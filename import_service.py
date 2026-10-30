"""Jeden importer XLSX: podgląd, jawna waluta, ostrożne duplikaty i atomowy zapis."""
from dataclasses import dataclass, replace
from collections import Counter
from datetime import datetime, date
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
import json
import re
import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session
from models import Czlonek, Wplata, ImportWyciagu, PozycjaWyciagu
from fee_service import parse_amount
from finance_service import signed_amount

DEFAULT_COLUMNS = {'date':'Data operacji','amount':'Kwota','title':'Opis transakcji',
                   'currency':'Waluta','bank_id':'','sender':'Nazwa nadawcy'}


@dataclass(frozen=True)
class BankRow:
    number: int
    paid_on: datetime | None
    cents: int | None
    title: str
    bank_id: str | None
    public_id: int | None
    member_id: int | None
    fingerprint: str
    state: str
    issue: str
    sender: str = ""


@dataclass(frozen=True)
class ImportPlan:
    file_hash: str
    rows: tuple


def _value(value):
    return '' if pd.isna(value) else str(value).strip()


def preview_import(session, path, columns=None, currency=None, date_format='%Y-%m-%d'):
    path = Path(path)
    if path.suffix.lower() != '.xlsx' or path.stat().st_size > 20*1024*1024:
        raise ValueError('Wybierz plik XLSX do 20 MB.')
    content = path.read_bytes()
    frame = pd.read_excel(path,dtype=object)
    return preview_rows(session,frame,sha256(content).hexdigest(),columns,currency,date_format)


def preview_rows(session, frame, file_hash, columns=None, currency=None, date_format='%Y-%m-%d'):
    columns = dict(DEFAULT_COLUMNS, **(columns or {}))
    if date_format not in ('%Y-%m-%d','%d.%m.%Y'):
        raise ValueError('Wybierz jawny format daty: RRRR-MM-DD albo DD.MM.RRRR.')
    if not all(columns[key] in frame.columns for key in ('date','amount','title')):
        raise ValueError('Brakuje skonfigurowanych kolumn daty, kwoty lub tytułu.')
    if len(frame)>20000:
        raise ValueError('Maksymalna liczba wierszy w jednym imporcie to 20 000.')
    currency_column = columns.get('currency') in frame.columns
    if not currency_column and currency != 'PLN':
        raise ValueError('Brak kolumny waluty. Jawnie wybierz PLN dla tego wyciągu lub popraw konfigurację kolumn.')
    with Session(bind=session.get_bind()) as operation:
        if operation.query(ImportWyciagu).filter_by(sha256=file_hash).first():
            raise ValueError('Ten sam plik został już zapisany. Nie wykonano ponownego importu.')
        members = {m.numer_identyfikacyjny:m.id for m in operation.query(Czlonek)}
        bank_ids = {value for value, in operation.query(PozycjaWyciagu.id_bankowe).filter(PozycjaWyciagu.id_bankowe.is_not(None))}
        fingerprints = {value for value, in operation.query(PozycjaWyciagu.odcisk).filter(PozycjaWyciagu.wplata_id.is_not(None))}
        for payment in operation.query(Wplata):
            try:
                legacy_cents = int(parse_amount(payment.kwota)*100)
                fingerprint = sha256(json.dumps([payment.data_przelewu.isoformat(),legacy_cents,
                    payment.tytul_oryginalny or '', 'PLN'],ensure_ascii=False).encode('utf-8')).hexdigest()
                fingerprints.add(fingerprint)
            except (ValueError,AttributeError):
                continue
    result = []
    for offset, (_, source) in enumerate(frame.iterrows(), start=2):
        title = _value(source[columns['title']])
        sender = _value(source[columns['sender']]) if columns.get('sender') in frame.columns else ''
        bank_id = _value(source[columns['bank_id']]) if columns.get('bank_id') in frame.columns else ''
        ids = re.findall(r'(?<![\w!])A!([0-9]+)(?![\w!])',title)
        public_id = int(ids[0]) if len(ids)==1 else None
        member_id = members.get(public_id)
        paid_on, cents, issue, state = None, None, '', 'ready'
        try:
            raw_date = source[columns['date']]
            if isinstance(raw_date,datetime):
                paid_on = raw_date
            elif isinstance(raw_date,date):
                paid_on = datetime.combine(raw_date,datetime.min.time())
            elif isinstance(raw_date,str):
                paid_on = datetime.strptime(raw_date.strip(),date_format)
            else:
                raise ValueError('Nieprawidłowa data.')
            if pd.isna(paid_on) or paid_on.tzinfo is not None or paid_on.date()>date.today():
                raise ValueError('Nieprawidłowa lub przyszła data.')
            cents = int(parse_amount(source[columns['amount']])*100)
            row_currency = _value(source[columns['currency']]).upper() if currency_column else currency
            if row_currency != 'PLN':
                raise ValueError('Obsługiwane są wyłącznie dodatnie wpływy PLN.')
        except (ValueError,TypeError,OverflowError):
            issue, state = 'Sprawdź datę, dodatnią kwotę z maks. 2 miejscami i walutę PLN.', 'invalid'
        fingerprint = sha256(json.dumps([paid_on.isoformat() if paid_on and not pd.isna(paid_on) else None,
            cents,title,'PLN'],ensure_ascii=False).encode('utf-8')).hexdigest()
        if state=='ready' and (not member_id or len(ids)!=1):
            state, issue = 'review', 'Brak jednoznacznego znanego ID. Wymagane ręczne przypisanie.'
        if state!='invalid' and bank_id and bank_id in bank_ids:
            state, issue = 'duplicate', 'Identyfikator bankowy jest już zapisany.'
        elif state!='invalid' and not bank_id and fingerprint in fingerprints:
            state, issue = 'review', 'Podobna operacja istnieje. Potwierdź, że jest to odrębny nowy wpływ.'
        if paid_on is not None and pd.isna(paid_on):
            paid_on = None
        result.append(BankRow(offset,paid_on,cents,title,bank_id or None,public_id,member_id,fingerprint,state,issue,sender))
    counts = Counter(row.fingerprint for row in result if not row.bank_id)
    id_counts = Counter(row.bank_id for row in result if row.bank_id)
    result = [replace(row,state='invalid',issue='Powtórzony identyfikator bankowy w pliku.')
              if row.bank_id and id_counts[row.bank_id]>1 else
              replace(row,state='review',issue='Identyczne wiersze bez ID bankowego. Potwierdź odrębność wpływów.')
              if row.state=='ready' and not row.bank_id and counts[row.fingerprint]>1 else row for row in result]
    return ImportPlan(file_hash,tuple(result))


