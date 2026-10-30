from contextlib import closing
import sqlite3
import tempfile
import os
from unittest.mock import patch
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import text, create_engine
from sqlalchemy.orm import Session

from backup import backup_database
from paths import data_path, PROJECT_DIR
from fee_service import parse_amount, update_fees
from logic import KalkulatorSkladek
from models import (Base, init_db, Czlonek, Status, HistoriaNaliczen,
                    NaliczenieMiesiaca, NaliczenieCzlonka)


class FinanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'test.db'
        self.engine = init_db(self.path)
        self.session = Session(self.engine)
        self.status = self.session.query(Status).filter_by(nazwa='Standard').one()
        self.member = Czlonek(numer_identyfikacyjny=12, imie_nazwisko='Osoba Testowa',
            status=self.status, bilans_otwarcia=105, aktywny=True,
            rok_dolaczenia=2026, miesiac_dolaczenia=6)
        self.session.add(self.member)
        self.session.commit()
        self.calc = KalkulatorSkladek(self.session)

    def tearDown(self):
        self.session.close()
        self.engine.dispose()
        self.tmp.cleanup()

    def test_reversal_uses_original_amount_and_membership(self):
        self.assertTrue(self.calc.dodaj_naleznosc(2026, 6)[0])
        update_fees(self.session, {self.status.id: '65'})
        self.member.rok_dolaczenia = 2027
        self.member.status = None
        self.session.commit()
        self.assertTrue(self.calc.zdejmij_naleznosc(2026, 6)[0])
        self.assertEqual(self.member.bilans_otwarcia, 105)
        self.assertEqual(self.session.query(NaliczenieCzlonka).one().kwota_grosze, 3500)
        self.assertIsNotNone(self.session.query(NaliczenieMiesiaca).one().cofnieto)
        self.assertFalse(self.calc.zdejmij_naleznosc(2026, 6)[0])

    def test_duplicate_and_new_cycle_preserve_history(self):
        self.assertTrue(self.calc.dodaj_naleznosc(2026, 6)[0])
        self.assertFalse(self.calc.dodaj_naleznosc(2026, 6)[0])
        self.assertEqual(self.member.bilans_otwarcia, 70)
        self.assertTrue(self.calc.zdejmij_naleznosc(2026, 6)[0])
        self.assertTrue(self.calc.dodaj_naleznosc(2026, 6)[0])
        self.assertEqual(self.session.query(NaliczenieMiesiaca).count(), 2)

    def test_archived_member_charged_through_departure_month(self):
        self.member.aktywny = False
        self.member.rok_odejscia = 2026
        self.member.miesiac_odejscia = 9
        self.session.commit()
        for month in (6, 7, 8, 9, 10):
            self.assertTrue(self.calc.dodaj_naleznosc(2026, month)[0])
        self.assertEqual(self.member.bilans_otwarcia, -35)
        self.assertEqual(self.session.query(NaliczenieCzlonka).count(), 4)

    def test_invalid_later_member_rolls_back_entire_month(self):
        self.session.add(Czlonek(numer_identyfikacyjny=13, imie_nazwisko='Druga Osoba',
            status=None, bilans_otwarcia=0, aktywny=True, rok_dolaczenia=2026, miesiac_dolaczenia=6))
        self.session.commit()
        self.assertFalse(self.calc.dodaj_naleznosc(2026, 6)[0])
        self.session.expire_all()
        self.assertEqual(self.member.bilans_otwarcia, 105)
        self.assertEqual(self.session.query(NaliczenieMiesiaca).count(), 0)

    def test_legacy_cannot_be_reversed_or_duplicated(self):
        self.session.add(HistoriaNaliczen(rok=2025, miesiac=12))
        self.session.commit()
        self.assertFalse(self.calc.zdejmij_naleznosc(2025, 12)[0])
        self.assertFalse(self.calc.dodaj_naleznosc(2025, 12)[0])
        self.assertEqual(self.member.bilans_otwarcia, 105)

    def test_invalid_fee_does_not_change_earlier_status(self):
        statuses = self.session.query(Status).order_by(Status.id).all()
        with self.assertRaises(ValueError):
            update_fees(self.session, {statuses[0].id: '70', statuses[1].id: 'abc'})
        self.session.expire_all()
        self.assertEqual(statuses[0].kwota, 35)

    def test_fee_transaction_does_not_commit_pending_member_edit(self):
        status_id, member_id = self.status.id, self.member.id
        self.member.email = 'pending@example.invalid'
        update_fees(self.session, {status_id: '35,50'})
        with Session(self.engine) as other:
            self.assertIsNone(other.get(Czlonek, member_id).email)
            self.assertEqual(other.get(Status, status_id).kwota, 35.5)
        self.session.rollback()

    def test_validation(self):
        for value in ['NaN', 'Infinity', '-1', '0', '1.001', 'abc', '1e999']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_amount(value)
        self.assertEqual(parse_amount('35,50'), Decimal('35.50'))
        self.assertFalse(self.calc.dodaj_naleznosc(2026, 13)[0])

    def test_foreign_keys(self):
        with self.engine.connect() as connection:
            self.assertEqual(connection.execute(text('PRAGMA foreign_keys')).scalar(), 1)

    def test_backup_and_restore_wal(self):
        with closing(sqlite3.connect(self.path)) as src:
            src.execute('PRAGMA journal_mode=WAL')
            src.execute('CREATE TABLE backup_test (value INTEGER)')
            src.execute('INSERT INTO backup_test VALUES (42)')
            src.commit()
            copy = Path(self.tmp.name) / 'copy.db'
            backup_database(self.path, copy)
            restored = Path(self.tmp.name) / 'restored.db'
            backup_database(copy, restored)
            with closing(sqlite3.connect(restored)) as dst:
                self.assertEqual(dst.execute('SELECT value FROM backup_test').fetchone(), (42,))
            with self.assertRaises(FileExistsError):
                backup_database(self.path, copy)

    def test_calendar_year_boundary(self):
        for year, month in [(2026, 12), (2027, 1)]:
            self.assertTrue(self.calc.dodaj_naleznosc(year, month)[0])
        self.assertEqual(self.member.bilans_otwarcia, 35)
        self.assertTrue(self.calc.zdejmij_naleznosc(2026, 12)[0])
        self.assertEqual(self.member.bilans_otwarcia, 70)
        self.assertTrue(self.calc.czy_naliczone(2027, 1))

    def test_data_directory(self):
        import paths
        no_pointer = patch.object(paths, 'POINTER_FILE', Path(self.tmp.name) / 'brak-wskazania.txt')
        with patch.dict(os.environ, {}, clear=True), no_pointer:
            self.assertEqual(data_path('monity.db'), PROJECT_DIR / 'monity.db')
        with patch.dict(os.environ, {'MONITY_DATA_DIR': self.tmp.name}):
            self.assertEqual(data_path('monity.db'), Path(self.tmp.name).resolve() / 'monity.db')
        with patch.dict(os.environ, {'MONITY_DATA_DIR': 'relative'}):
            with self.assertRaises(ValueError):
                data_path('monity.db')

    def test_legacy_migration_creates_backup_and_keeps_balance(self):
        legacy = Path(self.tmp.name) / 'legacy.db'
        old_engine = create_engine('sqlite:///' + legacy.as_posix())
        old_tables = [table for table in Base.metadata.sorted_tables
                      if table.name not in {'naliczenia_miesiecy', 'naliczenia_czlonkow', 'wersja_schematu'}]
        Base.metadata.create_all(old_engine, tables=old_tables)
        with Session(old_engine) as old_session:
            old_session.add(Czlonek(numer_identyfikacyjny=77, imie_nazwisko='Dawna Osoba',
                bilans_otwarcia=-123.45, aktywny=True, rok_dolaczenia=2025, miesiac_dolaczenia=6))
            old_session.add(HistoriaNaliczen(rok=2025, miesiac=6))
            old_session.commit()
        old_engine.dispose()
        engine = init_db(legacy)
        with Session(engine) as migrated:
            self.assertEqual(migrated.query(Czlonek).one().bilans_otwarcia, -123.45)
            self.assertEqual(migrated.query(HistoriaNaliczen).count(), 1)
        engine.dispose()
        copies = list(Path(self.tmp.name).glob('legacy.przed-migracja-1-*.db'))
        self.assertEqual(len(copies), 1)
        with closing(sqlite3.connect(copies[0])) as conn:
            self.assertEqual(conn.execute('SELECT bilans_otwarcia FROM czlonkowie').fetchone(), (-123.45,))
        engine = init_db(legacy)
        engine.dispose()
        self.assertEqual(len(list(Path(self.tmp.name).glob('legacy.przed-migracja-1-*.db'))), 1)


if __name__ == '__main__':
    unittest.main()
