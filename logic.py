from datetime import datetime
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session

from member_status import status_for_month
from models import Status
from annual_fees import rate_cents, effective_charge_cents
from models import Czlonek, HistoriaNaliczen, NaliczenieMiesiaca, NaliczenieCzlonka, StatusNaliczenia, UzgodnienieMiesiaca


class KalkulatorSkladek:
    def __init__(self, session):
        self.session = session

    def _czy_obejmuje_okres(self, cel_rok, cel_miesiac, r_od, m_od, r_do, m_do):
        target = cel_rok * 12 + cel_miesiac
        start = r_od * 12 + m_od if r_od and m_od else 0
        end = r_do * 12 + m_do if r_do and m_do else float('inf')
        return start <= target <= end

    def _validate_period(self, rok, miesiac):
        datetime(rok, miesiac, 1)

    def czy_naliczone(self, rok, miesiac):
        self._validate_period(rok, miesiac)
        with Session(bind=self.session.get_bind()) as operation:
            return self._is_charged(operation, rok, miesiac)

    def _is_charged(self, operation, rok, miesiac):
        legacy = operation.query(HistoriaNaliczen).filter_by(rok=rok, miesiac=miesiac).first()
        active = operation.query(NaliczenieMiesiaca).filter_by(rok=rok, miesiac=miesiac, cofnieto=None).first()
        return (legacy is not None and operation.get(UzgodnienieMiesiaca, legacy.id) is None) or active is not None

    def _refresh_balances(self):
        for obj in list(self.session.identity_map.values()):
            if isinstance(obj, Czlonek):
                self.session.expire(obj, ['bilans_otwarcia'])

    def dodaj_naleznosc(self, rok, miesiac):
        try:
            self._validate_period(rok, miesiac)
            with Session(bind=self.session.get_bind()) as operation:
                # Rezerwacja zapisu przed odczytem zabezpiecza dwa okna/procesy.
                operation.execute(text('BEGIN IMMEDIATE'))
                if self._is_charged(operation, rok, miesiac):
                    return False, "Należność za ten miesiąc została już dodana."
                batch = NaliczenieMiesiaca(rok=rok, miesiac=miesiac)
                operation.add(batch)
                operation.flush()
                count = 0
                for member in operation.query(Czlonek).all():
                    if not member.aktywny and not (member.rok_odejscia and member.miesiac_odejscia):
                        raise ValueError("Archiwalna kartoteka nie ma daty odejścia. Uzupełnij ją przed naliczeniem.")
                    if not self._czy_obejmuje_okres(rok, miesiac, member.rok_dolaczenia,
                            member.miesiac_dolaczenia, member.rok_odejscia, member.miesiac_odejscia):
                        continue
                    if member.status is None:
                        raise ValueError("Kartoteka objęta naliczeniem nie ma statusu.")
                    historical_status_id = status_for_month(operation, member, rok, miesiac)
                    historical_status = operation.get(Status, historical_status_id)
                    cents = rate_cents(operation, historical_status, rok, miesiac)
                    amount = Decimal(cents) / 100
                    charge = NaliczenieCzlonka(naliczenie_id=batch.id,
                        czlonek_id=member.id, kwota_grosze=cents)
                    operation.add(charge)
                    operation.flush()
                    operation.add(StatusNaliczenia(naliczenie_czlonka_id=charge.id,
                        status_id=historical_status_id))
                    member.bilans_otwarcia = Decimal(str(member.bilans_otwarcia or 0)) - amount
                    count += 1
                operation.commit()
            self._refresh_balances()
            return True, f"Naliczono należności za {miesiac}/{rok} dla {count} osób."
        except ValueError as exc:
            return False, str(exc)
        except Exception:
            return False, "Nie udało się zapisać naliczenia. Operacja została wycofana."

    def zdejmij_naleznosc(self, rok, miesiac):
        try:
            self._validate_period(rok, miesiac)
            with Session(bind=self.session.get_bind()) as operation:
                operation.execute(text('BEGIN IMMEDIATE'))
                legacy = operation.query(HistoriaNaliczen).filter_by(rok=rok, miesiac=miesiac).first()
                if legacy and operation.get(UzgodnienieMiesiaca, legacy.id) is None:
                    return False, "Dawne naliczenie nie zawiera kwot poszczególnych osób. Automatyczne cofnięcie jest zablokowane."
                batch = operation.query(NaliczenieMiesiaca).filter_by(
                    rok=rok, miesiac=miesiac, cofnieto=None).first()
                if batch is None:
                    return False, "Brak należności do cofnięcia za ten miesiąc."
                for charge in operation.query(NaliczenieCzlonka).filter_by(naliczenie_id=batch.id):
                    member = operation.get(Czlonek, charge.czlonek_id)
                    if member is None:
                        raise ValueError("Brak kartoteki powiązanej z naliczeniem.")
                    member.bilans_otwarcia = (Decimal(str(member.bilans_otwarcia or 0))
                                             + Decimal(effective_charge_cents(operation, charge)) / 100)
                batch.cofnieto = datetime.now()
                operation.commit()
            self._refresh_balances()
            return True, f"Cofnięto należności za {miesiac}/{rok}, zachowując historię."
        except ValueError as exc:
            return False, str(exc)
        except Exception:
            return False, "Nie udało się cofnąć naliczenia. Operacja została wycofana."
