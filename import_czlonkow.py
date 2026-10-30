"""Import klientów XLSX. Domyślnie tylko walidacja, bez zapisu."""
import argparse
from pathlib import Path
from uuid import uuid4
import sqlite3
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from models import init_db
from paths import data_path
from backup import backup_database
from member_import import preview_members, commit_members


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('plik',type=Path)
    parser.add_argument('--baza',type=Path,default=data_path('monity.db'))
    parser.add_argument('--zapisz',action='store_true',help='Zrób backup i zapisz wszystkie kartoteki; zamknij wcześniej aplikację.')
    args=parser.parse_args()
    path=args.baza.expanduser().resolve()
    if not path.is_file():
        parser.error('Baza nie istnieje. Najpierw przygotuj bazę w aplikacji.')
    # Podgląd nie tworzy bazy, tabel ani migracji.
    engine=create_engine('sqlite://',creator=lambda:sqlite3.connect(path.as_uri()+'?mode=ro',uri=True))
    try:
        with Session(engine) as session:
            plan=preview_members(session,args.plik)
        engine.dispose()
        for warning in plan.warnings:
            print('UWAGA: '+warning)
        print(f'Walidacja OK: {len(plan.rows)} klientów. Excel: minus w Saldo = nadpłata, plus = zaległość.')
        if not args.zapisz:
            print('Nic nie zapisano. Aby zaimportować, zamknij aplikację i powtórz polecenie z --zapisz.')
            return 0
        backup=backup_database(path,path.with_name(path.stem+'.przed-importem-czlonkow-'+uuid4().hex+'.db'))
        engine=init_db(path)
        with Session(engine) as session:
            count=commit_members(session,plan)
        print(f'Zapisano {count} kartotek. Kopia bazy: {backup.name}')
        return 0
    except ValueError as exc:
        print(f'Nie zaimportowano: {exc}')
        return 1
    except Exception:
        print('Import nie powiódł się. Nie zapisano części kartotek. Sprawdź format pliku i dostęp do bazy.')
        return 1
    finally:
        engine.dispose()


if __name__=='__main__':
    raise SystemExit(main())