def commit_import(session, plan, selected_rows, assignments=None, confirmed_new=()):
    selected, confirmed_new = set(selected_rows), set(confirmed_new)
    assignments = assignments or {}
    if not selected or not selected.issubset({row.number for row in plan.rows}):
        raise ValueError('Zaznacz poprawne wiersze do zaksięgowania.')
    with Session(bind=session.get_bind()) as operation:
        operation.execute(text('BEGIN IMMEDIATE'))
        if operation.query(ImportWyciagu).filter_by(sha256=plan.file_hash).first():
            raise ValueError('Ten plik został już zapisany.')
        batch = ImportWyciagu(sha256=plan.file_hash)
        operation.add(batch)
        operation.flush()
        count = 0
        for row in plan.rows:
            payment_id, state = None, 'omitted'
            if row.number in selected:
                if row.state in ('invalid','duplicate') or row.paid_on is None or row.cents is None:
                    raise ValueError(f'Wiersz {row.number}: błędna lub powtórzona operacja nie może być zapisana.')
                if row.state=='review' and row.number not in confirmed_new:
                    raise ValueError(f'Wiersz {row.number}: wymagane jawne zatwierdzenie ręcznego sprawdzenia.')
                if row.bank_id and operation.query(PozycjaWyciagu).filter_by(id_bankowe=row.bank_id).first():
                    raise ValueError('Identyfikator bankowy został zapisany od czasu podglądu. Wczytaj plik ponownie.')
                overlap = operation.query(PozycjaWyciagu).filter_by(odcisk=row.fingerprint).filter(PozycjaWyciagu.wplata_id.is_not(None)).first()
                legacy_overlap = operation.query(Wplata).filter_by(data_przelewu=row.paid_on,
                    kwota=Decimal(row.cents)/100,tytul_oryginalny=row.title).first()
                if not row.bank_id and (overlap or legacy_overlap) and row.number not in confirmed_new:
                    raise ValueError('Podobna operacja została zapisana od czasu podglądu. Sprawdź ją ponownie.')
                member_id = assignments.get(row.number,row.member_id)
                member = operation.get(Czlonek,member_id) if member_id else None
                if not member:
                    raise ValueError(f'Wiersz {row.number}: ręcznie wybierz klienta.')
                if row.number not in assignments and member.numer_identyfikacyjny != row.public_id:
                    raise ValueError('ID klienta zmieniło się od czasu podglądu. Wczytaj plik ponownie.')
                payment = Wplata(czlonek_id=member.id,kwota=Decimal(row.cents)/100,
                    data_przelewu=row.paid_on,tytul_oryginalny=row.title,
                    metoda_dopasowania='Import ręczny' if row.number in assignments else 'Import A!',czy_potwierdzona=True)
                operation.add(payment)
                member.bilans_otwarcia = signed_amount(member.bilans_otwarcia or 0)+Decimal(row.cents)/100
                operation.flush()
                payment_id, state = payment.id, 'posted'
                count += 1
            # Nie rezerwuj ID bankowego dla pominiętej pozycji — można ją obsłużyć w osobnym wyciągu.
            data = json.dumps(dict(date=row.paid_on.isoformat() if row.paid_on and not pd.isna(row.paid_on) else None,
                cents=row.cents,title=row.title,sender=row.sender,public_id=row.public_id,issue=row.issue,bank_id=row.bank_id,source_state=row.state),ensure_ascii=False)
            operation.add(PozycjaWyciagu(import_id=batch.id,numer_wiersza=row.number,odcisk=row.fingerprint,
                id_bankowe=row.bank_id if payment_id else None,wplata_id=payment_id,dane_json=data,stan=state))
        operation.commit()
    for obj in list(session.identity_map.values()):
        if isinstance(obj,Czlonek):
            session.expire(obj,['bilans_otwarcia'])
    return count


