"""Odczyt zapisanych zdarzeń finansowych i pochodzenia wpłat, bez rekonstrukcji sald."""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
import json

from sqlalchemy.orm import Session
from models import (Czlonek, Wplata, PozycjaWyciagu, ImportWyciagu, NaliczenieMiesiaca,
    NaliczenieCzlonka, KorektaStawki, KorektaStatusu, ZatwierdzenieStawek,
    ZmianaStatusu, SaldoPoczatkoweKadencji, Wpisowe, HistoriaNaliczen, UzgodnienieMiesiaca)
from finance_service import signed_amount


@dataclass(frozen=True)
class LedgerRow:
    key: str
    date: date
    period: date
    kind: str
    cents: int | None
    description: str
    details: str
    state: str = 'Zapisano'
    affects_balance: bool = True


def payment_sources(operation, payment_ids):
    if not payment_ids:
        return {}
    result = {}
    for row, batch in operation.query(PozycjaWyciagu, ImportWyciagu).join(
            ImportWyciagu, PozycjaWyciagu.import_id == ImportWyciagu.id).filter(
            PozycjaWyciagu.wplata_id.in_(payment_ids)):
        data = json.loads(row.dane_json)
        result[row.wplata_id] = (f"Nazwa nadawcy: {data.get('sender') or 'brak danych w wyciągu'}\n"
            f"ID bankowe: {row.id_bankowe or 'brak'}\n"
            f"Import #{batch.id}, wiersz {row.numer_wiersza}\n"
            f"Odcisk pliku: {batch.sha256}\nZapis importu: {batch.zapisano:%Y-%m-%d %H:%M:%S}")
    return result


def payment_details(payment, source=''):
    return (f"Wpłata #{payment.id}\nData przelewu: {payment.data_przelewu:%Y-%m-%d %H:%M:%S}\n"
        f"Kwota: {signed_amount(payment.kwota):.2f} PLN\n"
        f"Opis transakcji: {payment.tytul_oryginalny or 'brak zapisanego opisu'}\n"
        f"Metoda: {payment.metoda_dopasowania or 'brak danych'}\n"
        + (source or 'Brak powiązania z wyciągiem (wpłata ręczna lub starszy zapis).'))


