import unittest
from datetime import date
from decimal import Decimal
from sqlalchemy import text
import test_finance as fixtures
from annual_fees import approve_fees, cadence_year
from finance_service import add_member
from models import Czlonek, NaliczenieCzlonka, Status, StatusNaliczenia
from opening_balance import opening_balances


class LateMemberTests(unittest.TestCase):
    setUp = fixtures.FinanceTests.setUp
    tearDown = fixtures.FinanceTests.tearDown

    def add(self, month=6, balance='0'):
        public_id, amount = add_member(self.session, 'Nowy Standard', '', self.status.id,
            balance, joined=date(2026, month, 1), entry_fee=True)
        member = self.session.query(Czlonek).filter_by(numer_identyfikacyjny=public_id).one()
        return member, amount

    def test_entry_fee_and_june_through_october_reversal_and_recharge(self):
        for month in range(6, 11):
            self.assertTrue(self.calc.dodaj_naleznosc(2026, month)[0])
        member, amount = self.add()
        self.assertEqual(amount, Decimal('-280'))
        self.assertEqual(member.bilans_otwarcia, -280)
        self.assertEqual(self.session.query(NaliczenieCzlonka).filter_by(czlonek_id=member.id).count(), 5)
        self.assertEqual(self.session.query(StatusNaliczenia).count(), 10)
        today = date.today()
        self.assertEqual(opening_balances(self.session, cadence_year(today.year, today.month))[member.id], 0)
        self.assertFalse(self.calc.dodaj_naleznosc(2026, 10)[0])
        self.assertTrue(self.calc.zdejmij_naleznosc(2026, 6)[0])
        self.assertEqual(member.bilans_otwarcia, -245)
        self.assertTrue(self.calc.dodaj_naleznosc(2026, 6)[0])
        self.assertEqual(member.bilans_otwarcia, -280)

    def test_join_month_reversed_month_and_unbilled_month(self):
        for month in range(6, 10):
            self.calc.dodaj_naleznosc(2026, month)
        self.calc.zdejmij_naleznosc(2026, 8)
        member, amount = self.add(month=8, balance='10')
        self.assertEqual(amount, -130)  # 10 - 105 - wrzesień 35
        self.assertEqual(self.session.query(NaliczenieCzlonka).filter_by(czlonek_id=member.id).count(), 1)
        self.calc.dodaj_naleznosc(2026, 10)
        self.assertEqual(member.bilans_otwarcia, -165)

    def test_approved_rates_and_later_correction(self):
        self.calc.dodaj_naleznosc(2026, 6)
        rates = {s.id: '40' if s.nazwa == 'Standard' else '70' for s in self.session.query(Status)}
        approve_fees(self.session, 2026, rates, date(2026, 10, 1))
        member, amount = self.add()
        self.assertEqual(amount, -145)  # wpisowe bazowe 105 + zatwierdzone 40
        self.assertTrue(approve_fees(self.session, 2026, rates, date(2026, 10, 1)).unchanged)
        rates[self.status.id] = '45'
        approve_fees(self.session, 2026, rates, date(2026, 10, 1))
        self.assertEqual(member.bilans_otwarcia, -150)

    def test_failure_rolls_back_member_opening_and_charges(self):
        self.calc.dodaj_naleznosc(2026, 6)
        with self.engine.begin() as connection:
            connection.execute(text("CREATE TRIGGER fail_late BEFORE INSERT ON statusy_naliczen BEGIN SELECT RAISE(ABORT,'test'); END"))
        with self.assertRaises(Exception):
            self.add()
        self.assertEqual(self.session.query(Czlonek).count(), 1)
        self.assertEqual(self.session.query(NaliczenieCzlonka).count(), 1)
        self.assertEqual(opening_balances(self.session, 2026), {})
