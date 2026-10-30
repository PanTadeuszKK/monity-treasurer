"""Stawki kadencji i powiązane korekty, bez przepisywania historii."""
import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from fee_service import parse_amount
from models import (Czlonek, Status, HistoriaNaliczen, NaliczenieCzlonka,
                    NaliczenieMiesiaca, StatusNaliczenia, ZatwierdzenieStawek,
                    StawkaKadencji, KorektaStawki, KorektaStatusu, UzgodnienieMiesiaca, UzgodnienieHistorii)


def cadence_year(year, month):
    date(year, month, 1)
    return year if month >= 6 else year - 1


def latest_approval(operation, year):
    return operation.query(ZatwierdzenieStawek).filter_by(rok_kadencji=year).order_by(
        ZatwierdzenieStawek.rewizja.desc()).first()


def rate_cents(operation, status, year, month):
    """Zatwierdzona stawka kadencji lub prowizoryczna z poprzedniej kadencji."""
    term = cadence_year(year, month)
    rate = operation.query(StawkaKadencji).join(ZatwierdzenieStawek).filter(
        StawkaKadencji.status_id == status.id,
        ZatwierdzenieStawek.rok_kadencji <= term).order_by(
        ZatwierdzenieStawek.rok_kadencji.desc(), ZatwierdzenieStawek.rewizja.desc()).first()
    return rate.kwota_grosze if rate else int(parse_amount(status.kwota) * 100)


def effective_charge_cents(operation, charge):
    adjustments = operation.query(func.coalesce(func.sum(KorektaStawki.roznica_grosze), 0)).filter_by(
        naliczenie_czlonka_id=charge.id).scalar()
    status_adjustments = operation.query(func.coalesce(func.sum(KorektaStatusu.roznica_grosze), 0)).filter_by(
        naliczenie_czlonka_id=charge.id).scalar()
    return charge.kwota_grosze + adjustments + status_adjustments


@dataclass(frozen=True)
class FeePlan:
    year: int
    decision_date: date
    previous_id: int | None
    rates: tuple
    # charge ID, member ID, historical status, current amount, target amount
    charges: tuple
    unchanged: bool
    history: tuple = ()
    member_periods: tuple = ()
    charge_periods: tuple = ()

    @property
    def correction_count(self):
        return sum(current != target for _, _, _, current, target in self.charges)

    @property
    def total_cents(self):
        return sum(target - current for _, _, _, current, target in self.charges)


def _build_plan(operation, year, values, decision_date):
    start, end = date(year, 6, 1), date(year + 1, 6, 1)
    if not isinstance(decision_date, date) or isinstance(decision_date, datetime):
        raise ValueError("Podaj datę decyzji w formacie RRRR-MM-DD.")
    if not start <= decision_date < end:
        raise ValueError("Data decyzji musi należeć do wybranej kadencji.")
    if decision_date > date.today():
        raise ValueError("Data decyzji nie może być przyszła.")
    rates = {key: int(parse_amount(value) * 100) for key, value in values.items()}
    status_ids = {row.id for row in operation.query(Status).all()}
    if not rates or set(rates) != status_ids:
        raise ValueError("Podaj stawki wszystkich statusów. Otwórz formularz ponownie, jeśli lista się zmieniła.")
    previous = latest_approval(operation, year)
    if previous and decision_date < previous.data_decyzji:
        raise ValueError("Data nowej decyzji nie może poprzedzać poprzedniego zatwierdzenia.")
    old_rates = ({row.status_id: row.kwota_grosze for row in operation.query(StawkaKadencji).filter_by(
        zatwierdzenie_id=previous.id)} if previous else {})
    # Dawna tabela nie pozwala wiarygodnie przypisać stawek poszczególnym osobom.
    for legacy in operation.query(HistoriaNaliczen).all():
        if cadence_year(legacy.rok, legacy.miesiac) == year and operation.get(UzgodnienieMiesiaca, legacy.id) is None:
            raise ValueError("Ta kadencja zawiera dawne naliczenia bez kwot osób. Najpierw trzeba uzgodnić ich historię; nie wykonano zmian.")
    charges = []
    charge_periods = []
    batches = operation.query(NaliczenieMiesiaca).filter_by(cofnieto=None).all()
    for batch in batches:
        if cadence_year(batch.rok, batch.miesiac) != year:
            continue
        for charge in operation.query(NaliczenieCzlonka).filter_by(naliczenie_id=batch.id):
            snapshot = operation.get(StatusNaliczenia, charge.id)
            if snapshot is None or snapshot.status_id not in rates:
                raise ValueError("Naliczenie nie ma zapisanego historycznego statusu. Nie wolno użyć bieżącego statusu do korekty; nie wykonano zmian.")
            from member_status import status_for_month
            member = operation.get(Czlonek, charge.czlonek_id)
            target_status = status_for_month(operation, member, batch.rok, batch.miesiac, snapshot.status_id)
            if target_status not in rates:
                raise ValueError("Brak stawki dla statusu obowiązującego w miesiącu naliczenia.")
            charges.append((charge.id, charge.czlonek_id, target_status,
                effective_charge_cents(operation, charge), rates[target_status]))
            charge_periods.append((charge.id, batch.rok, batch.miesiac))
    return FeePlan(year, decision_date, previous.id if previous else None,
                   tuple(sorted(rates.items())), tuple(sorted(charges)),
                   old_rates == rates and all(current == target for _, _, _, current, target in charges),
                   charge_periods=tuple(sorted(charge_periods)))


