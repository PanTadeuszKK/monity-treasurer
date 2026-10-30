import unittest
from datetime import date

import test_finance as fixtures
from allocation import settle_oldest_first, member_settlement, describe


class SettleOldestFirstTests(unittest.TestCase):
    dues = [(date(2026, 6, 1), 'Składka 06.2026', 3500), (date(2026, 7, 1), 'Składka 07.2026', 3500),
            (date(2026, 8, 1), 'Składka 08.2026', 3500)]

    def test_debt_sits_in_newest_dues(self):
        result = settle_oldest_first(-5000, self.dues)
        self.assertEqual([i.unpaid_cents for i in result.items], [0, 1500, 3500])
        self.assertEqual([i.state for i in result.items], ['opłacone', 'częściowo', 'nieopłacone'])
        self.assertEqual(result.older_debt_cents, 0)
        self.assertEqual(sum(i.unpaid_cents for i in result.items), 5000)

    def test_debt_larger_than_recorded_dues_is_older_debt(self):
        result = settle_oldest_first(-12000, self.dues)
        self.assertTrue(all(i.state == 'nieopłacone' for i in result.items))
        self.assertEqual(result.older_debt_cents, 1500)
        self.assertIn('sprzed zapisanej historii 15,00 zł', describe(result))

    def test_credit_and_zero_balance(self):
        self.assertEqual(settle_oldest_first(2000, self.dues).credit_cents, 2000)
        self.assertFalse(settle_oldest_first(2000, self.dues).unpaid)
        self.assertEqual(describe(settle_oldest_first(0, self.dues)), 'Wszystkie zapisane należności opłacone')

    def test_input_order_does_not_matter(self):
        result = settle_oldest_first(-3500, list(reversed(self.dues)))
        self.assertEqual(result.unpaid[0].label, 'Składka 08.2026')


class MemberSettlementTests(unittest.TestCase):
    setUp = fixtures.FinanceTests.setUp
    tearDown = fixtures.FinanceTests.tearDown

    def test_uses_recorded_charges_and_ignores_reversed_month(self):
        # Saldo 105 zł, trzy składki po 35 zł -> 0; czwarta -> zaległość jednego miesiąca.
        for month in (6, 7, 8, 9):
            self.assertTrue(self.calc.dodaj_naleznosc(2026, month)[0])
        result = member_settlement(self.session, self.member.id)
        self.assertEqual([i.label for i in result.unpaid], ['Składka 09.2026'])
        self.assertTrue(self.calc.zdejmij_naleznosc(2026, 9)[0])
        result = member_settlement(self.session, self.member.id)
        self.assertEqual(len(result.items), 3)
        self.assertFalse(result.unpaid)


if __name__ == '__main__':
    unittest.main()
