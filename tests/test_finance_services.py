import unittest
from datetime import datetime, date
from pathlib import Path
from unittest.mock import patch
from sqlalchemy import text, create_engine
from sqlalchemy.orm import Session
from openpyxl import load_workbook
import test_finance as fixtures
from finance_service import add_member, record_payment, signed_amount, bank_account
from report_service import cadence_report, export_cadence
from annual_fees import approve_fees
from models import Base, Czlonek, Wplata, HistoriaNaliczen, OperacjaReczna, init_db


class FinanceServicesTests(unittest.TestCase):
    setUp=fixtures.FinanceTests.setUp
    tearDown=fixtures.FinanceTests.tearDown

    def test_manual_payment_is_idempotent_and_preserves_date(self):
        first=record_payment(self.session,self.member.id,'35,50',datetime(2026,6,15),'token1')
        self.assertEqual(record_payment(self.session,self.member.id,'35,50',datetime(2026,6,15),'token1'),first)
        self.assertEqual(self.member.bilans_otwarcia,140.5)
        self.assertEqual(self.session.query(Wplata).count(),1)
        self.assertEqual(self.session.query(Wplata).one().data_przelewu,datetime(2026,6,15))
        with self.assertRaises(ValueError): record_payment(self.session,self.member.id,'40',datetime(2026,6,15),'token1')

    def test_manual_payment_does_not_commit_other_window_edit(self):
        member_id=self.member.id
        self.member.email='pending@example.invalid'
        record_payment(self.session,member_id,'35',datetime(2026,6,15),'token1')
        with Session(self.engine) as operation:
            self.assertIsNone(operation.get(Czlonek,member_id).email)
        self.session.rollback()

    def test_manual_payment_trigger_failure_rolls_back_all(self):
        with self.engine.begin() as connection:
            connection.execute(text("CREATE TRIGGER fail_manual BEFORE INSERT ON operacje_reczne BEGIN SELECT RAISE(ABORT,'test'); END"))
        with self.assertRaises(Exception): record_payment(self.session,self.member.id,'35',datetime(2026,6,15),'token1')
        self.session.expire_all()
        self.assertEqual(self.member.bilans_otwarcia,105)
        self.assertEqual(self.session.query(Wplata).count(),0)

    def test_signed_amount_and_account_validation(self):
        self.assertEqual(signed_amount('-35,50'),-35.5)
        for amount in ['NaN','Infinity','-Infinity','1.001','1e999']:
            with self.assertRaises(ValueError): signed_amount(amount)
        self.assertEqual(bank_account('PL61 1090 1014 0000 0712 1981 2874'),'61109010140000071219812874')
        for account in ['123','61109010140000071219812875','a'*26]:
            with self.assertRaises(ValueError): bank_account(account)

    def test_member_creation_validates_fields_and_allocates_stable_id(self):
        public_id,amount=add_member(self.session,'Nowa Osoba','new@example.invalid',self.status.id,'-35,50',joined=date(2026,6,1))
        self.assertEqual(public_id,13)
        self.assertEqual(amount,-35.5)
        member=self.session.query(Czlonek).filter_by(numer_identyfikacyjny=public_id).one()
        self.assertEqual((member.rok_dolaczenia,member.miesiac_dolaczenia),(2026,6))
        with self.assertRaises(ValueError): add_member(self.session,'','',self.status.id)
        with self.assertRaises(ValueError): add_member(self.session,'Bad Email','invalid',self.status.id)
        self.assertEqual(self.session.query(Czlonek).count(),2)

    def test_duplicate_bank_account_does_not_create_partial_member(self):
        account='61109010140000071219812874'
        add_member(self.session,'Osoba Jedna','',self.status.id,account=account)
        with self.assertRaises(ValueError): add_member(self.session,'Osoba Druga','',self.status.id,account=account)
        self.assertEqual(self.session.query(Czlonek).count(),2)

    def test_report_uses_saved_charges_corrections_and_actual_payment_dates(self):
        self.calc.dodaj_naleznosc(2026,6)
        from models import Status
        rates={s.id:'40' if s.nazwa=='Standard' else '70' for s in self.session.query(Status)}
        approve_fees(self.session,2026,rates,date(2026,10,1))
        record_payment(self.session,self.member.id,'20',datetime(2026,8,15),'p1')
        report=cadence_report(self.session,2026)
        self.assertEqual(report['members'][0]['charges'],4000)
        self.assertEqual(sum(report['members'][0]['payments']),2000)
        self.assertEqual(report['monthly'][6]['charges'],4000)
        self.assertEqual(report['monthly'][8]['payments'],2000)
        self.assertTrue(self.calc.zdejmij_naleznosc(2026,6)[0])
        report=cadence_report(self.session,2026)
        self.assertEqual(report['members'][0]['charges'],0)
        self.assertTrue(report['charges'][0]['reversed'])

    def test_report_archived_and_unknown_history_are_explicit(self):
        self.member.aktywny=False
        self.member.rok_odejscia,self.member.miesiac_odejscia=2026,9
        self.session.add(HistoriaNaliczen(rok=2026,miesiac=6))
        self.session.commit()
        row=cadence_report(self.session,2026)['members'][0]
        self.assertTrue(row['archived'])
        self.assertEqual(row['left'],'2026-09')
        self.assertIn('Brak kwot',row['note'])

    def test_excel_export_is_valid_and_member_text_cannot_execute_formulas(self):
        self.member.imie_nazwisko='=HYPERLINK("https://example.invalid")'
        self.session.commit()
        path=Path(self.tmp.name)/'report.xlsx'
        export_cadence(self.session,2026,path)
        workbook=load_workbook(path,data_only=False)
        self.assertEqual(workbook['Klienci']['B2'].data_type,'s')
        self.assertEqual(workbook['Klienci']['U2'].value,'Brak wiarygodnych danych')
        self.assertEqual(len(workbook.sheetnames),5)
        workbook.close()

    def test_empty_database_report_exports(self):
        self.session.delete(self.member)
        self.session.commit()
        report=export_cadence(self.session,2026,Path(self.tmp.name)/'empty.xlsx')
        self.assertEqual(report['members'],[])

    def test_migration_5_creates_backup_and_preserves_previous_rows(self):
        path=Path(self.tmp.name)/'v4.db'
        old=create_engine('sqlite:///'+path.as_posix())
        Base.metadata.create_all(old,tables=[t for t in Base.metadata.sorted_tables if t.name not in
            {'wysylki_email','importy_wyciagow','pozycje_wyciagow','operacje_reczne'}])
        old.dispose()
        for _ in range(2):
            engine=init_db(path)
            with Session(engine) as operation:
                self.assertEqual(operation.execute(text('SELECT MAX(wersja) FROM wersja_schematu')).scalar(),8)
            engine.dispose()
        self.assertEqual(len(list(Path(self.tmp.name).glob('v4.przed-migracja-5-*.db'))),1)