def preview_fees(session, year, values, decision_date, history=None):
    # Tymczasowe zapisy są wycofywane przy zamknięciu sesji; saldo nie jest zmieniane.
    with Session(bind=session.get_bind()) as operation:
        operation.execute(text('BEGIN IMMEDIATE'))
        confirmed = _prepare_history(operation, year, history)
        plan = _build_plan(operation, year, values, decision_date)
        return FeePlan(plan.year, plan.decision_date, plan.previous_id, plan.rates,
                       plan.charges, plan.unchanged and not confirmed, confirmed, _member_periods(operation, confirmed), plan.charge_periods)


def approve_fees(session, year, values, decision_date, expected_plan=None, history=None):
    with Session(bind=session.get_bind()) as operation:
        operation.execute(text('BEGIN IMMEDIATE'))
        confirmed = _prepare_history(operation, year, history)
        base = _build_plan(operation, year, values, decision_date)
        plan = FeePlan(base.year, base.decision_date, base.previous_id, base.rates,
                       base.charges, base.unchanged and not confirmed, confirmed, _member_periods(operation, confirmed), base.charge_periods)
        if expected_plan is not None and expected_plan != plan:
            raise ValueError("Dane zmieniły się od podglądu. Sprawdź i zatwierdź nowy podgląd.")
        if plan.unchanged:
            return plan
        previous = operation.get(ZatwierdzenieStawek, plan.previous_id) if plan.previous_id else None
        approval = ZatwierdzenieStawek(rok_kadencji=year,
            rewizja=previous.rewizja + 1 if previous else 1,
            data_decyzji=decision_date, obowiazuje_od=date(year, 6, 1))
        operation.add(approval)
        operation.flush()
        if confirmed:
            operation.add(UzgodnienieHistorii(zatwierdzenie_id=approval.id,
                dane_json=json.dumps(confirmed)))
        for status_id, cents in plan.rates:
            operation.add(StawkaKadencji(zatwierdzenie_id=approval.id,
                status_id=status_id, kwota_grosze=cents))
        for charge_id, member_id, _, current, target in plan.charges:
            delta = target - current
            if delta:
                member = operation.get(Czlonek, member_id)
                if member is None:
                    raise ValueError("Brak kartoteki powiązanej z naliczeniem.")
                member.bilans_otwarcia = Decimal(str(member.bilans_otwarcia or 0)) - Decimal(delta) / 100
                operation.add(KorektaStawki(naliczenie_czlonka_id=charge_id,
                    zatwierdzenie_id=approval.id, roznica_grosze=delta))
        operation.commit()
    # Bez odrzucania niezapisanych edycji w innych oknach.
    for obj in list(session.identity_map.values()):
        if isinstance(obj, Czlonek):
            session.expire(obj, ['bilans_otwarcia'])
    return plan


def history_requirements(session, year):
    """Każdy brak wymaga jawnej decyzji; bieżący status nie jest podpowiedzią historii."""
    with Session(bind=session.get_bind()) as operation:
        return _history_requirements(operation, year)


def _history_requirements(operation, year):
    rows = []
    members = operation.query(Czlonek).order_by(Czlonek.id).all()
    periods = set()
    for legacy in operation.query(HistoriaNaliczen).order_by(HistoriaNaliczen.id):
        if cadence_year(legacy.rok, legacy.miesiac) != year or operation.get(UzgodnienieMiesiaca, legacy.id):
            continue
        period = (legacy.rok, legacy.miesiac)
        if period in periods or operation.query(NaliczenieMiesiaca).filter_by(
                rok=legacy.rok, miesiac=legacy.miesiac, cofnieto=None).first():
            raise ValueError("Stara historia zawiera nakładające się naliczenia miesiąca. Wymaga indywidualnego sprawdzenia.")
        periods.add(period)
        if not members:
            raise ValueError("Brak kartotek do potwierdzenia dawnej historii.")
        for member in members:
            rows.append(('legacy', legacy.id, member.id, legacy.rok, legacy.miesiac,
                         member.imie_nazwisko, None))
    for batch in operation.query(NaliczenieMiesiaca).filter_by(cofnieto=None):
        if cadence_year(batch.rok, batch.miesiac) != year:
            continue
        for charge in operation.query(NaliczenieCzlonka).filter_by(naliczenie_id=batch.id):
            if operation.get(StatusNaliczenia, charge.id) is None:
                member = operation.get(Czlonek, charge.czlonek_id)
                rows.append(('snapshot', charge.id, charge.czlonek_id, batch.rok, batch.miesiac,
                             member.imie_nazwisko, charge.kwota_grosze))
    return tuple(rows)


