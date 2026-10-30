"""Walidacja i atomowy import kartotek z ustalonego formatu Excel."""
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
import unicodedata
import pandas as pd
from sqlalchemy import func, inspect, text
from sqlalchemy.orm import Session
from models import Czlonek, Status, KontoBankowe, ImportCzlonkow
from finance_service import signed_amount, bank_account
from mailer import valid_address
from opening_balance import record_opening
from annual_fees import cadence_year
from member_search import normalize_name

COLUMNS = ('Imie','Nazwisko','Numer Konta','Mail','Saldo','Data dołączenia','Status')

@dataclass(frozen=True)
class MemberRow:
    number: int
    name: str
    account: str
    email: str
    cents: int
    joined: date
    status_id: int

@dataclass(frozen=True)
class MemberPlan:
    digest: str
    rows: tuple
    warnings: tuple = ()


def cell(value):
    return '' if pd.isna(value) else str(value).strip()


def joined_date(value):
    if isinstance(value,datetime):
        if pd.isna(value) or value.tzinfo is not None:
            raise ValueError('Nieprawidłowa data dołączenia.')
        value=value.date()
    elif not isinstance(value,date):
        parsed=None
        for fmt in ('%Y-%m-%d','%d.%m.%Y','%Y-%m'):
            try:
                parsed=datetime.strptime(cell(value),fmt).date()
                break
            except ValueError:
                pass
        if parsed is None:
            raise ValueError('Data dołączenia: użyj daty Excel, RRRR-MM-DD lub DD.MM.RRRR.')
        value=parsed
    if value>date.today():
        raise ValueError('Data dołączenia nie może być przyszła.')
    return value.replace(day=1)


def validate_existing(session, rows, digest):
    if inspect(session.get_bind()).has_table('importy_czlonkow') and session.get(ImportCzlonkow,digest):
        raise ValueError('Ten sam plik klientów został już zaimportowany.')
    names={normalize_name(m.imie_nazwisko).strip() for m in session.query(Czlonek)}
    emails={cell(m.email).casefold() for m in session.query(Czlonek) if m.email}
    accounts={k.numer_konta for k in session.query(KontoBankowe)}
    for row in rows:
        name=normalize_name(row.name).strip()
        if name in names:
            raise ValueError(f'Wiersz {row.number}: osoba o tym imieniu i nazwisku już istnieje lub powtarza się w pliku. Sprawdź ręcznie.')
        if row.email and row.email.casefold() in emails:
            raise ValueError(f'Wiersz {row.number}: adres mailowy jest już przypisany lub powtarza się w pliku.')
        if row.account and row.account in accounts:
            raise ValueError(f'Wiersz {row.number}: rachunek jest już przypisany lub powtarza się w pliku.')
        if not session.get(Status,row.status_id):
            raise ValueError(f'Wiersz {row.number}: status zmienił się od podglądu.')
        names.add(name)
        if row.email: emails.add(row.email.casefold())
        if row.account: accounts.add(row.account)


def preview_members(session, path):
    path=Path(path)
    if path.suffix.lower()!='.xlsx' or not path.is_file() or path.stat().st_size>20*1024*1024:
        raise ValueError('Wybierz istniejący XLSX do 20 MB.')
    content=path.read_bytes()
    from io import BytesIO
    canonical={' '.join(normalize_name(c).split()):c for c in COLUMNS}
    header_sample=pd.read_excel(BytesIO(content),dtype=object,header=None,nrows=20)
    candidates=[]
    for index,source in header_sample.iterrows():
        normalized=[' '.join(normalize_name(cell(value)).split()) for value in source]
        if set(canonical).issubset(normalized):
            if any(normalized.count(key)!=1 for key in canonical):
                raise ValueError(f'Wiersz {index+1}: nagłówki kolumn powtarzają się.')
            candidates.append(index)
    if len(candidates)!=1:
        raise ValueError('Nie znaleziono jednego wiersza nagłówków w pierwszych 20 wierszach. Wymagane: '+', '.join(COLUMNS))
    header_index=candidates[0]
    frame=pd.read_excel(BytesIO(content),dtype=object,header=header_index)
    frame.columns=[canonical.get(' '.join(normalize_name(c).split()),str(c).strip()) for c in frame.columns]
    if not 1<=len(frame)<=20000:
        raise ValueError('Plik musi zawierać od 1 do 20 000 wierszy.')
    statuses={s.nazwa.casefold():s.id for s in session.query(Status)}
    rows=[]
    warnings=[]
    errors=[]
    for number,(_,source) in enumerate(frame.iterrows(),header_index+2):
        if all(not cell(source[c]) for c in COLUMNS):
            continue
        try:
            first,last=cell(source['Imie']),cell(source['Nazwisko'])
            name=' '.join((first+' '+last).split())
            if not first or not last or len(name)>200 or any(ord(c)<32 for c in first+last):
                raise ValueError('Wymagane poprawne imię i nazwisko.')
            email=cell(source['Mail'])
            if email and not valid_address(email):
                raise ValueError('Nieprawidłowy adres Mail.')
            raw_account=source['Numer Konta']
            if cell(raw_account) and not isinstance(raw_account,str):
                warnings.append(f'Wiersz {number}: pominięto rachunek zapisany jako liczba; klient zostanie dodany bez rachunku.')
                account=''
            else:
                try:
                    account=bank_account(cell(raw_account))
                except ValueError:
                    warnings.append(f'Wiersz {number}: pominięto niepoprawny rachunek; klient zostanie dodany bez rachunku.')
                    account=''
            if not cell(source['Saldo']):
                raise ValueError('Wpisz Saldo, także 0 przy braku zaległości i nadpłaty.')
            amount=-signed_amount(source['Saldo'])  # Excel: plus = zaległość, minus = nadpłata.
            status_id=statuses.get(cell(source['Status']).casefold())
            if status_id is None or cell(source['Status']).casefold() not in ('standard','premium'):
                raise ValueError('Status musi wynosić Standard albo Premium.')
            rows.append(MemberRow(number,name,account,email,int(amount*100),joined_date(source['Data dołączenia']),status_id))
        except ValueError as exc:
            errors.append(f'Wiersz {number}: {exc}')
    if errors:
        raise ValueError('\n'.join(errors))
    if not rows:
        raise ValueError('Brak wypełnionych kartotek.')
    digest=sha256(content).hexdigest()
    validate_existing(session,rows,digest)
    return MemberPlan(digest,tuple(rows),tuple(warnings))


def commit_members(session, plan):
    with Session(bind=session.get_bind()) as operation:
        operation.execute(text('BEGIN IMMEDIATE'))
        validate_existing(operation,plan.rows,plan.digest)
        next_id=(operation.query(func.max(Czlonek.numer_identyfikacyjny)).scalar() or 0)+1
        today=date.today();year=cadence_year(today.year,today.month)
        for offset,row in enumerate(plan.rows):
            member=Czlonek(numer_identyfikacyjny=next_id+offset,imie_nazwisko=row.name,
                email=row.email or None,status_id=row.status_id,bilans_otwarcia=Decimal(row.cents)/100,
                aktywny=True,rok_dolaczenia=row.joined.year,miesiac_dolaczenia=row.joined.month)
            operation.add(member);operation.flush()
            if row.account:
                operation.add(KontoBankowe(numer_konta=row.account,czlonek_id=member.id))
            record_opening(operation,member.id,year,Decimal(row.cents)/100,'Import klientów Excel — Saldo')
        operation.add(ImportCzlonkow(sha256=plan.digest,liczba=len(plan.rows)))
        operation.commit()
    return len(plan.rows)
