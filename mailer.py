"""SMTP Gmail: weryfikacja TLS, limit czasu i jawny stan wysyłki."""
import json
import os
import re
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path

from paths import data_path


def email_config_path():
    return Path(os.environ['MONITY_EMAIL_CONFIG']).expanduser() if os.environ.get('MONITY_EMAIL_CONFIG') else data_path('config_email.json')


def load_email_config():
    try:
        config = json.loads(email_config_path().read_text(encoding='utf-8'))
        if not isinstance(config, dict):
            return {}
        return config
    except (OSError, ValueError):
        return {}


def valid_address(address):
    return isinstance(address, str) and len(address)<=254 and not any(ord(c)<33 or ord(c)==127 for c in address) and bool(re.fullmatch(r'[^\s@<>;,]+@[^\s@<>;,]+\.[^\s@<>;,]+', address))


class Mailer:
    def __init__(self, smtp_user, smtp_password, timeout=15):
        self.smtp_server = 'smtp.gmail.com'
        self.smtp_port = 587
        self.smtp_user = smtp_user
        self.smtp_password = smtp_password
        self.timeout = timeout
        self.delivery_state = 'not_sent'
        self.smtp_stage = 'połączenie'

    def _connect(self):
        if not valid_address(self.smtp_user) or not self.smtp_password:
            raise ValueError('Brak prawidłowego adresu nadawcy lub hasła aplikacji.')
        self.smtp_stage = 'połączenie'
        server = smtplib.SMTP(self.smtp_server, self.smtp_port, timeout=self.timeout)
        try:
            server.ehlo()
            self.smtp_stage = 'TLS'
            server.starttls(context=ssl.create_default_context())
            server.ehlo()
            self.smtp_stage = 'logowanie'
            server.login(self.smtp_user, self.smtp_password)
        except Exception:
            server.close()
            raise
        return server

    def _close(self, server):
        if server is not None:
            try:
                server.quit()
            except Exception:
                try:
                    server.close()
                except Exception:
                    pass

    def _smtp_details(self, exc):
        code = getattr(exc, 'smtp_code', None)
        response = getattr(exc, 'smtp_error', b'')
        if isinstance(exc, smtplib.SMTPRecipientsRefused) and exc.recipients:
            code, response = next(iter(exc.recipients.values()))
        # Only protocol codes are exposed: server text can contain private data.
        if isinstance(response, bytes):
            response = response.decode('ascii', errors='ignore')
        enhanced = re.search(r'(?<![0-9.])([245]\.[0-9]{1,3}\.[0-9]{1,3})(?![0-9.])', str(response))
        details = f' SMTP {code}' if isinstance(code, int) else ''
        if enhanced:
            details += f' / {enhanced.group(1)}'
        return details

    def _failure(self, exc):
        diagnostic = f'Etap: {self.smtp_stage}.{self._smtp_details(exc)}'
        if isinstance(exc, smtplib.SMTPAuthenticationError):
            return diagnostic + ' Gmail odrzucił logowanie. Sprawdź adres i hasło aplikacji; nie używaj zwykłego hasła konta.'
        if isinstance(exc, ssl.SSLError):
            return 'Nie udało się zweryfikować bezpiecznego połączenia TLS z Gmail.'
        if isinstance(exc, ValueError):
            return str(exc)
        if self.delivery_state == 'uncertain':
            return 'Nie można potwierdzić wyniku wysyłki po przerwaniu połączenia. Sprawdź folder Wysłane przed ponowną próbą.'
        if isinstance(exc, smtplib.SMTPServerDisconnected):
            return diagnostic + ' Połączenie zostało przerwane przed wysyłką. Nie oznacza to odrzucenia hasła.'
        if isinstance(exc, smtplib.SMTPNotSupportedError):
            return diagnostic + ' Serwer nie udostępnił wymaganej funkcji SMTP. Sprawdź połączenie TLS i ochronę poczty w antywirusie.'
        if isinstance(exc, smtplib.SMTPException):
            code = getattr(exc, 'smtp_code', None)
            if code in (421, 450, 451, 452, 454):
                return diagnostic + ' Tymczasowa odmowa SMTP; możliwy limit lub ograniczenie serwera. Nie ponawiaj seryjnie. Sprawdź kod odpowiedzi.'
            return diagnostic + ' Serwer odrzucił operację SMTP. Sprawdź kod odpowiedzi; sam komunikat nie określa przyczyny.'
        if getattr(exc, 'winerror', None) == 10013:
            return 'Środowisko blokuje połączenie sieciowe z Gmail (WinError 10013). Nie doszło do logowania ani wysyłki.'
        return 'Nie udało się połączyć z Gmail. Sprawdź dostęp do sieci i portu 587.'

    def sprawdz_polaczenie(self):
        """EHLO, STARTTLS i logowanie. Bez MAIL FROM / RCPT TO / DATA."""
        if os.environ.get('MONITY_MAIL_DRY_RUN') == '1':
            return True, 'SYMULACJA: połączenie i logowanie. Nie nawiązano połączenia z Gmail.'
        server = None
        try:
            server = self._connect()
            return True, 'Połączenie TLS i logowanie do Gmail działają. Nie wysłano wiadomości.'
        except Exception as exc:
            return False, self._failure(exc)
        finally:
            self._close(server)

    def wyslij_test(self, adres_odbiorcy):
        return self.wyslij_wiadomosc(adres_odbiorcy, '[Monity] Wiadomość testowa',
            'To pojedyncza wiadomość testowa aplikacji Monity.\n'
            'Nie zawiera danych klientów ani informacji o składkach.\n'
            'Odbiór tej wiadomości potwierdza dostarczenie testu.')

    def wyslij_wiadomosc(self, adres_odbiorcy, temat, tresc, is_html=False, message_id=None):
        self.delivery_state = 'not_sent'
        if not valid_address(adres_odbiorcy):
            return False, 'Podaj jeden prawidłowy adres odbiorcy.'
        if not temat.strip() or '\n' in temat or '\r' in temat:
            return False, 'Podaj poprawny temat wiadomości.'
        if os.environ.get('MONITY_MAIL_DRY_RUN') == '1':
            return True, 'SYMULACJA: wiadomość nie została wysłana do Gmail.'
        server = None
        try:
            msg = EmailMessage()
            msg['From'] = self.smtp_user
            msg['To'] = adres_odbiorcy
            msg['Subject'] = temat
            msg['Date'] = formatdate(localtime=True)
            msg['Message-ID'] = message_id or make_msgid()
            if is_html:
                msg.set_content('Wiadomość zawiera zestawienie HTML. Otwórz ją w programie obsługującym HTML.')
                msg.add_alternative(tresc, subtype='html')
            else:
                msg.set_content(tresc)
            server = self._connect()
            self.smtp_stage = 'wysyłanie wiadomości'
            self.delivery_state = 'uncertain'
            refused = server.send_message(msg, from_addr=self.smtp_user, to_addrs=[adres_odbiorcy])
            if refused:
                self.delivery_state = 'not_sent'
                return False, 'Gmail odrzucił odbiorcę. Nie przyjął wiadomości.'
            self.delivery_state = 'accepted'
            return True, 'Gmail przyjął wiadomość. Dostarczenie potwierdź w skrzynce odbiorcy.'
        except (smtplib.SMTPRecipientsRefused, smtplib.SMTPDataError, smtplib.SMTPSenderRefused) as exc:
            self.delivery_state = 'not_sent'
            return False, self._failure(exc)
        except Exception as exc:
            return False, self._failure(exc)
        finally:
            self._close(server)
