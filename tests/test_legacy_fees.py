import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

import test_finance as fixtures
from annual_fees import approve_fees, preview_fees, history_requirements
from models import (Base, Czlonek, HistoriaNaliczen, NaliczenieCzlonka, StatusNaliczenia,
                    KorektaStawki, UzgodnienieMiesiaca, UzgodnienieHistorii,
                    ZatwierdzenieStawek, init_db)


class LegacyFeesTests(unittest.TestCase):
    setUp = fixtures.FinanceTests.setUp
    tearDown = fixtures.FinanceTests.tearDown

    def values(self, amount='40'):
        from models import Status
        return {s.id: amount if s.nazwa == 'Standard' else '70' for s in self.session.query(Status)}

    def legacy(self, months=(6, 7, 8, 9)):
        self.member.bilans_otwarcia = 105 - 35 * len(months)
        self.session.add_all(HistoriaNaliczen(rok=2026, miesiac=m) for m in months)
        self.session.commit()
        return [(kind, source, member, self.status.id, '35')
                for kind, source, member, *_ in history_requirements(self.session, 2026)]

    def approve(self, history=None, values=None, plan=None):
        return approve_fees(self.session, 2026, values or self.values(), date(2026, 10, 1),
                            expected_plan=plan, history=history)

    def test_preview_does_not_save_history_or_change_balance(self):
        history = self.legacy()
        plan = preview_fees(self.session, 2026, self.values(), date(2026, 10, 1), history=history)
        self.assertEqual(plan.total_cents, 2000)
        self.assertEqual(self.member.bilans_otwarcia, -35)
        self.assertEqual(self.session.query(NaliczenieCzlonka).count(), 0)
        self.assertEqual(self.session.query(UzgodnienieMiesiaca).count(), 0)
        self.assertEqual(self.session.query(ZatwierdzenieStawek).count(), 0)
        self.approve(history, plan=plan)
        self.assertEqual(self.member.bilans_otwarcia, -55)
        self.assertEqual(self.session.query(HistoriaNaliczen).count(), 4)
        self.assertEqual(self.session.query(UzgodnienieHistorii).count(), 1)
        self.assertEqual(self.session.query(KorektaStawki).count(), 4)
        self.assertTrue(self.approve().unchanged)
        self.assertEqual(self.member.bilans_otwarcia, -55)
        self.assertEqual(history_requirements(self.session, 2026), ())

    def test_same_rate_only_reconciles_without_debiting_again(self):
        self.approve(self.legacy(), self.values('35'))
        self.assertEqual(self.member.bilans_otwarcia, -35)
        self.assertEqual(self.session.query(KorektaStawki).count(), 0)

    def test_reconciled_reversal_and_recharge_and_next_revision(self):
        self.approve(self.legacy((6,)))
        self.assertEqual(self.member.bilans_otwarcia, 65)
        self.assertTrue(self.calc.zdejmij_naleznosc(2026, 6)[0])
        self.assertEqual(self.member.bilans_otwarcia, 105)
        self.assertTrue(self.calc.dodaj_naleznosc(2026, 6)[0])
        self.assertEqual(self.member.bilans_otwarcia, 65)
        self.approve(values=self.values('45'))
        self.assertEqual(self.member.bilans_otwarcia, 60)

    def test_missing_status_requires_confirmation_preserves_original_amount(self):
        self.calc.dodaj_naleznosc(2026, 6)
        charge = self.session.query(NaliczenieCzlonka).one()
        self.session.delete(self.session.query(StatusNaliczenia).one())
        self.session.commit()
        history = [('snapshot', charge.id, self.member.id, self.status.id, '35')]
        with self.assertRaisesRegex(ValueError, 'pierwotna kwota'):
            self.approve([('snapshot', charge.id, self.member.id, self.status.id, '36')])
        self.approve(history)
        self.assertEqual(charge.kwota_grosze, 3500)
        self.assertEqual(self.member.bilans_otwarcia, 65)

    def test_incomplete_or_invalid_history_is_atomic(self):
        history = self.legacy()
        for invalid in [history[:-1], history + [history[0]],
                        [(k, s, m, None, a) for k, s, m, _, a in history]]:
            with self.assertRaises(ValueError):
                self.approve(invalid)
            self.assertEqual(self.session.query(NaliczenieCzlonka).count(), 0)
            self.assertEqual(self.member.bilans_otwarcia, -35)

    def test_explicit_exclusion_and_historical_status_ignore_current_dates(self):
        history = self.legacy((6,))
        other = Czlonek(numer_identyfikacyjny=13, imie_nazwisko='Nieobciążona Osoba',
                        status=self.status, bilans_otwarcia=0, rok_dolaczenia=2026, miesiac_dolaczenia=9)
        self.session.add(other)
        self.member.rok_dolaczenia = 2027
        self.session.commit()
        history.append(('legacy', history[0][1], other.id, 0, ''))
        self.approve(history)
        self.assertEqual(self.member.bilans_otwarcia, 65)
        self.assertEqual(other.bilans_otwarcia, 0)
        self.assertEqual(self.session.query(NaliczenieCzlonka).count(), 1)

    def test_failure_rolls_back_history_and_all_financial_changes(self):
        history = self.legacy()
        with self.engine.begin() as connection:
            connection.execute(text("CREATE TRIGGER fail_correction BEFORE INSERT ON korekty_stawek BEGIN SELECT RAISE(ABORT, 'test'); END"))
        with self.assertRaises(Exception):
            self.approve(history)
        self.assertEqual(self.session.query(UzgodnienieMiesiaca).count(), 0)
        self.assertEqual(self.session.query(NaliczenieCzlonka).count(), 0)
        self.assertEqual(self.member.bilans_otwarcia, -35)

    def test_changed_history_confirmation_requires_new_preview(self):
        history = self.legacy((6,))
        plan = preview_fees(self.session, 2026, self.values(), date(2026, 10, 1), history=history)
        changed = [(k, s, m, status, '30') for k, s, m, status, _ in history]
        with self.assertRaisesRegex(ValueError, 'od podglądu'):
            self.approve(changed, plan=plan)
        self.assertEqual(self.session.query(NaliczenieCzlonka).count(), 0)

    def test_next_cadence_uses_previous_approved_rate_without_reconciliation(self):
        approve_fees(self.session, 2025, self.values('40'), date(2025, 10, 1))
        self.assertTrue(self.calc.dodaj_naleznosc(2026, 6)[0])
        self.assertEqual(self.session.query(NaliczenieCzlonka).one().kwota_grosze, 4000)
        self.assertEqual(history_requirements(self.session, 2026), ())
        self.approve(values=self.values('45'))
        self.assertEqual(self.member.bilans_otwarcia, 60)
        self.assertEqual(self.session.query(KorektaStawki).one().roznica_grosze, 500)

    def test_migration_3_backup_preserves_data_and_only_runs_once(self):
        path = Path(self.tmp.name) / 'v2.db'
        old = create_engine('sqlite:///' + path.as_posix())
        Base.metadata.create_all(old, tables=[t for t in Base.metadata.sorted_tables
            if t.name not in {'uzgodnienia_miesiecy', 'uzgodnienia_historii'}])
        with Session(old) as operation:
            operation.add(HistoriaNaliczen(rok=2026, miesiac=6))
            operation.commit()
        old.dispose()
        for _ in range(2):
            engine = init_db(path)
            with Session(engine) as operation:
                self.assertEqual(operation.query(HistoriaNaliczen).count(), 1)
                self.assertEqual(operation.query(UzgodnienieMiesiaca).count(), 0)
            engine.dispose()
        self.assertEqual(len(list(Path(self.tmp.name).glob('v2.przed-migracja-3-*.db'))), 1)
