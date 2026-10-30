import unittest
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
import test_finance as fixtures
from annual_fees import cadence_year
from finance_service import add_member, record_payment
from opening_balance import opening_balances, opening_description, record_opening
from models import Base, Czlonek, SaldoPoczatkoweKadencji, init_db
from mail_service import preview_batch, prepare_batch, DEFAULT_SUBJECT, DEFAULT_TEMPLATE

class OpeningBalanceTests(unittest.TestCase):
    setUp=fixtures.FinanceTests.setUp
    tearDown=fixtures.FinanceTests.tearDown

    def test_creation_preserves_input_before_entry_fee_and_later_operations(self):
        today=date.today();year=cadence_year(today.year,today.month)
        public_id,_=add_member(self.session,'Nowa Osoba','new@example.invalid',self.status.id,'-50',entry_fee=True)
        member=self.session.query(Czlonek).filter_by(numer_identyfikacyjny=public_id).one()
        self.assertEqual(opening_balances(self.session,year)[member.id],-5000)
        record_payment(self.session,member.id,'10',datetime.now(),'opening-test')
        self.calc.dodaj_naleznosc(year,6)
        self.assertEqual(opening_balances(self.session,year)[member.id],-5000)

    def test_revisions_do_not_change_balance_or_duplicate_same_amount(self):
        today=date.today();year=cadence_year(today.year,today.month)
        before=self.member.bilans_otwarcia
        record_opening(self.session,self.member.id,year,'-10','Test')
        self.session.commit()
        record_opening(self.session,self.member.id,year,'-10.00','Test')
        self.session.commit()
        self.assertEqual(self.session.query(SaldoPoczatkoweKadencji).count(),1)
        record_opening(self.session,self.member.id,year,'20','Korekta')
        self.session.commit()
        self.assertEqual(self.session.query(SaldoPoczatkoweKadencji).count(),2)
        self.assertEqual(opening_balances(self.session,year)[self.member.id],2000)
        self.assertEqual(self.member.bilans_otwarcia,before)
        self.assertNotIn(self.member.id,opening_balances(self.session,year-1))

    def test_description_distinguishes_debt_credit_zero_and_unknown(self):
        self.assertIn('Zaległość',opening_description(-5000,2026))
        self.assertIn('Nadpłata',opening_description(5000,2026))
        self.assertIn('bez zaległości',opening_description(0,2026))
        self.assertIn('nieuzupełnione',opening_description(None,2026))

    def test_mail_credit_and_opening_are_separate_and_stale_opening_blocks_send(self):
        today=date.today();year=cadence_year(today.year,today.month)
        self.member.email='member@example.invalid';self.session.commit()
        def plan():return preview_batch(self.session,'sender@example.invalid','active',DEFAULT_SUBJECT,DEFAULT_TEMPLATE)
        self.assertIn('nieuzupełnione',plan().items[0].body)
        for balance in (-35,0,25):
            self.member.bilans_otwarcia=balance;self.session.commit()
            body=plan().items[0].body
            self.assertIn(f'Do zapłaty na dziś: {max(-balance,0):.2f} PLN',body)
            self.assertIn(f'Nadpłata na dziś: {max(balance,0):.2f} PLN',body)
        old=plan()
        record_opening(self.session,self.member.id,year,'-50','Test');self.session.commit()
        self.assertIn('Zaległość przeniesiona',plan().items[0].body)
        with self.assertRaisesRegex(ValueError,'zmieniły'):
            prepare_batch(self.session,old,[self.member.id])

    def test_migration_6_backup_and_unknown_old_balance(self):
        path=Path(self.tmp.name)/'v5.db'
        old=create_engine('sqlite:///'+path.as_posix())
        Base.metadata.create_all(old,tables=[t for t in Base.metadata.sorted_tables if t.name!='salda_poczatkowe_kadencji'])
        old.dispose()
        for _ in range(2):
            engine=init_db(path)
            with Session(engine) as session:
                self.assertEqual(session.execute(text('SELECT MAX(wersja) FROM wersja_schematu')).scalar(),8)
                self.assertEqual(session.query(SaldoPoczatkoweKadencji).count(),0)
            engine.dispose()
        self.assertEqual(len(list(path.parent.glob('v5.przed-migracja-6-*.db'))),1)
