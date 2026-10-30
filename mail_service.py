"""Trwała kolejka poczty. Każda wiadomość ma osobnego odbiorcę i trwały identyfikator."""
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
from string import Formatter
from uuid import uuid4
import json
import os
from email.utils import make_msgid
from sqlalchemy import text
from sqlalchemy.orm import Session
from models import Czlonek, WysylkaEmail
from mailer import Mailer, valid_address
from annual_fees import cadence_year
from opening_balance import opening_balances, opening_description
from mail_content import payment_details, text_to_html

DEFAULT_SUBJECT = 'Zestawienie składek — {kadencja}'
DEFAULT_TEMPLATE = ('Cześć {imie},\n\n{rozliczenie_poczatkowe}\nTwoje aktualne saldo składek wynosi {saldo} PLN.\n'
    'Do zapłaty na dziś: {zaleglosc} PLN.\n'
    'Nadpłata na dziś: {nadplata} PLN (względem dotychczas naliczonych składek).\n'
    'Identyfikator klienta: A!{id}. Okres rozliczeniowy: {kadencja}.\n\n{dane_przelewu}\n\nPozdrawiam,\nObsługa rozliczeń')
FIELDS = {'imie', 'id', 'saldo', 'zaleglosc', 'nadplata', 'rozliczenie_poczatkowe', 'dane_przelewu', 'kadencja'}


@dataclass(frozen=True)
class MailItem:
    member_id: int
    name: str
    recipient: str
    subject: str
    body: str
    balance_cents: int
    active: bool


@dataclass(frozen=True)
class MailPlan:
    sender: str
    scope: str
    subject_template: str
    body_template: str
    items: tuple
    skipped: tuple


