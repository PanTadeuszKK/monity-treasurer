import unittest
from contextlib import closing
from datetime import date, datetime
from pathlib import Path
import sqlite3
import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
import test_finance as fixtures
from annual_fees import approve_fees
from finance_service import add_member, record_payment
from import_service import preview_rows, commit_import
from member_ledger import member_ledger
from member_status import change_status
from opening_balance import record_opening
from models import Base, Czlonek, Status, HistoriaNaliczen, Wpisowe, init_db
from report_service import export_cadence, cadence_report
from openpyxl import load_workbook


class MemberLedgerTests(unittest.TestCase):
    setUp = fixtures.FinanceTests.setUp
    tearDown = fixtures.FinanceTests.tearDown

    def ledger(self):
        return member_ledger(self.session, self.member.id)

    def test_import_retains_full_title_sender_bank_id_and_source_after_assignment(self):
        title = 'Składka za czerwiec\nJan Testowy — tytuł bez ID'
        frame = pd.DataFrame([['2026-06-15', '35.12', title, 'PLN', 'Nadawca Fikcyjny', 'bank-1']],
            columns=['Data operacji', 'Kwota', 'Opis transakcji', 'Waluta', 'Nazwa nadawcy', 'ID bankowe'])
        plan = preview_rows(self.session, frame, 'synthetic-hash', {'bank_id': 'ID bankowe'})
        commit_import(self.session, plan, [2], {2: self.member.id}, [2])
        row = self.ledger()['rows'][0]
        self.assertEqual(row.kind, 'Wpłata')
        self.assertEqual(row.cents, 3512)
        self.assertEqual(row.description, title)
        for value in (title, 'Nadawca Fikcyjny', 'bank-1', 'synthetic-hash', 'wiersz 2'):
            self.assertIn(value, row.details)
        self.assertEqual(row.date, date(2026, 6, 15))
        path = Path(self.tmp.name) / 'audit.xlsx'
        export_cadence(self.session, 2026, path)
        workbook = load_workbook(path)
        try:
            self.assertEqual(workbook['Wpłaty']['F2'].value, title)
            self.assertIn('Nadawca Fikcyjny', workbook['Wpłaty']['G2'].value)
            self.assertIn('bank-1', workbook['Wpłaty']['G2'].value)
        finally:
            workbook.close()

    def test_original_charges_both_corrections_and_reversal_remain_visible(self):
        self.calc.dodaj_naleznosc(2026, 6)
        status = self.session.query(Status).filter_by(nazwa='Premium').one()
        change_status(self.session, self.member, status.id, date(2026, 6, 1))
        self.session.commit()
        rates = {s.id: '40' if s.nazwa == 'Standard' else '80' for s in self.session.query(Status)}
        approve_fees(self.session, 2026, rates, date(2026, 10, 1))
        rows = self.ledger()['rows']
        self.assertEqual({r.kind for r in rows}, {'Składka miesięczna', 'Korekta stawki', 'Korekta statusu'})
        self.assertEqual(sum(r.cents for r in rows), -8000)
        self.assertEqual({r.period for r in rows}, {date(2026, 6, 1)})
        self.calc.zdejmij_naleznosc(2026, 6)
        rows = self.ledger()['rows']
        self.assertEqual(sum(r.cents for r in rows), 0)
        self.assertEqual(len([r for r in rows if r.state == 'Cofnięte']), 3)
        self.assertEqual(next(r.cents for r in rows if r.kind == 'Cofnięcie miesiąca'), 8000)

    def test_entry_fee_and_opening_revisions_are_separate_without_recharging(self):
        public_id, _ = add_member(self.session, 'Nowa Osoba', '', self.status.id,
            '-50', joined=date(2026, 6, 1), entry_fee=True)
        member = self.session.query(Czlonek).filter_by(numer_identyfikacyjny=public_id).one()
        record_opening(self.session, member.id, 2026, '-60', 'Uzgodniona poprawka')
        self.session.commit()
        ledger = member_ledger(self.session, member.id)
        self.assertEqual(ledger['balance'], -15500)
        entries = [r for r in ledger['rows'] if r.kind == 'Wpisowe']
        self.assertEqual([r.cents for r in entries], [-10500])
        self.assertIn('3 × 35.00', entries[0].description)
        openings = [r for r in ledger['rows'] if r.kind == 'Saldo początkowe']
        self.assertEqual(len(openings), 2)
        self.assertTrue(all(not r.affects_balance for r in openings))
        self.assertEqual(sum(r.state == 'Aktualna informacja' for r in openings), 1)
        self.assertEqual(sum(r.cents for r in ledger['rows'] if r.affects_balance), -10500)
        report = cadence_report(self.session, 2026)
        report_member = next(row for row in report['members'] if row['id'] == public_id)
        self.assertEqual(report_member['charges'], 10500)
        self.assertEqual(report['monthly'][6]['charges'], 10500)
        self.assertEqual([r['kind'] for r in report['charges']], ['Wpisowe'])

    def test_legacy_amount_and_old_entry_fee_are_not_guessed(self):
        self.session.add(HistoriaNaliczen(rok=2026, miesiac=6))
        self.session.commit()
        ledger = self.ledger()
        self.assertEqual(len(ledger['rows']), 1)
        self.assertIsNone(ledger['rows'][0].cents)
        self.assertFalse(ledger['rows'][0].affects_balance)
        self.assertIn('nie odtwarzamy', ledger['warning'])
        self.assertEqual(self.session.query(Wpisowe).count(), 0)

    def test_archived_member_manual_payment_has_actual_date(self):
        self.member.aktywny = False
        self.member.rok_odejscia, self.member.miesiac_odejscia = 2026, 6
        self.session.commit()
        record_payment(self.session, self.member.id, '10', datetime(2026, 9, 15), 'ledger-payment')
        ledger = self.ledger()
        self.assertTrue(ledger['archived'])
        self.assertEqual(ledger['rows'][0].date, date(2026, 9, 15))
        self.assertIn('ręczna', ledger['rows'][0].details)

    def test_entry_failure_rolls_back_member_opening_and_fee(self):
        with self.engine.begin() as connection:
            connection.execute(text("CREATE TRIGGER fail_entry BEFORE INSERT ON wpisowe BEGIN SELECT RAISE(ABORT,'test'); END"))
        with self.assertRaises(Exception):
            add_member(self.session, 'Nie zapisano', '', self.status.id, entry_fee=True)
        self.assertEqual(self.session.query(Czlonek).count(), 1)
        self.assertEqual(self.session.query(Wpisowe).count(), 0)

    def test_migration_8_backup_preserves_balances_and_does_not_invent_entry_fees(self):
        path = Path(self.tmp.name) / 'v7.db'
        old = create_engine('sqlite:///' + path.as_posix())
        Base.metadata.create_all(old, tables=[t for t in Base.metadata.sorted_tables if t.name != 'wpisowe'])
        with Session(old) as operation:
            operation.add(Czlonek(numer_identyfikacyjny=99, imie_nazwisko='Dawna Osoba', bilans_otwarcia=-115))
            operation.commit()
        old.dispose()
        for _ in range(2):
            engine = init_db(path)
            try:
                with Session(engine) as operation:
                    self.assertEqual(operation.query(Wpisowe).count(), 0)
                    self.assertEqual(operation.query(Czlonek).one().bilans_otwarcia, -115)
                    self.assertEqual(operation.execute(text('SELECT MAX(wersja) FROM wersja_schematu')).scalar(), 8)
            finally:
                engine.dispose()
        backups = list(path.parent.glob('v7.przed-migracja-8-*.db'))
        self.assertEqual(len(backups), 1)
        with closing(sqlite3.connect(backups[0])) as copy:
            self.assertIsNone(copy.execute("SELECT name FROM sqlite_master WHERE name='wpisowe'").fetchone())
            self.assertEqual(copy.execute('SELECT bilans_otwarcia FROM czlonkowie').fetchone()[0], -115)
