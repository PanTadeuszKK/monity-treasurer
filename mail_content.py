"""Wspólne dane przelewu i bezpieczne formatowanie maili."""
import html

BANK_ACCOUNT = '[numer rachunku do uzupełnienia]'
PAYEE = '[nazwa firmy do uzupełnienia]'
NOTE_PREFIX = 'WAŻNE: '


def payment_details(name, public_id):
    return (f'Odbiorca: {PAYEE}\n'
            f'Numer konta: {BANK_ACCOUNT}\n'
            f'{NOTE_PREFIX}W tytule przelewu należy podać: składka {name} A!{public_id}')


def text_to_html(value):
    lines=[]
    for line in value.split('\n'):
        escaped=html.escape(line)
        if line.startswith(NOTE_PREFIX):
            escaped=f'<strong style="color: #B00020;">{escaped}</strong>'
        lines.append(escaped)
    return '<br>'.join(lines)