def _validate_template(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 50000:
        raise ValueError('Wpisz treść i temat wiadomości (maksymalnie 50 000 znaków).')
    try:
        for _, field, spec, conversion in Formatter().parse(value):
            if field is not None and (field not in FIELDS or spec or conversion):
                raise ValueError('Dozwolone pola: {imie}, {id}, {saldo}, {zaleglosc}, {nadplata}, {rozliczenie_poczatkowe}, {dane_przelewu}, {kadencja}.')
    except (KeyError, IndexError) as exc:
        raise ValueError('Nieprawidłowy szablon wiadomości.') from exc


def preview_batch(session, sender, scope, subject_template, body_template):
    if not valid_address(sender):
        raise ValueError('Skonfiguruj prawidłowy adres nadawcy Gmail.')
    if scope not in ('active', 'debt'):
        raise ValueError('Wybierz grupę odbiorców.')
    _validate_template(subject_template)
    _validate_template(body_template)
    if '\n' in subject_template or '\r' in subject_template or len(subject_template) > 200:
        raise ValueError('Temat musi mieć jedną linię, maksymalnie 200 znaków.')
    now = datetime.now()
    year = cadence_year(now.year, now.month)
    items, skipped = [], []
    with Session(bind=session.get_bind()) as operation:
        openings = opening_balances(operation, year)
        for member in operation.query(Czlonek).order_by(Czlonek.imie_nazwisko, Czlonek.id):
            balance = Decimal(str(member.bilans_otwarcia or 0))
            if not balance.is_finite():
                raise ValueError('Kartoteka ma nieprawidłowe saldo. Uzgodnij je przed wysyłką.')
            if (scope == 'active' and not member.aktywny) or (scope == 'debt' and balance >= 0):
                continue
            address = (member.email or '').strip()
            if not valid_address(address):
                skipped.append((member.id, member.imie_nazwisko, 'Brak prawidłowego adresu e-mail.'))
                continue
            values = dict(imie=member.imie_nazwisko, id=member.numer_identyfikacyjny,
                saldo=format(balance, '.2f'), zaleglosc=format(max(-balance, Decimal(0)), '.2f'),
                nadplata=format(max(balance, Decimal(0)), '.2f'),
                rozliczenie_poczatkowe=opening_description(openings.get(member.id),year),
                dane_przelewu=payment_details(member.imie_nazwisko,member.numer_identyfikacyjny),
                kadencja=f'{year}/{year+1}')
            subject = subject_template.format(**values)
            body = body_template.format(**values)
            if '\r' in subject or '\n' in subject:
                raise ValueError('Dane klienta powodują nieprawidłowy temat wiadomości.')
            items.append(MailItem(member.id, member.imie_nazwisko, address, subject, body,
                                  int(balance * 100), bool(member.aktywny)))
    return MailPlan(sender, scope, subject_template, body_template, tuple(items), tuple(skipped))


def _key(sender, member_id, recipient, subject, body, mode):
    return sha256(json.dumps([sender.lower(), member_id, recipient.lower(), subject, body, mode],
                             ensure_ascii=False).encode('utf-8')).hexdigest()


def _enqueue(operation, campaign, sender, item, mode, is_html=False):
    key = _key(sender, item.member_id, item.recipient, item.subject, item.body, mode + str(is_html))
    existing = operation.query(WysylkaEmail).filter_by(klucz=key).first()
    if existing:
        return None
    row = WysylkaEmail(kampania=campaign, klucz=key, czlonek_id=item.member_id,
        nadawca=sender, odbiorca=item.recipient, temat=item.subject, tresc=item.body, czy_html=is_html,
        message_id=make_msgid(domain='monity.local'), tryb=mode, stan='pending')
    operation.add(row)
    operation.flush()
    return row.id


def prepare_batch(session, plan, selected_ids):
    selected = set(selected_ids)
    if not selected or not selected.issubset({item.member_id for item in plan.items}):
        raise ValueError('Zaznacz co najmniej jednego prawidłowego odbiorcę z podglądu.')
    campaign = uuid4().hex
    mode = 'simulation' if os.environ.get('MONITY_MAIL_DRY_RUN') == '1' else 'real'
    with Session(bind=session.get_bind()) as operation:
        operation.execute(text('BEGIN IMMEDIATE'))
        current = preview_batch(operation, plan.sender, plan.scope, plan.subject_template, plan.body_template)
        if current != plan:
            raise ValueError('Dane odbiorców zmieniły się. Wygeneruj i zatwierdź nowy podgląd.')
        added = [_enqueue(operation, campaign, plan.sender, replace(item,body=text_to_html(item.body)), mode, is_html=True)
                 for item in plan.items if item.member_id in selected]
        if not any(added):
            raise ValueError('Te same wiadomości są już w rejestrze. Otwórz historię wysyłek zamiast tworzyć duplikaty.')
        operation.commit()
    return campaign, sum(row_id is not None for row_id in added), sum(row_id is None for row_id in added)


def prepare_single(session, member_id, sender, recipient, subject, body, is_html=False):
    if not valid_address(sender) or not valid_address(recipient) or not subject.strip() or any(c in subject for c in '\r\n'):
        raise ValueError('Sprawdź nadawcę, odbiorcę i temat wiadomości.')
    mode = 'simulation' if os.environ.get('MONITY_MAIL_DRY_RUN') == '1' else 'real'
    campaign = uuid4().hex
    with Session(bind=session.get_bind()) as operation:
        operation.execute(text('BEGIN IMMEDIATE'))
        member = operation.get(Czlonek, member_id)
        if not member or (member.email or '').strip() != recipient:
            raise ValueError('Adres klienta zmienił się. Wczytaj odbiorcę ponownie.')
        item = MailItem(member_id, member.imie_nazwisko, recipient, subject, body, 0, bool(member.aktywny))
        row_id = _enqueue(operation, campaign, sender, item, mode, is_html)
        if row_id is None:
            raise ValueError('Ta wiadomość znajduje się już w rejestrze wysyłek. Sprawdź jej stan w historii.')
        operation.commit()
    return campaign


def delivery_rows(engine, campaign=None):
    with Session(engine) as operation:
        query = operation.query(WysylkaEmail)
        if campaign:
            query = query.filter_by(kampania=campaign)
        return [dict(id=row.id, campaign=row.kampania, recipient=row.odbiorca, subject=row.temat,
            body=row.tresc, state=row.stan, mode=row.tryb, info=row.informacja,
            created=row.utworzono.isoformat(timespec='seconds'))
            for row in query.order_by(WysylkaEmail.id.desc()).limit(2000)]


def retry_failed(engine, campaign):
    """Wyłącznie jawne ponowienie pewnego braku przyjęcia. Nie dotyczy sending/uncertain."""
    with Session(engine) as operation:
        operation.execute(text('BEGIN IMMEDIATE'))
        rows = operation.query(WysylkaEmail).filter_by(kampania=campaign, stan='not_sent').all()
        for row in rows:
            row.stan, row.aktualizacja = 'pending', datetime.now()
            row.informacja = 'Jawnie zatwierdzono ponowienie po pewnym braku wysłania.'
        operation.commit()
        return len(rows)


def send_campaign(engine, campaign, config, stop_event, on_result=lambda *args: None, interval=1.0):
    mode = 'simulation' if os.environ.get('MONITY_MAIL_DRY_RUN') == '1' else 'real'
    with Session(engine) as operation:
        ids = [row.id for row in operation.query(WysylkaEmail).filter_by(kampania=campaign).order_by(WysylkaEmail.id)]
    for row_id in ids:
        if stop_event.is_set():
            break
        with Session(engine) as operation:
            operation.execute(text('BEGIN IMMEDIATE'))
            row = operation.get(WysylkaEmail, row_id)
            if row.stan != 'pending':
                continue
            if row.tryb != mode or row.nadawca != config.get('email'):
                raise ValueError('Tryb wysyłki lub nadawca różni się od zatwierdzonego podglądu.')
            row.stan, row.aktualizacja = 'sending', datetime.now()
            row.informacja = 'Rozpoczęto próbę. Po przerwaniu aplikacji sprawdź folder Wysłane; nie ponawiaj automatycznie.'
            payload = row.odbiorca, row.temat, row.tresc, row.message_id, row.czy_html
            operation.commit()  # Trwały ślad PRZED kontaktem z SMTP.
        mailer = Mailer(config.get('email', ''), config.get('haslo', ''))
        try:
            success, info = mailer.wyslij_wiadomosc(*payload[:3], message_id=payload[3], is_html=payload[4])
            state = 'accepted' if success else ('uncertain' if mailer.delivery_state == 'uncertain' else 'not_sent')
        except Exception:
            success, state, info = False, 'uncertain', 'Nie można potwierdzić wyniku. Sprawdź folder Wysłane.'
        with Session(engine) as operation:
            operation.execute(text('BEGIN IMMEDIATE'))
            row = operation.get(WysylkaEmail, row_id)
            row.stan, row.informacja, row.aktualizacja = state, info, datetime.now()
            operation.commit()
        on_result(row_id, state, info)
        if not success:
            break  # Bez automatycznych ponowień i kolejnych 500 prób przy awarii Gmail.
        if interval and stop_event.wait(interval):
            break
