import unittest
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

import test_finance as fixtures
from annual_fees import approve_fees, preview_fees, rate_cents
from models import (Base, Czlonek, Status, Wplata, HistoriaNaliczen, StatusNaliczenia,
                    ZatwierdzenieStawek, StawkaKadencji, KorektaStawki,
                    NaliczenieCzlonka, NaliczenieMiesiaca, init_db)


class AnnualFeesTests(unittest.TestCase):
    setUp = fixtures.FinanceTests.setUp
    tearDown = fixtures.FinanceTests.tearDown

    def values(self, standard='40', premium='70'):
        with Session(self.engine) as operation:
            return {s.id: standard if s.nazwa == 'Standard' else premium for s in operation.query(Status)}

    def approve(self, values=None, year=2026):
        return approve_fees(self.session, year, values or self.values(), date(year, 10, 1))

    def test_october_increase_corrects_june_through_september(self):
        for month in (6, 7, 8, 9):
            self.assertTrue(self.calc.dodaj_naleznosc(2026, month)[0])
        original = [(c.id, c.kwota_grosze) for c in self.session.query(NaliczenieCzlonka)]
        plan = self.approve()
        self.assertEqual(plan.correction_count, 4)
        self.assertEqual(plan.total_cents, 2000)
        self.assertEqual(self.member.bilans_otwarcia, -55)
        self.assertEqual([(c.id, c.kwota_grosze) for c in self.session.query(NaliczenieCzlonka)], original)
        self.assertEqual(self.session.query(KorektaStawki).count(), 4)
        self.assertTrue(self.calc.dodaj_naleznosc(2026, 10)[0])
        self.assertEqual(self.member.bilans_otwarcia, -95)

    def test_repeated_approval_does_not_duplicate_adjustments(self):
        self.calc.dodaj_naleznosc(2026, 6)
        self.approve()
        self.assertTrue(self.approve().unchanged)
        self.assertEqual(self.member.bilans_otwarcia, 65)
        self.assertEqual(self.session.query(ZatwierdzenieStawek).count(), 1)
        self.assertEqual(self.session.query(KorektaStawki).count(), 1)

    def test_second_decision_uses_only_additional_difference_and_reduction(self):
        self.calc.dodaj_naleznosc(2026, 6)
        self.approve()
        self.approve(self.values('45'))
        self.assertEqual(self.member.bilans_otwarcia, 60)
        self.approve(self.values('30'))
        self.assertEqual(self.member.bilans_otwarcia, 75)
        self.assertEqual([c.roznica_grosze for c in self.session.query(KorektaStawki).order_by(KorektaStawki.id)], [500, 500, -1500])

    def test_reversal_restores_original_and_all_adjustments(self):
        self.calc.dodaj_naleznosc(2026, 6)
        self.approve()
        self.approve(self.values('45'))
        self.assertTrue(self.calc.zdejmij_naleznosc(2026, 6)[0])
        self.assertEqual(self.member.bilans_otwarcia, 105)
        self.assertEqual(self.session.query(KorektaStawki).count(), 2)
        self.assertTrue(self.calc.dodaj_naleznosc(2026, 6)[0])
        self.assertEqual(self.member.bilans_otwarcia, 60)
        self.approve(self.values('50'))
        self.assertEqual(self.member.bilans_otwarcia, 55)

    def test_historical_status_survives_status_change(self):
        self.calc.dodaj_naleznosc(2026, 6)
        self.member.status = self.session.query(Status).filter_by(nazwa='Premium').one()
        self.session.commit()
        self.calc.dodaj_naleznosc(2026, 7)
        plan = self.approve(self.values('40', '80'))
        self.assertEqual(plan.total_cents, 2000)
        self.assertEqual(self.member.bilans_otwarcia, -15)

    def test_departed_and_late_joining_members(self):
        self.member.aktywny = False
        self.member.rok_odejscia, self.member.miesiac_odejscia = 2026, 9
        self.session.add(Czlonek(numer_identyfikacyjny=13, imie_nazwisko='Nowa Osoba',
            status=self.status, bilans_otwarcia=0, aktywny=True,
            rok_dolaczenia=2026, miesiac_dolaczenia=8))
        self.session.commit()
        for month in (6, 7, 8, 9, 10):
            self.calc.dodaj_naleznosc(2026, month)
        self.assertEqual(self.approve().correction_count, 7)
        self.assertEqual(self.member.bilans_otwarcia, -55)
        self.assertEqual(self.session.query(Czlonek).filter_by(numer_identyfikacyjny=13).one().bilans_otwarcia, -120)

    def test_cadence_boundaries_and_previous_rate_provisional(self):
        self.calc.dodaj_naleznosc(2026, 5)
        self.calc.dodaj_naleznosc(2026, 6)
        self.calc.dodaj_naleznosc(2027, 5)
        self.assertEqual(self.approve().correction_count, 2)
        self.calc.dodaj_naleznosc(2027, 6)
        latest = self.session.query(NaliczenieCzlonka).order_by(NaliczenieCzlonka.id.desc()).first()
        self.assertEqual(latest.kwota_grosze, 4000)
        with Session(self.engine) as operation:
            status = operation.get(Status, self.status.id)
            self.assertEqual(rate_cents(operation, status, 2026, 5), 3500)
            self.assertEqual(rate_cents(operation, status, 2027, 1), 4000)

    def test_payments_dates_and_surplus_untouched(self):
        payment = Wplata(czlonek_id=self.member.id, kwota=100,
            data_przelewu=__import__('datetime').datetime(2026, 8, 12), tytul_oryginalny='Test')
        self.session.add(payment)
        self.member.bilans_otwarcia += 100
        self.session.commit()
        self.calc.dodaj_naleznosc(2026, 6)
        self.approve()
        self.assertEqual(self.member.bilans_otwarcia, 165)
        self.assertEqual(payment.kwota, 100)
        self.assertEqual(payment.data_przelewu.date(), date(2026, 8, 12))

    def test_unknown_legacy_history_blocks_entire_approval(self):
        self.calc.dodaj_naleznosc(2026, 6)
        self.session.add(HistoriaNaliczen(rok=2026, miesiac=7))
        self.session.commit()
        with self.assertRaisesRegex(ValueError, 'dawne naliczenia'):
            self.approve()
        self.assertEqual(self.session.query(ZatwierdzenieStawek).count(), 0)
        self.assertEqual(self.member.bilans_otwarcia, 70)

    def test_missing_status_snapshot_is_not_inferred(self):
        self.calc.dodaj_naleznosc(2026, 6)
        self.session.delete(self.session.query(StatusNaliczenia).one())
        self.session.commit()
        with self.assertRaisesRegex(ValueError, 'historycznego statusu'):
            self.approve()
        self.assertEqual(self.session.query(KorektaStawki).count(), 0)

    def test_invalid_later_rate_is_atomic(self):
        self.calc.dodaj_naleznosc(2026, 6)
        with self.assertRaises(ValueError):
            self.approve(self.values('40', 'NaN'))
        self.assertEqual(self.member.bilans_otwarcia, 70)
        self.assertEqual(self.session.query(ZatwierdzenieStawek).count(), 0)

    def test_stale_preview_requires_new_confirmation(self):
        values = self.values()
        plan = preview_fees(self.session, 2026, values, date(2026, 10, 1))
        self.calc.dodaj_naleznosc(2026, 6)
        with self.assertRaisesRegex(ValueError, 'od podglądu'):
            approve_fees(self.session, 2026, values, date(2026, 10, 1), expected_plan=plan)
        self.assertEqual(self.session.query(ZatwierdzenieStawek).count(), 0)

    def test_write_failure_rolls_back_approval_rates_and_balances(self):
        self.calc.dodaj_naleznosc(2026, 6)
        with self.engine.begin() as connection:
            connection.execute(text("CREATE TRIGGER fail_correction BEFORE INSERT ON korekty_stawek BEGIN SELECT RAISE(ABORT, 'test'); END"))
        with self.assertRaises(Exception):
            self.approve()
        self.session.expire_all()
        self.assertEqual(self.member.bilans_otwarcia, 70)
        self.assertEqual(self.session.query(ZatwierdzenieStawek).count(), 0)
        self.assertEqual(self.session.query(StawkaKadencji).count(), 0)

    def test_decision_dates_and_all_statuses_required(self):
        for decision in [date(2026, 5, 31), date(2027, 6, 1)]:
            with self.assertRaises(ValueError):
                approve_fees(self.session, 2026, self.values(), decision)
        with self.assertRaises(ValueError):
            self.approve({self.status.id: '40'})

    def test_correction_does_not_commit_other_window_pending_changes(self):
        self.calc.dodaj_naleznosc(2026, 6)
        member_id = self.member.id
        values = self.values()
        self.member.email = 'pending@example.invalid'
        self.approve(values)
        with Session(self.engine) as operation:
            self.assertIsNone(operation.get(Czlonek, member_id).email)
        self.session.rollback()

    def test_migration_2_adds_tables_and_backup_without_reconstructing_history(self):
        from pathlib import Path
        path = Path(self.tmp.name) / 'v1.db'
        engine = create_engine('sqlite:///' + path.as_posix())
        new_names = {'statusy_naliczen', 'zatwierdzenia_stawek', 'stawki_kadencji', 'korekty_stawek'}
        Base.metadata.create_all(engine, tables=[t for t in Base.metadata.sorted_tables if t.name not in new_names])
        with engine.begin() as connection:
            connection.execute(text('INSERT INTO wersja_schematu (wersja, zastosowano) VALUES (1, CURRENT_TIMESTAMP)'))
        engine.dispose()
        engine = init_db(path)
        with Session(engine) as operation:
            self.assertEqual(operation.query(StatusNaliczenia).count(), 0)
            self.assertEqual(operation.execute(text('SELECT MAX(wersja) FROM wersja_schematu')).scalar(), 8)
        engine.dispose()
        self.assertEqual(len(list(Path(self.tmp.name).glob('v1.przed-migracja-2-*.db'))), 1)


if __name__ == '__main__':
    unittest.main()
