import unittest
from datetime import datetime
import pandas as pd
from sqlalchemy import text
import test_finance as fixtures
from models import Wplata, ImportWyciagu, PozycjaWyciagu
from import_service import preview_rows, commit_import, pending_imports, post_pending


class ImportTests(unittest.TestCase):
    setUp=fixtures.FinanceTests.setUp
    tearDown=fixtures.FinanceTests.tearDown

    def preview(self,rows=None,key='file1',ids=False,currency=None):
        rows=rows or [['2026-06-15','35','A!12','PLN']]
        columns=['Data operacji','Kwota','Opis transakcji','Waluta']+(['Bank ID'] if ids else [])
        return preview_rows(self.session,pd.DataFrame(rows,columns=columns),key,
                            {'bank_id':'Bank ID'} if ids else None,currency)

    def test_preview_and_repeat_file_and_overlap_are_safe(self):
        plan=self.preview()
        self.assertEqual(self.session.query(Wplata).count(),0)
        self.assertEqual(commit_import(self.session,plan,[2]),1)
        self.assertEqual(self.member.bilans_otwarcia,140)
        with self.assertRaises(ValueError): self.preview()
        overlap=self.preview(key='overlap')
        self.assertEqual(overlap.rows[0].state,'review')
        with self.assertRaises(ValueError): commit_import(self.session,overlap,[2])
        self.assertEqual(self.member.bilans_otwarcia,140)

    def test_two_real_identical_payments_require_confirmation_and_are_both_preserved(self):
        plan=self.preview([['2026-06-15','35','A!12','PLN']]*2)
        self.assertEqual([r.state for r in plan.rows],['review','review'])
        self.assertEqual(commit_import(self.session,plan,[2,3],confirmed_new=[2,3]),2)
        self.assertEqual(self.member.bilans_otwarcia,175)

    def test_bank_id_duplicate_cannot_be_overridden(self):
        rows=[['2026-06-15','35','A!12','PLN','unique-1']]
        commit_import(self.session,self.preview(rows,ids=True),[2])
        plan=self.preview(rows,key='other',ids=True)
        self.assertEqual(plan.rows[0].state,'duplicate')
        with self.assertRaises(ValueError): commit_import(self.session,plan,[2],confirmed_new=[2])
        self.assertEqual(self.session.query(Wplata).count(),1)

    def test_invalid_amount_date_currency_never_falls_back_to_today(self):
        for row in [['bad','35','A!12','PLN'],['2026-06-15','NaN','A!12','PLN'],
                    ['2026-06-15','-35','A!12','PLN'],['2026-06-15','35','A!12','EUR'],
                    ['2026-06-15','1.001','A!12','PLN']]:
            plan=self.preview([row])
            self.assertEqual(plan.rows[0].state,'invalid')
            with self.assertRaises(ValueError): commit_import(self.session,plan,[2])
        self.assertEqual(self.session.query(Wplata).count(),0)

    def test_missing_currency_requires_explicit_full_file_declaration(self):
        frame=pd.DataFrame([['2026-06-15','35','A!12']],columns=['Data operacji','Kwota','Opis transakcji'])
        with self.assertRaises(ValueError): preview_rows(self.session,frame,'file')
        plan=preview_rows(self.session,frame,'file',currency='PLN')
        self.assertEqual(plan.rows[0].state,'ready')

    def test_id_boundaries_and_multiple_ids_require_manual_assignment(self):
        for title in ['A!112','A!12 A!112','XA!12','A!12abc','Brak ID']:
            self.assertEqual(self.preview([['2026-06-15','35',title,'PLN']]).rows[0].state,'review')
        plan=self.preview([['2026-06-15','35','Brak ID','PLN']])
        self.assertEqual(commit_import(self.session,plan,[2],{2:self.member.id},[2]),1)
        self.assertEqual(self.member.bilans_otwarcia,140)

    def test_archived_member_can_pay_old_debt(self):
        self.member.aktywny=False
        self.member.rok_odejscia,self.member.miesiac_odejscia=2026,6
        self.session.commit()
        self.assertEqual(commit_import(self.session,self.preview(),[2]),1)
        self.assertFalse(self.member.aktywny)

    def test_invalid_later_row_rolls_back_whole_selected_import(self):
        plan=self.preview([['2026-06-15','35','A!12','PLN'],['bad','35','A!12','PLN']])
        with self.assertRaises(ValueError): commit_import(self.session,plan,[2,3])
        self.assertEqual(self.session.query(Wplata).count(),0)
        self.assertEqual(self.session.query(ImportWyciagu).count(),0)
        self.assertEqual(self.member.bilans_otwarcia,105)

    def test_database_error_rolls_back_balances_and_provenance(self):
        with self.engine.begin() as connection:
            connection.execute(text("CREATE TRIGGER fail_import BEFORE INSERT ON pozycje_wyciagow BEGIN SELECT RAISE(ABORT,'test'); END"))
        with self.assertRaises(Exception): commit_import(self.session,self.preview(),[2])
        self.session.expire_all()
        self.assertEqual(self.member.bilans_otwarcia,105)
        self.assertEqual(self.session.query(Wplata).count(),0)

    def test_unmatched_rows_persist_for_manual_review_and_cannot_be_posted_twice(self):
        plan=self.preview([['2026-06-15','35','A!12','PLN'],['2026-06-16','40','Brak ID','PLN']])
        commit_import(self.session,plan,[2])
        queue=pending_imports(self.engine)
        self.assertEqual(len(queue),1)
        record_id=queue[0]['id']
        post_pending(self.session,[record_id],{record_id:self.member.id})
        self.assertEqual(self.member.bilans_otwarcia,180)
        self.assertEqual(pending_imports(self.engine),[])
        with self.assertRaises(ValueError): post_pending(self.session,[record_id],{record_id:self.member.id})

    def test_old_payment_without_provenance_is_detected_as_possible_overlap(self):
        self.session.add(Wplata(czlonek_id=self.member.id,kwota=35,data_przelewu=datetime(2026,6,15),tytul_oryginalny='A!12'))
        self.session.commit()
        self.assertEqual(self.preview().rows[0].state,'review')

    def test_explicit_polish_date_format_and_excel_dates(self):
        frame=pd.DataFrame([['15.06.2026','35','A!12','PLN']],columns=['Data operacji','Kwota','Opis transakcji','Waluta'])
        self.assertEqual(preview_rows(self.session,frame,'p',date_format='%d.%m.%Y').rows[0].paid_on,datetime(2026,6,15))
        self.assertEqual(self.preview([[datetime(2026,6,15),'35','A!12','PLN']]).rows[0].state,'ready')

    def test_sender_preserved_in_preview_and_pending_without_auto_name_match(self):
        frame=pd.DataFrame([["2026-06-15","35","Składka","PLN","Osoba Testowa"]],
            columns=["Data operacji","Kwota","Opis transakcji","Waluta","Nazwa nadawcy"])
        plan=preview_rows(self.session,frame,"sender-test")
        self.assertEqual(plan.rows[0].sender,"Osoba Testowa")
        self.assertEqual(plan.rows[0].state,"review")
        self.assertIsNone(plan.rows[0].member_id)
        commit_import(self.session,
            preview_rows(self.session,pd.concat([frame,pd.DataFrame([["2026-06-16","10","A!12","PLN",""]],columns=frame.columns)],ignore_index=True),"sender-test"),[3])
        pending=pending_imports(self.engine)
        self.assertEqual(pending[0]["sender"],"Osoba Testowa")
        post_pending(self.session,[pending[0]["id"]],{pending[0]["id"]:self.member.id})
        self.assertEqual(self.session.query(Wplata).count(),2)

    def test_optional_sender_mapping_and_missing_column(self):
        frame=pd.DataFrame([["2026-06-15","35","A!12","PLN","Nadawca Testowy"]],columns=["Data operacji","Kwota","Opis transakcji","Waluta","Kontrahent"])
        self.assertEqual(preview_rows(self.session,frame,"mapped",{"sender":"Kontrahent"}).rows[0].sender,"Nadawca Testowy")
        self.assertEqual(preview_rows(self.session,frame,"missing").rows[0].sender,"")

    def test_transaction_title_label_is_shown_once_without_changing_source(self):
        from import_service import transaction_details
        for title in ("Składka", "Tytuł: Składka", " TYTUŁ : Tytuł: Składka"):
            self.assertEqual(transaction_details(title,"Jan Testowy"),"Tytuł: Składka\nNazwa nadawcy: Jan Testowy")
        self.assertIn("Składka: lipiec",transaction_details("Tytuł: Składka: lipiec"))
