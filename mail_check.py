"""Diagnostyka istniejącej konfiguracji; domyślnie bez wysyłki."""
import argparse
from mailer import Mailer, load_email_config


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--send-to-self',action='store_true',help='Wyślij jedną wiadomość testową na skonfigurowany adres nadawcy')
    args=parser.parse_args()
    config=load_email_config()
    mailer=Mailer(config.get('email',''),config.get('haslo',''))
    success,info=(mailer.wyslij_test(config.get('email','')) if args.send_to_self else mailer.sprawdz_polaczenie())
    print(('OK: ' if success else 'BŁĄD: ')+info)
    return 0 if success else 1


if __name__=='__main__':
    raise SystemExit(main())
