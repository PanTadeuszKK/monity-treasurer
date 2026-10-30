"""Datowane zmiany statusu i korekty zapisanych indywidualnych naliczeń."""
from datetime import date
from decimal import Decimal
from models import (Status, ZmianaStatusu, KorektaStatusu, NaliczenieMiesiaca,
                    NaliczenieCzlonka)


def status_for_month(operation, member, year, month, fallback=None):
    target = date(year, month, 1)
    changes = operation.query(ZmianaStatusu).filter_by(czlonek_id=member.id)
    change = changes.filter(ZmianaStatusu.obowiazuje_od <= target).order_by(
        ZmianaStatusu.obowiazuje_od.desc(), ZmianaStatusu.id.desc()).first()
    if change:
        return change.nowy_status_id
    if fallback is not None:
        return fallback
    first = changes.order_by(ZmianaStatusu.obowiazuje_od, ZmianaStatusu.id).first()
    return first.poprzedni_status_id if first else member.status_id


def change_status(operation, member, new_status_id, effective):
    """Wywołujący zapisuje kartotekę, zdarzenie i korekty w tej samej transakcji."""
    from annual_fees import rate_cents, effective_charge_cents
    if new_status_id == member.status_id:
        return 0
    if not isinstance(effective, date) or effective.day != 1:
        raise ValueError("Podaj miesiąc i rok obowiązywania nowego statusu.")
    if effective > date.today():
        raise ValueError("Zmiana statusu nie może zaczynać się w przyszłości.")
    if not operation.get(Status, new_status_id) or not operation.get(Status, member.status_id):
        raise ValueError("Wybierz prawidłowy status klienta.")
    if member.rok_dolaczenia and member.miesiac_dolaczenia and effective < date(
            member.rok_dolaczenia, member.miesiac_dolaczenia, 1):
        raise ValueError("Zmiana statusu nie może poprzedzać dołączenia.")
    latest = operation.query(ZmianaStatusu).filter_by(czlonek_id=member.id).order_by(
        ZmianaStatusu.obowiazuje_od.desc(), ZmianaStatusu.id.desc()).first()
    if latest and effective < latest.obowiazuje_od:
        raise ValueError("Zapisz zmiany statusu w kolejności miesięcy obowiązywania.")
    change = ZmianaStatusu(czlonek_id=member.id, poprzedni_status_id=member.status_id,
                          nowy_status_id=new_status_id, obowiazuje_od=effective)
    operation.add(change)
    operation.flush()
    member.status_id = new_status_id
    operation.expire(member, ['status'])
    delta_total = 0
    for charge, batch in operation.query(NaliczenieCzlonka, NaliczenieMiesiaca).join(
            NaliczenieMiesiaca, NaliczenieCzlonka.naliczenie_id == NaliczenieMiesiaca.id).filter(
            NaliczenieCzlonka.czlonek_id == member.id, NaliczenieMiesiaca.cofnieto.is_(None)):
        if date(batch.rok, batch.miesiac, 1) < effective:
            continue
        status = operation.get(Status, status_for_month(operation, member, batch.rok, batch.miesiac))
        delta = rate_cents(operation, status, batch.rok, batch.miesiac) - effective_charge_cents(operation, charge)
        if delta:
            operation.add(KorektaStatusu(naliczenie_czlonka_id=charge.id,
                zmiana_statusu_id=change.id, roznica_grosze=delta))
            delta_total += delta
    member.bilans_otwarcia = Decimal(str(member.bilans_otwarcia or 0)) - Decimal(delta_total) / 100
    operation.flush()
    return delta_total
