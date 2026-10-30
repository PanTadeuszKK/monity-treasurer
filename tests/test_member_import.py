import contextlib
import io
from datetime import date
from pathlib import Path
from unittest.mock import patch
import unittest
import pandas as pd
from sqlalchemy import text, create_engine
from sqlalchemy.orm import Session
import test_finance as fixtures
from models import Czlonek, Base, ImportCzlonkow, init_db
from member_import import preview_members, commit_members, COLUMNS
from opening_balance import opening_balances
from annual_fees import cadence_year

class MemberImportTests(unittest.TestCase):
    setUp=fixtures.FinanceTests.setUp
    tearDown=fixtures.FinanceTests.tearDown

    def file(self,rows=None,name='members.xlsx'):
        path=Path(self.tmp.name)/name
        pd.DataFrame(rows or [['Jan','Nowy','','jan.nowy@example.invalid','50','2026-06-15','Standard']],columns=COLUMNS).to_excel(path,index=False)
        return path

    def test_preview_no_writes_and_excel_debt_sign_is_converted(self):
        plan=preview_members(self.session,self.file())
        self.assertEqual(plan.rows[0].cents,-5000)
        self.assertEqual(self.session.query(Czlonek).count(),1)
        self.assertEqual(self.session.query(ImportCzlonkow).count(),0)
        self.assertEqual(commit_members(self.session,plan),1)
        member=self.session.query(Czlonek).filter_by(imie_nazwisko='Jan Nowy').one()
        self.assertEqual(member.bilans_otwarcia,-50)
        self.assertEqual(member.miesiac_dolaczenia,6)
        today=date.today();year=cadence_year(today.year,today.month)
        self.assertEqual(opening_balances(self.session,year)[member.id],-5000)

    def test_credit_and_zero_keep_correct_sign(self):
        plan=preview_members(self.session,self.file([
            ['Ala','Nowa','','','-25','15.06.2026','Premium'],
            ['Jan','Drugi','','','0','2026-06','Standard']]))
        self.assertEqual([r.cents for r in plan.rows],[2500,0])
        commit_members(self.session,plan)
        self.assertEqual(self.session.query(Czlonek).filter_by(imie_nazwisko='Ala Nowa').one().bilans_otwarcia,25)

    def test_repeat_file_and_overlapping_reexport_blocked(self):
        path=self.file();plan=preview_members(self.session,path);commit_members(self.session,plan)
        with self.assertRaises(ValueError): preview_members(self.session,path)
        with self.assertRaises(ValueError): preview_members(self.session,self.file(name='other.xlsx'))
        with self.assertRaises(ValueError): commit_members(self.session,plan)
        self.assertEqual(self.session.query(Czlonek).count(),2)

    def test_invalid_later_row_creates_nothing(self):
        rows=[['Jan','Nowy','','','0','2026-06-15','Standard'],['Ala','Nowa','','bad','0','2026-06-15','Standard']]
        with self.assertRaisesRegex(ValueError,'Wiersz 3'):
            preview_members(self.session,self.file(rows))
        self.assertEqual(self.session.query(Czlonek).count(),1)

    def test_numeric_bank_account_is_skipped_with_warning_without_corruption(self):
        plan=preview_members(self.session,self.file([['Jan','Nowy',61109010140000071219812874,'','0','2026-06-15','Standard']]))
        self.assertEqual(plan.rows[0].account,'')
        self.assertEqual(len(plan.warnings),1)
        self.assertIn('Wiersz 2',plan.warnings[0])
        commit_members(self.session,plan)
        self.assertEqual(self.session.query(Czlonek).count(),2)

    def test_duplicate_names_require_manual_review(self):
        rows=[['Jan','Nowy','','','0','2026-06-15','Standard']]*2
        with self.assertRaisesRegex(ValueError,'nazwisku'):
            preview_members(self.session,self.file(rows))

    def test_failure_rolls_back_every_member_and_ledger(self):
        plan=preview_members(self.session,self.file([
            ['Jan','Nowy','','','0','2026-06-15','Standard'],['Ala','Nowa','','','0','2026-06-15','Standard']]))
        with self.engine.begin() as connection:
            connection.execute(text("CREATE TRIGGER stop_import BEFORE INSERT ON czlonkowie WHEN NEW.imie_nazwisko='Ala Nowa' BEGIN SELECT RAISE(ABORT,'test'); END"))
        with self.assertRaises(Exception): commit_members(self.session,plan)
        self.assertEqual(self.session.query(Czlonek).count(),1)
        self.assertEqual(self.session.query(ImportCzlonkow).count(),0)

    def test_cli_default_is_read_only_and_write_creates_backup(self):
        from import_czlonkow import main
        path=self.file()
        database=Path(self.engine.url.database)
        output=io.StringIO()
        with contextlib.redirect_stdout(output),patch('sys.argv',['import_czlonkow.py',str(path),'--baza',str(database)]):
            self.assertEqual(main(),0)
        self.assertEqual(self.session.query(Czlonek).count(),1)
        with contextlib.redirect_stdout(output),patch('sys.argv',['import_czlonkow.py',str(path),'--baza',str(database),'--zapisz']):
            self.assertEqual(main(),0)
        self.assertEqual(self.session.query(Czlonek).count(),2)
        self.assertEqual(len(list(database.parent.glob(database.stem+'.przed-importem-czlonkow-*.db'))),1)

    def test_migration_7_backup_once(self):
        path=Path(self.tmp.name)/'v6.db'
        engine=create_engine('sqlite:///'+path.as_posix())
        Base.metadata.create_all(engine,tables=[t for t in Base.metadata.sorted_tables if t.name!='importy_czlonkow'])
        engine.dispose()
        for _ in range(2):
            engine=init_db(path)
            with Session(engine) as session:
                self.assertEqual(session.execute(text('SELECT MAX(wersja) FROM wersja_schematu')).scalar(),8)
            engine.dispose()
        self.assertEqual(len(list(path.parent.glob('v6.przed-migracja-7-*.db'))),1)

    def test_headers_after_blank_row_with_accents_spaces_and_case(self):
        path=Path(self.tmp.name)/"offset.xlsx"
        columns=[" IMIĘ ","nazwisko","Numer  Konta","MAIL","saldo","Data dolaczenia","Status"]
        pd.DataFrame([["Jan","Nowy","","","50","2026-06-15","Standard"]],columns=columns).to_excel(path,index=False,startrow=1)
        plan=preview_members(self.session,path)
        self.assertEqual(plan.rows[0].number,3)
        self.assertEqual(plan.rows[0].cents,-5000)

    def test_repeated_header_is_rejected_and_real_row_number_used(self):
        path=Path(self.tmp.name)/"duplicate-header.xlsx"
        pd.DataFrame([["Jan","Nowy","","","50","2026-06-15","Standard","Jan"]],columns=list(COLUMNS)+["Imię"]).to_excel(path,index=False,startrow=1)
        with self.assertRaisesRegex(ValueError,"powtarzają"):
            preview_members(self.session,path)
        pd.DataFrame([["Jan","Nowy","","bad","50","2026-06-15","Standard"]],columns=COLUMNS).to_excel(path,index=False,startrow=2)
        with self.assertRaisesRegex(ValueError,"Wiersz 4"):
            preview_members(self.session,path)

    def test_all_invalid_rows_reported_together(self):
        rows=[["Jan","Nowy","","bad","0","2026-06-15","Standard"],
            ["Ala","Nowa","","","0","2026-06-15",""]]
        with self.assertRaises(ValueError) as error:
            preview_members(self.session,self.file(rows))
        self.assertIn("Wiersz 2",str(error.exception))
        self.assertIn("Wiersz 3",str(error.exception))

    def test_invalid_optional_account_is_skipped_with_warning(self):
        plan=preview_members(self.session,self.file([["Jan","Nowy","123","","0","2026-06-15","Standard"]]))
        self.assertEqual(plan.rows[0].account,"")
        self.assertIn("niepoprawny rachunek",plan.warnings[0])
