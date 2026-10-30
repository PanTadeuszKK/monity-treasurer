"""Walidacja i izolowane, atomowe operacje kartotek oraz wpłat."""
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import json
from sqlalchemy import func, text
from sqlalchemy.orm import Session
from fee_service import parse_amount
from mailer import valid_address
from models import Czlonek, Status, KontoBankowe, Wplata, OperacjaReczna


def signed_amount(value):
    try:
        amount = Decimal(str(value).strip().replace(',', '.'))
        if not amount.is_finite() or abs(amount) > Decimal('999999999.99') or amount != amount.quantize(Decimal('.01')):
            raise ValueError('Kwota musi być skończona i mieć najwyżej dwa miejsca po przecinku.')
        return amount
    except (InvalidOperation, TypeError) as exc:
        raise ValueError('Podaj prawidłową kwotę PLN.') from exc


def bank_account(value):
    value = ''.join(value.split()).upper()
    if not value:
        return ''
    digits = value[2:] if value.startswith('PL') else value
    if len(digits) != 26 or not digits.isascii() or not digits.isdigit() or int(digits[2:]+'2521'+digits[:2]) % 97 != 1:
        raise ValueError('Podaj poprawny polski NRB (26 cyfr) lub IBAN PL.')
    return digits


def add_member(session, name, email, status_id, balance='0', account='', joined=None, entry_fee=False):
    name, email = name.strip(), email.strip()
    if not name or len(name)>200 or any(ord(c)<32 for c in name):
        raise ValueError('Podaj imię i nazwisko (maksymalnie 200 znaków).')
    if email and not valid_address(email):
        raise ValueError('Podaj poprawny adres e-mail albo pozostaw pole puste.')
    amount, account = signed_amount(balance or '0'), bank_account(account)
    joined = joined or date.today().replace(day=1)
    if not isinstance(joined,date) or joined.day != 1 or joined > date.today():
        raise ValueError('Podaj poprawny miesiąc dołączenia, nie późniejszy niż obecny.')
    with Session(bind=session.get_bind()) as operation:
        operation.execute(text('BEGIN IMMEDIATE'))
        if not operation.get(Status,status_id):
            raise ValueError('Wybierz prawidłowy status.')
        if account and operation.get(KontoBankowe,account):
            raise ValueError('Ten rachunek jest już przypisany do kartoteki.')
        opening_amount = amount
        if entry_fee:
            standard = operation.query(Status).filter_by(nazwa='Standard').one_or_none()
            if standard is None:
                raise ValueError('Brak bazowej stawki Standard do naliczenia wpisowego.')
            entry_rate = int(parse_amount(standard.kwota) * 100)
            amount -= Decimal(entry_rate * 3) / 100
        public_id = (operation.query(func.max(Czlonek.numer_identyfikacyjny)).scalar() or 0) + 1
        member = Czlonek(numer_identyfikacyjny=public_id,imie_nazwisko=name,email=email or None,
            status_id=status_id,bilans_otwarcia=amount,aktywny=True,
            rok_dolaczenia=joined.year,miesiac_dolaczenia=joined.month)
        operation.add(member)
        operation.flush()
        if entry_fee:
            from models import Wpisowe
            operation.add(Wpisowe(czlonek_id=member.id, kwota_grosze=entry_rate * 3,
                stawka_grosze=entry_rate, obowiazuje_od=joined))
        from opening_balance import record_opening
        from annual_fees import cadence_year
        today = date.today()
        record_opening(operation,member.id,cadence_year(today.year,today.month),opening_amount,'Dodanie klienta — saldo początkowe')
        # Miesiące naliczone przed utworzeniem kartoteki muszą objąć także
        # nową osobę. Zapisujemy indywidualne należności w tych samych partiach,
        # aby cofnięcie miesiąca i późniejsze korekty zachowały pełną historię.
        from annual_fees import rate_cents
        from models import NaliczenieMiesiaca, NaliczenieCzlonka, StatusNaliczenia
        status = operation.get(Status, status_id)
        for batch in operation.query(NaliczenieMiesiaca).filter_by(cofnieto=None):
            if (batch.rok, batch.miesiac) < (joined.year, joined.month):
                continue
            cents = rate_cents(operation, status, batch.rok, batch.miesiac)
            charge = NaliczenieCzlonka(naliczenie_id=batch.id,
                czlonek_id=member.id, kwota_grosze=cents)
            operation.add(charge)
            operation.flush()
            operation.add(StatusNaliczenia(naliczenie_czlonka_id=charge.id,
                status_id=status_id))
            amount -= Decimal(cents) / 100
        member.bilans_otwarcia = amount
        if account:
            operation.add(KontoBankowe(numer_konta=account,czlonek_id=member.id))
        operation.commit()
    return public_id, amount


def record_payment(session, member_id, amount, paid_on, token):
    amount = parse_amount(amount)
    if not isinstance(paid_on, datetime) or paid_on.date()>date.today() or paid_on.tzinfo is not None:
        raise ValueError('Podaj rzeczywistą datę wpłaty, nie późniejszą niż dzisiaj.')
    if not isinstance(token,str) or not token or len(token)>100:
        raise ValueError('Brak identyfikatora operacji.')
    payload = json.dumps([member_id,format(amount,'.2f'),paid_on.isoformat()])
    with Session(bind=session.get_bind()) as operation:
        operation.execute(text('BEGIN IMMEDIATE'))
        previous = operation.get(OperacjaReczna,token)
        if previous:
            if previous.dane_json != payload:
                raise ValueError('Identyfikator tej operacji został już użyty dla innych danych.')
            return previous.wplata_id
        member = operation.get(Czlonek,member_id)
        if not member:
            raise ValueError('Nie znaleziono kartoteki klienta.')
        payment = Wplata(czlonek_id=member_id,kwota=amount,data_przelewu=paid_on,
            tytul_oryginalny='Wpłata ręczna',metoda_dopasowania='Ręczna',czy_potwierdzona=True)
        operation.add(payment)
        operation.flush()
        operation.add(OperacjaReczna(token=token,wplata_id=payment.id,dane_json=payload))
        member.bilans_otwarcia = signed_amount(member.bilans_otwarcia or 0) + amount
        payment_id = payment.id
        operation.commit()
    for obj in list(session.identity_map.values()):
        if isinstance(obj,Czlonek) and obj.id==member_id:
            session.expire(obj,['bilans_otwarcia'])
    return payment_id
