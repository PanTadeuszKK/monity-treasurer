"""Walidacja całego formularza przed zmianą któregokolwiek statusu."""
from decimal import Decimal, InvalidOperation

from sqlalchemy import inspect
from models import Status


def parse_amount(value):
    try:
        amount = Decimal(str(value).strip().replace(",", "."))
    except InvalidOperation as exc:
        raise ValueError("Kwota musi być liczbą.") from exc
    if not amount.is_finite() or amount <= 0:
        raise ValueError("Kwota musi być dodatnia i skończona.")
    if amount > Decimal("999999999.99"):
        raise ValueError("Kwota przekracza obsługiwany zakres.")
    if amount != amount.quantize(Decimal("0.01")):
        raise ValueError("Kwota może mieć najwyżej dwa miejsca po przecinku.")
    return amount


def update_fees(session, values):
    # Osobna sesja nie zapisze zmian oczekujących w innych oknach GUI.
    from sqlalchemy.orm import Session
    parsed = {key: parse_amount(value) for key, value in values.items()}
    with Session(bind=session.get_bind()) as operation:
        with operation.begin():
            statuses = operation.query(Status).filter(Status.id.in_(parsed)).all()
            if len(statuses) != len(parsed):
                raise ValueError("Lista statusów uległa zmianie. Otwórz formularz ponownie.")
            for status in statuses:
                # Zastany schemat FLOAT; migracja do groszy wymaga osobnego etapu.
                status.kwota = parsed[status.id]
    # Odśwież tylko kwoty, bez odrzucania edycji pozostałych obiektów.
    for obj in list(session.identity_map.values()):
        if isinstance(obj, Status) and inspect(obj).identity[0] in parsed:
            session.expire(obj, ["kwota"])
