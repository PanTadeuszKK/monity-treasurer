"""Rozliczenie należności metodą „najstarsze najpierw” — wyłącznie widok, bez zapisu.

Przy tej zasadzie każda wpłata pokrywa najpierw najstarszą otwartą należność,
więc ewentualna zaległość dotyczy zawsze najnowszych należności. Wystarczy
rozłożyć bieżącą zaległość z kartoteki wstecz od najnowszej należności.
Nie odtwarzamy niepełnej dawnej historii i zawsze zgadzamy się z saldem.
"""
from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from finance_service import signed_amount
from models import (Czlonek, NaliczenieCzlonka, NaliczenieMiesiaca, KorektaStawki,
                    KorektaStatusu, Wpisowe)


@dataclass(frozen=True)
class DueItem:
    period: date
    label: str
    due_cents: int
    unpaid_cents: int

    @property
    def state(self):
        if self.unpaid_cents <= 0:
            return 'opłacone'
        return 'nieopłacone' if self.unpaid_cents >= self.due_cents else 'częściowo'


@dataclass(frozen=True)
class Settlement:
    items: tuple
    older_debt_cents: int   # zaległość sprzed zapisanych należności (saldo przeniesione, dawna historia)
    credit_cents: int       # nadpłata

    @property
    def unpaid(self):
        return tuple(item for item in self.items if item.unpaid_cents > 0)


def settle_oldest_first(balance_cents, dues):
    """dues: [(okres, opis, kwota_grosze)], saldo: minus = zaległość."""
    ordered = sorted(dues, key=lambda d: (d[0], d[1]))
    debt = max(0, -balance_cents)
    unpaid = [0] * len(ordered)
    for index in range(len(ordered) - 1, -1, -1):
        if debt <= 0:
            break
        part = min(debt, max(0, ordered[index][2]))
        unpaid[index] = part
        debt -= part
    items = tuple(DueItem(p, label, amount, unpaid[i]) for i, (p, label, amount) in enumerate(ordered))
    return Settlement(items, debt, max(0, balance_cents))


def member_dues(operation, member_id):
    dues = []
    charges = operation.query(NaliczenieCzlonka, NaliczenieMiesiaca).join(
        NaliczenieMiesiaca, NaliczenieCzlonka.naliczenie_id == NaliczenieMiesiaca.id).filter(
        NaliczenieCzlonka.czlonek_id == member_id, NaliczenieMiesiaca.cofnieto.is_(None)).all()
    ids = [charge.id for charge, _ in charges]
    extra = {}
    if ids:
        for model in (KorektaStawki, KorektaStatusu):
            for correction in operation.query(model).filter(model.naliczenie_czlonka_id.in_(ids)):
                extra[correction.naliczenie_czlonka_id] = extra.get(correction.naliczenie_czlonka_id, 0) + correction.roznica_grosze
    for charge, batch in charges:
        period = date(batch.rok, batch.miesiac, 1)
        dues.append((period, f'Składka {period:%m.%Y}', charge.kwota_grosze + extra.get(charge.id, 0)))
    for fee in operation.query(Wpisowe).filter_by(czlonek_id=member_id):
        dues.append((fee.obowiazuje_od, 'Wpisowe', fee.kwota_grosze))
    return dues


def member_settlement(session, member_id):
    with Session(bind=session.get_bind()) as operation:
        member = operation.get(Czlonek, member_id)
        if member is None:
            raise ValueError('Nie znaleziono klienta.')
        balance = int(signed_amount(member.bilans_otwarcia or 0) * 100)
        return settle_oldest_first(balance, member_dues(operation, member_id))


def describe(settlement):
    """Krótki opis do karty finansowej."""
    def pln(cents):
        return f'{cents / 100:,.2f} zł'.replace(',', ' ').replace('.', ',')
    if settlement.credit_cents:
        return f'Wszystkie zapisane należności opłacone · nadpłata {pln(settlement.credit_cents)}'
    unpaid = settlement.unpaid
    if not unpaid and not settlement.older_debt_cents:
        return 'Wszystkie zapisane należności opłacone'
    parts = [f'{item.label}' + (f' (brakuje {pln(item.unpaid_cents)})' if item.state == 'częściowo' else '')
             for item in unpaid]
    if settlement.older_debt_cents:
        parts.insert(0, f'zaległość sprzed zapisanej historii {pln(settlement.older_debt_cents)}')
    return 'Nieopłacone (najstarsze najpierw): ' + ', '.join(parts)
