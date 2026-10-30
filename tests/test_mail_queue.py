import os
import threading
import unittest
from unittest.mock import patch
from sqlalchemy.orm import Session
import test_finance as fixtures
from models import Czlonek, WysylkaEmail
from mail_service import (preview_batch, prepare_batch, prepare_single, send_campaign,
                          delivery_rows, retry_failed, DEFAULT_SUBJECT, DEFAULT_TEMPLATE)


class MailQueueTests(unittest.TestCase):
    setUp = fixtures.FinanceTests.setUp
    tearDown = fixtures.FinanceTests.tearDown
    config = {'email':'sender@example.invalid','haslo':'fake'}

    def plan(self,scope='active'):
        self.member.email = 'member@example.invalid'
        self.session.commit()
        return preview_batch(self.session,self.config['email'],scope,DEFAULT_SUBJECT,DEFAULT_TEMPLATE)

    def test_preview_does_not_enqueue_and_sends_only_personalized_content(self):
        plan = self.plan()
        self.assertEqual(self.session.query(WysylkaEmail).count(),0)
        self.assertIn('105.00',plan.items[0].body)
        self.assertIn('Osoba Testowa',plan.items[0].body)
        with patch.dict(os.environ,{'MONITY_MAIL_DRY_RUN':'1'}), patch('mailer.smtplib.SMTP') as smtp:
            campaign,count,duplicates = prepare_batch(self.session,plan,[self.member.id])
            send_campaign(self.engine,campaign,self.config,threading.Event(),interval=0)
            smtp.assert_not_called()
            self.assertEqual((count,duplicates),(1,0))
            self.assertEqual(delivery_rows(self.engine,campaign)[0]['state'],'accepted')
            self.assertEqual(delivery_rows(self.engine,campaign)[0]['mode'],'simulation')
            with self.assertRaisesRegex(ValueError,'rejestrze'):
                prepare_batch(self.session,plan,[self.member.id])

    def test_real_and_simulated_keys_are_separate(self):
        plan = self.plan()
        with patch.dict(os.environ,{'MONITY_MAIL_DRY_RUN':'1'}):
            prepare_batch(self.session,plan,[self.member.id])
        with patch.dict(os.environ,{'MONITY_MAIL_DRY_RUN':'0'}):
            prepare_batch(self.session,plan,[self.member.id])
        self.assertEqual(self.session.query(WysylkaEmail).count(),2)

    def test_changed_balance_or_address_requires_new_preview(self):
        plan = self.plan()
        self.member.bilans_otwarcia = -20
        self.session.commit()
        with self.assertRaisesRegex(ValueError,'zmieniły'):
            prepare_batch(self.session,plan,[self.member.id])
        self.assertEqual(self.session.query(WysylkaEmail).count(),0)

    def test_archived_debtor_included_bad_addresses_listed(self):
        self.member.aktywny, self.member.bilans_otwarcia = False,-10
        plan = self.plan('debt')
        self.assertEqual(len(plan.items),1)
        self.assertEqual(len(self.plan('active').items),0)
        self.member.email = 'bad-address'
        self.session.commit()
        plan = preview_batch(self.session,self.config['email'],'debt',DEFAULT_SUBJECT,DEFAULT_TEMPLATE)
        self.assertEqual(len(plan.items),0)
        self.assertEqual(len(plan.skipped),1)

    def test_template_injection_and_invalid_subject_rejected(self):
        for body in ['{imie.__class__}', '{imie!r}', '{imie:>100}', '{unknown}']:
            with self.assertRaises(ValueError):
                preview_batch(self.session,self.config['email'],'active','Temat',body)
        with self.assertRaises(ValueError):
            preview_batch(self.session,self.config['email'],'active','Bad\nBcc: test','Body')

    def test_uncertain_delivery_is_durable_and_never_retried(self):
        plan = self.plan()
        campaign,_,_ = prepare_batch(self.session,plan,[self.member.id])
        class Fake:
            delivery_state = 'uncertain'
            def __init__(self,*args): pass
            def wyslij_wiadomosc(self,*args,**kwargs): return False,'Niepewny wynik.'
        with patch('mail_service.Mailer',Fake):
            send_campaign(self.engine,campaign,self.config,threading.Event(),interval=0)
        self.assertEqual(delivery_rows(self.engine,campaign)[0]['state'],'uncertain')
        self.assertEqual(retry_failed(self.engine,campaign),0)
        with patch('mail_service.Mailer') as mailer:
            send_campaign(self.engine,campaign,self.config,threading.Event(),interval=0)
            mailer.assert_not_called()

    def test_crash_after_claim_does_not_allow_automatic_duplicate(self):
        plan = self.plan()
        campaign,_,_ = prepare_batch(self.session,plan,[self.member.id])
        with Session(self.engine) as operation:
            row=operation.query(WysylkaEmail).one()
            row.stan='sending'
            operation.commit()
        with patch('mail_service.Mailer') as mailer:
            send_campaign(self.engine,campaign,self.config,threading.Event(),interval=0)
            mailer.assert_not_called()
        self.assertEqual(retry_failed(self.engine,campaign),0)

    def test_known_failure_requires_explicit_retry(self):
        campaign,_,_ = prepare_batch(self.session,self.plan(),[self.member.id])
        class Fake:
            delivery_state='not_sent'
            def __init__(self,*args): pass
            def wyslij_wiadomosc(self,*args,**kwargs): return False,'Brak połączenia.'
        with patch('mail_service.Mailer',Fake):
            send_campaign(self.engine,campaign,self.config,threading.Event(),interval=0)
        with patch('mail_service.Mailer') as mailer:
            send_campaign(self.engine,campaign,self.config,threading.Event(),interval=0)
            mailer.assert_not_called()
        self.assertEqual(retry_failed(self.engine,campaign),1)
        self.assertEqual(delivery_rows(self.engine,campaign)[0]['state'],'pending')

    def test_cancel_before_send_preserves_pending(self):
        campaign,_,_ = prepare_batch(self.session,self.plan(),[self.member.id])
        stop=threading.Event(); stop.set()
        with patch('mail_service.Mailer') as mailer:
            send_campaign(self.engine,campaign,self.config,stop,interval=0)
            mailer.assert_not_called()
        self.assertEqual(delivery_rows(self.engine,campaign)[0]['state'],'pending')

    def test_mode_mismatch_cannot_send_simulation_as_real(self):
        with patch.dict(os.environ,{'MONITY_MAIL_DRY_RUN':'1'}):
            campaign,_,_ = prepare_batch(self.session,self.plan(),[self.member.id])
        with patch.dict(os.environ,{'MONITY_MAIL_DRY_RUN':'0'}), patch('mail_service.Mailer') as mailer:
            with self.assertRaises(ValueError):
                send_campaign(self.engine,campaign,self.config,threading.Event(),interval=0)
            mailer.assert_not_called()

    def test_single_reminder_uses_same_durable_protection(self):
        self.plan()
        campaign=prepare_single(self.session,self.member.id,self.config['email'],self.member.email,'Temat','Treść')
        with self.assertRaises(ValueError):
            prepare_single(self.session,self.member.id,self.config['email'],self.member.email,'Temat','Treść')
        self.assertEqual(len(delivery_rows(self.engine,campaign)),1)

    def test_500_member_preview_and_queue(self):
        self.member.email='member@example.invalid'
        self.session.add_all(Czlonek(numer_identyfikacyjny=100+i,imie_nazwisko=f'Osoba {i:03}',
            email=f'member{i}@example.invalid',status_id=self.status.id,aktywny=True,bilans_otwarcia=-35,
            rok_dolaczenia=2026,miesiac_dolaczenia=6) for i in range(499))
        self.session.commit()
        plan=preview_batch(self.session,self.config['email'],'active',DEFAULT_SUBJECT,DEFAULT_TEMPLATE)
        self.assertEqual(len(plan.items),500)
        campaign,count,duplicates=prepare_batch(self.session,plan,[item.member_id for item in plan.items])
        self.assertEqual((count,duplicates),(500,0))
        self.assertEqual(len(delivery_rows(self.engine,campaign)),500)

    def test_bulk_transfer_details_are_saved_as_html_with_red_note(self):
        plan=self.plan()
        self.assertIn("[numer rachunku do uzupełnienia]",plan.items[0].body)
        self.assertIn("składka Osoba Testowa A!12",plan.items[0].body)
        campaign,_,_=prepare_batch(self.session,plan,[self.member.id])
        row=self.session.query(WysylkaEmail).filter_by(kampania=campaign).one()
        self.assertTrue(row.czy_html)
        self.assertIn("color: #B00020;",row.tresc)
        self.assertIn("[nazwa firmy do uzupełnienia]",row.tresc)