def member_ledger(session, member_id):
    rows = []
    with Session(bind=session.get_bind()) as operation:
        member = operation.get(Czlonek, member_id)
        if member is None:
            raise ValueError('Nie znaleziono klienta.')
        balance = int(signed_amount(member.bilans_otwarcia or 0) * 100)
        payments = operation.query(Wplata).filter_by(czlonek_id=member_id).all()
        sources = payment_sources(operation, [p.id for p in payments])
        for p in payments:
            rows.append(LedgerRow(f'payment:{p.id}', p.data_przelewu.date(), p.data_przelewu.date(),
                'Wpłata', int(signed_amount(p.kwota) * 100),
                p.tytul_oryginalny or 'Brak zapisanego opisu', payment_details(p, sources.get(p.id, ''))))
        charges = operation.query(NaliczenieCzlonka, NaliczenieMiesiaca).join(
            NaliczenieMiesiaca, NaliczenieCzlonka.naliczenie_id == NaliczenieMiesiaca.id).filter(
            NaliczenieCzlonka.czlonek_id == member_id).all()
        ids = [c.id for c, _ in charges]
        rate_changes, status_changes = {}, {}
        if ids:
            for correction, approval in operation.query(KorektaStawki, ZatwierdzenieStawek).join(
                    ZatwierdzenieStawek, KorektaStawki.zatwierdzenie_id == ZatwierdzenieStawek.id).filter(
                    KorektaStawki.naliczenie_czlonka_id.in_(ids)):
                rate_changes.setdefault(correction.naliczenie_czlonka_id, []).append((correction, approval))
            for correction, change in operation.query(KorektaStatusu, ZmianaStatusu).join(
                    ZmianaStatusu, KorektaStatusu.zmiana_statusu_id == ZmianaStatusu.id).filter(
                    KorektaStatusu.naliczenie_czlonka_id.in_(ids)):
                status_changes.setdefault(correction.naliczenie_czlonka_id, []).append((correction, change))
        for charge, batch in charges:
            period = date(batch.rok, batch.miesiac, 1)
            state = 'Cofnięte' if batch.cofnieto else 'Aktywne'
            reference = f'Naliczenie #{charge.id}, partia #{batch.id}, miesiąc {period:%Y-%m}'
            rows.append(LedgerRow(f'charge:{charge.id}', period, period, 'Składka miesięczna',
                -charge.kwota_grosze, f'Składka za {period:%m.%Y}',
                f'{reference}\nKwota pierwotna: {Decimal(charge.kwota_grosze) / 100:.2f} PLN\n'
                f'Utworzenie partii: {batch.utworzono:%Y-%m-%d %H:%M:%S}', state))
            total = charge.kwota_grosze
            for correction, approval in rate_changes.get(charge.id, []):
                total += correction.roznica_grosze
                rows.append(LedgerRow(f'rate:{correction.id}', approval.data_decyzji, period,
                    'Korekta stawki', -correction.roznica_grosze, f'Wyrównanie za {period:%m.%Y}',
                    f'{reference}\nDecyzja #{approval.id}, rewizja {approval.rewizja}\n'
                    f'Data decyzji: {approval.data_decyzji}\nZapis: {approval.zapisano:%Y-%m-%d %H:%M:%S}', state))
            for correction, change in status_changes.get(charge.id, []):
                total += correction.roznica_grosze
                rows.append(LedgerRow(f'status:{correction.id}', change.zapisano.date(), period,
                    'Korekta statusu', -correction.roznica_grosze, f'Zmiana statusu za {period:%m.%Y}',
                    f'{reference}\nZmiana statusu #{change.id}, obowiązuje od {change.obowiazuje_od}\n'
                    f'Zapis: {change.zapisano:%Y-%m-%d %H:%M:%S}', state))
            if batch.cofnieto:
                rows.append(LedgerRow(f'reversal:{charge.id}', batch.cofnieto.date(), period,
                    'Cofnięcie miesiąca', total, f'Cofnięto składkę i korekty za {period:%m.%Y}',
                    f'{reference}\nCofnięto: {batch.cofnieto:%Y-%m-%d %H:%M:%S}'))
        for fee in operation.query(Wpisowe).filter_by(czlonek_id=member_id):
            rows.append(LedgerRow(f'entry:{fee.id}', fee.obowiazuje_od, fee.obowiazuje_od,
                'Wpisowe', -fee.kwota_grosze, f'3 × {Decimal(fee.stawka_grosze) / 100:.2f} PLN — bazowa stawka Standard',
                f'Wpisowe #{fee.id}\nZapis: {fee.zapisano:%Y-%m-%d %H:%M:%S}'))
        openings = operation.query(SaldoPoczatkoweKadencji).filter_by(czlonek_id=member_id).order_by(
            SaldoPoczatkoweKadencji.id).all()
        latest = {o.rok_kadencji: o.id for o in openings}
        for opening in openings:
            period = date(opening.rok_kadencji, 6, 1)
            rows.append(LedgerRow(f'opening:{opening.id}', period, period, 'Saldo początkowe',
                opening.kwota_grosze, opening.zrodlo,
                f'Saldo przeniesione na {period:%d.%m.%Y}: {Decimal(opening.kwota_grosze) / 100:.2f} PLN\n'
                f'Zapis rewizji: {opening.utworzono:%Y-%m-%d %H:%M:%S}\n'
                'Informacja o kwocie już uwzględnionej w saldzie; nie jest ponownym obciążeniem.',
                'Aktualna informacja' if latest[opening.rok_kadencji] == opening.id else 'Poprzednia rewizja', False))
        for legacy in operation.query(HistoriaNaliczen):
            if operation.get(UzgodnienieMiesiaca, legacy.id):
                continue
            period = date(legacy.rok, legacy.miesiac, 1)
            joined = (member.rok_dolaczenia or 1, member.miesiac_dolaczenia or 1)
            left = (member.rok_odejscia or 9999, member.miesiac_odejscia or 12)
            if joined <= (period.year, period.month) <= left:
                rows.append(LedgerRow(f'legacy:{legacy.id}', period, period, 'Dawne naliczenie', None,
                    'Brak indywidualnej kwoty', 'Dawna historia nie zawiera kwoty tej osoby ani statusu. '
                    'Wymaga uzgodnienia w oknie stawek.', 'Do uzgodnienia', False))
        return dict(name=member.imie_nazwisko, public_id=member.numer_identyfikacyjny,
            archived=not member.aktywny, balance=balance,
            rows=tuple(sorted(rows, key=lambda r: (r.date, r.key), reverse=True)),
            warning='Saldo bieżące pochodzi z kartoteki. Historia może być niepełna: dawnych wpisowych '
                'i innych niezapisanych operacji nie odtwarzamy. Salda początkowe i ich rewizje są informacją, '
                'nie kolejnymi wpłatami ani obciążeniami.')
