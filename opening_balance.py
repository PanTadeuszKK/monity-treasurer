"""Jawnie zapisane saldo początkowe; nie rekonstruujemy go z bieżącego salda."""
from datetime import date
from decimal import Decimal
from annual_fees import cadence_year
from models import SaldoPoczatkoweKadencji, Czlonek
from finance_service import signed_amount


def opening_balances(session, year):
    result = {}
    for row in session.query(SaldoPoczatkoweKadencji).filter_by(rok_kadencji=year).order_by(SaldoPoczatkoweKadencji.id):
        result[row.czlonek_id] = row.kwota_grosze
    return result


def record_opening(session, member_id, year, amount, source):
    today = date.today()
    if not isinstance(year,int) or not 1900 <= year <= cadence_year(today.year,today.month):
        raise ValueError('Podaj rozpoczętą kadencję.')
    if not session.get(Czlonek,member_id):
        raise ValueError('Nie znaleziono klienta.')
    cents = int(signed_amount(amount)*100)
    previous = opening_balances(session,year).get(member_id)
    if previous != cents:
        session.add(SaldoPoczatkoweKadencji(czlonek_id=member_id,rok_kadencji=year,
                    kwota_grosze=cents,zrodlo=source))
    return cents


def opening_description(cents, year):
    if cents is None:
        return f'Saldo przeniesione na 01.06.{year}: nieuzupełnione.'
    amount = Decimal(abs(cents))/100
    if cents < 0:
        return f'Zaległość przeniesiona na 01.06.{year}: {amount:.2f} PLN.'
    if cents > 0:
        return f'Nadpłata przeniesiona na 01.06.{year}: {amount:.2f} PLN.'
    return f'Saldo przeniesione na 01.06.{year}: 0.00 PLN (bez zaległości i nadpłaty).'