def _prepare_history(operation, year, history):
    if history is None:
        return ()  # Zachowaj dotychczasową ochronę wywołań bez potwierdzenia historii.
    requirements = _history_requirements(operation, year)
    expected = {(kind, source, member) for kind, source, member, *_ in requirements}
    supplied = {(kind, source, member) for kind, source, member, _, _ in history}
    if supplied != expected or len(history) != len(expected):
        raise ValueError("Historia zmieniła się. Wczytaj kadencję i potwierdź wszystkie pozycje ponownie.")
    statuses = {s.id for s in operation.query(Status)}
    originals = {(k, source, member): cents for k, source, member, _, _, _, cents in requirements}
    normalized = []
    for kind, source, member, status_id, amount in history:
        if status_id == 0 and kind == 'legacy':
            if str(amount).strip() not in ('', '0', '0.00'):
                raise ValueError("Dla pozycji ‘Nie naliczono’ pozostaw kwotę pustą.")
            cents = 0
        else:
            if status_id not in statuses:
                raise ValueError("Wybierz historyczny status każdej pozycji.")
            cents = int(parse_amount(amount) * 100)
            if kind == 'snapshot' and cents != originals[(kind, source, member)]:
                raise ValueError("Zapisana pierwotna kwota naliczenia nie może być zmieniona.")
        normalized.append((kind, source, member, status_id, cents))
    batches = {}
    for kind, source, member, status_id, cents in sorted(normalized):
        if kind == 'snapshot':
            operation.add(StatusNaliczenia(naliczenie_czlonka_id=source, status_id=status_id))
            continue
        if source not in batches:
            legacy = operation.get(HistoriaNaliczen, source)
            batch = NaliczenieMiesiaca(rok=legacy.rok, miesiac=legacy.miesiac)
            operation.add(batch)
            operation.flush()
            batches[source] = batch.id
            operation.add(UzgodnienieMiesiaca(historia_id=source, naliczenie_id=batch.id))
        if status_id:
            charge = NaliczenieCzlonka(naliczenie_id=batches[source], czlonek_id=member, kwota_grosze=cents)
            operation.add(charge)
            operation.flush()
            operation.add(StatusNaliczenia(naliczenie_czlonka_id=charge.id, status_id=status_id))
    operation.flush()
    return tuple(sorted(normalized))


def bulk_history(session, year, previous_rates, original_statuses):
    """Zbiorcza deklaracja dawnych stawek/statusów zamiast wpisywania każdego miesiąca."""
    with Session(bind=session.get_bind()) as operation:
        rates = {key: int(parse_amount(value) * 100) for key, value in previous_rates.items()}
        result = []
        for kind, source, member_id, row_year, month, _, original_cents in _history_requirements(operation, year):
            member = operation.get(Czlonek, member_id)
            status_id = original_statuses.get(member_id)
            if status_id not in rates:
                raise ValueError("Wybierz status użyty przy dawnych naliczeniach dla każdej osoby.")
            if not member.rok_dolaczenia or not member.miesiac_dolaczenia or (
                    not member.aktywny and not (member.rok_odejscia and member.miesiac_odejscia)):
                raise ValueError("Uzupełnij daty umowy w kartotece przed przeliczeniem.")
            target = row_year * 12 + month
            start = member.rok_dolaczenia * 12 + member.miesiac_dolaczenia
            end = (member.rok_odejscia * 12 + member.miesiac_odejscia
                   if member.rok_odejscia and member.miesiac_odejscia else float('inf'))
            if kind == 'legacy' and not start <= target <= end:
                result.append((kind, source, member_id, 0, ''))
            else:
                cents = original_cents if original_cents is not None else rates[status_id]
                result.append((kind, source, member_id, status_id, str(Decimal(cents) / 100)))
        return result


def _member_periods(operation, history):
    result = []
    for member_id in sorted({row[2] for row in history}):
        member = operation.get(Czlonek, member_id)
        result.append((member.id, member.rok_dolaczenia, member.miesiac_dolaczenia,
                       member.rok_odejscia, member.miesiac_odejscia, member.aktywny))
    return tuple(result)
