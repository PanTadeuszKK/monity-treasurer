import unittest
from datetime import date
from pathlib import Path
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
import test_finance as fixtures
from annual_fees import approve_fees, preview_fees, bulk_history
from member_status import change_status
from models import (Base, Status, Czlonek, ZmianaStatusu, KorektaStatusu, HistoriaNaliczen,
                    NaliczenieCzlonka, StatusNaliczenia, init_db)


class MemberStatusTests(unittest.TestCase):
    setUp = fixtures.FinanceTests.setUp
    tearDown = fixtures.FinanceTests.tearDown

    def premium(self):
        return self.session.query(Status).filter_by(nazwa='Premium').one().id

    def change(self, month=6):
        member_id = self.member.id
        status_id = self.premium()
        with Session(self.engine) as operation:
            operation.execute(text('BEGIN IMMEDIATE'))
            delta = change_status(operation, operation.get(Czlonek, member_id), status_id, date(2026, month, 1))
            operation.commit()
        self.session.expire_all()
        return delta

    def rates(self):
        return {s.id: '40' if s.nazwa == 'Standard' else '80' for s in self.session.query(Status)}

    def test_june_change_after_charges_corrects_all_months_then_october_rates(self):
        for month in (6, 7, 8, 9):
            self.calc.dodaj_naleznosc(2026, month)
        self.assertEqual(self.change(), 12000)
        self.assertEqual(self.member.bilans_otwarcia, -155)
        self.assertEqual([c.kwota_grosze for c in self.session.query(NaliczenieCzlonka)], [3500] * 4)
        plan = approve_fees(self.session, 2026, self.rates(), date(2026, 10, 1))
        self.assertEqual(plan.total_cents, 6000)
        self.assertEqual(self.member.bilans_otwarcia, -215)
        self.assertTrue(approve_fees(self.session, 2026, self.rates(), date(2026, 10, 1)).unchanged)
        self.assertEqual(self.member.bilans_otwarcia, -215)
        self.assertTrue(self.calc.zdejmij_naleznosc(2026, 6)[0])
        self.assertEqual(self.member.bilans_otwarcia, -135)
        self.assertTrue(self.calc.dodaj_naleznosc(2026, 6)[0])
        self.assertEqual(self.member.bilans_otwarcia, -215)

    def test_change_mid_cadence_preserves_prior_months(self):
        for month in (6, 7, 8, 9):
            self.calc.dodaj_naleznosc(2026, month)
        self.assertEqual(self.change(8), 6000)
        plan = approve_fees(self.session, 2026, self.rates(), date(2026, 10, 1))
        self.assertEqual(plan.total_cents, 4000)
        self.assertEqual(self.member.bilans_otwarcia, -135)

    def test_june_change_before_charging_does_not_affect_may(self):
        self.member.rok_dolaczenia, self.member.miesiac_dolaczenia = 2026, 5
        self.session.commit()
        self.change()
        self.calc.dodaj_naleznosc(2026, 5)
        self.calc.dodaj_naleznosc(2026, 6)
        self.assertEqual([c.kwota_grosze for c in self.session.query(NaliczenieCzlonka).order_by(NaliczenieCzlonka.id)], [3500, 6500])

    def test_status_change_after_approved_rates_is_not_charged_twice(self):
        self.calc.dodaj_naleznosc(2026, 6)
        approve_fees(self.session, 2026, self.rates(), date(2026, 10, 1))
        self.assertEqual(self.change(), 4000)
        self.assertEqual(self.member.bilans_otwarcia, 25)
        self.assertTrue(approve_fees(self.session, 2026, self.rates(), date(2026, 10, 1)).unchanged)
        self.assertEqual(self.member.bilans_otwarcia, 25)

    def test_write_error_rolls_back_change_and_balance(self):
        self.calc.dodaj_naleznosc(2026, 6)
        with self.engine.begin() as connection:
            connection.execute(text("CREATE TRIGGER fail_status BEFORE INSERT ON korekty_statusow BEGIN SELECT RAISE(ABORT, 'test'); END"))
        with self.assertRaises(Exception):
            self.change()
        self.session.expire_all()
        self.assertEqual(self.member.status.nazwa, 'Standard')
        self.assertEqual(self.member.bilans_otwarcia, 70)
        self.assertEqual(self.session.query(ZmianaStatusu).count(), 0)

    def test_invalid_date_and_repeated_status_create_no_change(self):
        old_id = self.member.status_id
        new_id = self.premium()
        for effective in (date(2026, 5, 1), date(2027, 1, 1)):
            with Session(self.engine) as operation, self.assertRaises(ValueError):
                change_status(operation, operation.get(Czlonek, self.member.id), new_id, effective)
        self.assertEqual(self.change(), 0)
        self.assertEqual(self.change(), 0)
        self.assertEqual(self.session.query(ZmianaStatusu).count(), 1)

    def test_bulk_history_uses_membership_and_explicit_old_status_then_dated_new_status(self):
        self.member.bilans_otwarcia = -35
        self.session.add_all(HistoriaNaliczen(rok=2026, miesiac=m) for m in (6,7,8,9))
        self.session.commit()
        old_id = self.member.status_id
        self.change()
        history = bulk_history(self.session, 2026, {old_id: '35', self.premium(): '65'}, {self.member.id: old_id})
        self.assertEqual(len(history), 4)
        self.assertTrue(all(row[3:] == (old_id, '35') for row in history))
        approve_fees(self.session, 2026, self.rates(), date(2026, 10, 1), history=history)
        self.assertEqual(self.member.bilans_otwarcia, -215)

    def test_bulk_history_excludes_months_outside_membership(self):
        self.member.miesiac_dolaczenia = 8
        self.session.add_all(HistoriaNaliczen(rok=2026, miesiac=m) for m in (6,7,8,9))
        self.session.commit()
        history = bulk_history(self.session, 2026, {self.status.id: '35'}, {self.member.id: self.status.id})
        self.assertEqual([row[3] for row in history], [0, 0, self.status.id, self.status.id])
        with self.assertRaises(ValueError):
            bulk_history(self.session, 2026, {self.status.id: '35'}, {})

    def test_membership_change_after_bulk_preview_requires_new_confirmation(self):
        self.session.add(HistoriaNaliczen(rok=2026, miesiac=6))
        self.session.commit()
        history = bulk_history(self.session, 2026, {self.status.id: '35'}, {self.member.id: self.status.id})
        plan = preview_fees(self.session, 2026, self.rates(), date(2026, 10, 1), history=history)
        self.member.miesiac_dolaczenia = 7
        self.session.commit()
        with self.assertRaisesRegex(ValueError, 'od podglądu'):
            approve_fees(self.session, 2026, self.rates(), date(2026, 10, 1), history=history, expected_plan=plan)
        self.assertEqual(self.session.query(NaliczenieCzlonka).count(), 0)

    def test_migration_4_backup_is_additive(self):
        path = Path(self.tmp.name) / 'v3.db'
        old = create_engine('sqlite:///' + path.as_posix())
        Base.metadata.create_all(old, tables=[t for t in Base.metadata.sorted_tables
            if t.name not in {'zmiany_statusow', 'korekty_statusow'}])
        old.dispose()
        for _ in range(2):
            engine = init_db(path)
            with Session(engine) as operation:
                self.assertEqual(operation.query(ZmianaStatusu).count(), 0)
            engine.dispose()
        self.assertEqual(len(list(Path(self.tmp.name).glob('v3.przed-migracja-4-*.db'))), 1)
