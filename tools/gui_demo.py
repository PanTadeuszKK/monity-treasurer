"""Ręczny podgląd GUI na jednej fikcyjnej kartotece; nigdy na bazie roboczej."""
import json
import os
import sys
import tempfile
import argparse
from datetime import datetime
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--view', choices=['dashboard', 'rates', 'import', 'ledger'], default='dashboard')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='monity-gui-') as directory:
        os.environ['MONITY_DATA_DIR']=directory
        os.environ['MONITY_GUI_TEST']='1'
        os.environ['MONITY_MAIL_DRY_RUN']='1'
        config=Path(directory)/'config_email.json'
        config.write_text(json.dumps({'email':'demo@example.invalid','haslo':'fikcyjne-haslo'}),encoding='utf-8')
        os.environ['MONITY_EMAIL_CONFIG']=str(config)
        from models import init_db, Czlonek, Status, Wplata
        from sqlalchemy.orm import Session
        from logic import KalkulatorSkladek
        from annual_fees import cadence_year
        engine=init_db()
        today=datetime.now()
        year=cadence_year(today.year,today.month)
        with Session(engine) as session:
            status=session.query(Status).filter_by(nazwa='Standard').one()
            member=Czlonek(numer_identyfikacyjny=12,imie_nazwisko='Jan Przykładowy',
                email='czlonek@example.invalid',status=status,bilans_otwarcia=105,
                aktywny=True,rok_dolaczenia=year,miesiac_dolaczenia=6)
            session.add(member)
            session.flush()
            session.add(Wplata(czlonek_id=member.id,kwota=105,data_przelewu=datetime(year,8,15),
                tytul_oryginalny='Wpłata demonstracyjna',metoda_dopasowania='Test',czy_potwierdzona=True))
            session.commit()
            calculator=KalkulatorSkladek(session)
            for month in (6,7,8,9):
                calculator.dodaj_naleznosc(year,month)
        engine.dispose()
        from main import MonityApp
        app=MonityApp()
        if args.view == 'rates':
            from frames.change_fees_frame import ChangeFeesWindow
            window = ChangeFeesWindow(app, app.session)
            window.title('TEST — Stawki kadencji')
        elif args.view == 'ledger':
            from frames.member_stats_frame import MemberStatsWindow
            window = MemberStatsWindow(app, app.session, app.session.query(Czlonek).one())
            window.title('TEST — Karta finansowa')
        elif args.view == 'import':
            from frames.import_frame import ImportWindow
            from unittest.mock import patch
            import pandas as pd
            path = Path(directory) / 'synthetic.xlsx'
            pd.DataFrame([
                [f'{year}-06-15', '35', 'Składka czerwiec A!12', 'PLN', 'Jan Przykładowy'],
                [f'{year}-07-15', '70', 'Składki lipiec i sierpień A!12', 'PLN', 'Jan Przykładowy'],
                [f'{year}-09-15', '35', 'Przelew bez identyfikatora', 'PLN', 'Osoba Testowa']],
                columns=['Data operacji', 'Kwota', 'Opis transakcji', 'Waluta', 'Nazwa nadawcy']).to_excel(path, index=False)
            window = ImportWindow(app, app.session)
            window.title('TEST — Przypisania wpłat')
            with patch('tkinter.filedialog.askopenfilename', return_value=str(path)):
                window.process_file()
        app.mainloop()


if __name__=='__main__':
    main()