def pending_imports(engine):
    with Session(engine) as operation:
        return [dict(id=row.id,number=row.numer_wiersza,**json.loads(row.dane_json))
            for row in operation.query(PozycjaWyciagu).filter_by(stan='omitted').order_by(PozycjaWyciagu.id).limit(20000)]


def post_pending(session, record_ids, assignments=None):
    """Wyłącznie po jawnym przypisaniu i potwierdzeniu w GUI; bez zmiany źródłowego wiersza."""
    assignments = assignments or {}
    selected = set(record_ids)
    if not selected:
        raise ValueError('Zaznacz pozycje z kolejki.')
    with Session(bind=session.get_bind()) as operation:
        operation.execute(text('BEGIN IMMEDIATE'))
        for record_id in selected:
            row = operation.get(PozycjaWyciagu,record_id)
            if not row or row.stan!='omitted':
                raise ValueError('Pozycja została już obsłużona. Odśwież kolejkę.')
            data = json.loads(row.dane_json)
            if data['source_state'] in ('invalid','duplicate') or data['cents'] is None or not data['date']:
                raise ValueError('Błędne dane źródłowe wymagają poprawienia wyciągu i nowego podglądu.')
            paid_on = datetime.fromisoformat(data['date'])
            amount = parse_amount(Decimal(data['cents'])/100)
            if paid_on.date()>date.today() or paid_on.tzinfo is not None:
                raise ValueError('Nieprawidłowa data wpływu.')
            bank_id = data.get('bank_id')
            if bank_id and operation.query(PozycjaWyciagu).filter_by(id_bankowe=bank_id).first():
                raise ValueError('Ta operacja bankowa jest już zapisana.')
            member_id = assignments.get(record_id)
            if member_id is None:
                member = operation.query(Czlonek).filter_by(numer_identyfikacyjny=data['public_id']).first() if data['public_id'] else None
            else:
                member = operation.get(Czlonek,member_id)
            if not member:
                raise ValueError('Ręcznie przypisz klienta do wybranej pozycji.')
            payment = Wplata(czlonek_id=member.id,kwota=amount,data_przelewu=paid_on,
                tytul_oryginalny=data['title'],metoda_dopasowania='Import — kolejka ręczna',czy_potwierdzona=True)
            operation.add(payment)
            member.bilans_otwarcia = signed_amount(member.bilans_otwarcia or 0)+amount
            operation.flush()
            row.wplata_id, row.id_bankowe, row.stan = payment.id, bank_id, 'posted'
        operation.commit()
    for obj in list(session.identity_map.values()):
        if isinstance(obj,Czlonek):
            session.expire(obj,['bilans_otwarcia'])
    return len(selected)


def transaction_details(title, sender=""):
    """Etykieta tytułu tylko raz; oryginalne dane importu pozostają bez zmian."""
    display_title = re.sub(r"^(?:\s*tytuł\s*:\s*)+", "", title or "", flags=re.IGNORECASE)
    return f'Tytuł: {display_title}\nNazwa nadawcy: {sender or "brak danych w wyciągu"}'
