"""Jawnie uruchamiane testy Tkintera. Nie czytają bazy ani konfiguracji użytkownika."""
import json
import os
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import customtkinter as ctk
from sqlalchemy.orm import Session

from annual_fees import cadence_year
from models import Czlonek, Status, Wplata, init_db
from logic import KalkulatorSkladek


class GuiSmokeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='monity-gui-test-')
        config=Path(self.tmp.name)/'config_email.json'
        config.write_text(json.dumps({'email':'sender@example.invalid','haslo':'fake'}),encoding='utf-8')
        self.env=patch.dict(os.environ,{'MONITY_DATA_DIR':self.tmp.name,'MONITY_GUI_TEST':'1',
            'MONITY_MAIL_DRY_RUN':'1','MONITY_EMAIL_CONFIG':str(config)})
        self.env.start()
        self.no_network=patch('mailer.smtplib.SMTP',side_effect=AssertionError('GUI test tried real network'))
        self.no_network.start()
        from main import MonityApp
        engine=init_db()
        now=datetime.now()
        self.year=cadence_year(now.year,now.month)
        with Session(engine) as session:
            member=Czlonek(numer_identyfikacyjny=12,imie_nazwisko='Jan Przykładowy',
                email='member@example.invalid',status=session.query(Status).filter_by(nazwa='Standard').one(),
                bilans_otwarcia=105,aktywny=True,rok_dolaczenia=self.year,miesiac_dolaczenia=6)
            session.add(member)
            session.flush()
            session.add(Wplata(czlonek_id=member.id,kwota=105,data_przelewu=datetime(self.year,8,15)))
            session.commit()
            for month in (6,7,8,9):
                self.assertTrue(KalkulatorSkladek(session).dodaj_naleznosc(self.year,month)[0])
        engine.dispose()
        self.app=MonityApp()
        self.errors=[]
        self.app.report_callback_exception=lambda *args:self.errors.append(args)
        self.app.update()

    def tearDown(self):
        self.app.on_closing()
        self.no_network.stop()
        self.env.stop()
        self.tmp.cleanup()
        self.assertEqual(self.errors,[])

    def windows(self):
        return [w for w in self.app.winfo_children() if isinstance(w,ctk.CTkToplevel)]

    def open(self,method):
        getattr(self.app,method)()
        self.app.update()
        self.assertEqual(len(self.windows()),1)
        return self.windows()[0]

    def close_windows(self):
        for window in self.windows():
            window.destroy()
        self.app.update()

    def test_all_navigation_views_and_minimum_size(self):
        for geometry in ['1220x790','1000x700']:
            self.app.geometry(geometry)
            self.app.update()
            for view in ['dashboard','members','payments','monits','stats','settings']:
                self.app.switch_view(view)
                self.app.update()
                self.assertGreater(len(self.app.main_container.winfo_children()),1)
                self.assertEqual(self.app.current_view,view)

    def test_all_readonly_and_form_windows_open(self):
        for method in ['open_member_add','open_dues_window','open_change_fees','open_change_columns',
                'open_list_all','open_list_premium','open_list_standard','open_list_archived',
                'open_payment_list','open_statuses_list','open_bank_accounts','open_yearly_stats',
                'open_send_reminder','open_email_settings','open_monthly_stats']:
            with self.subTest(method=method):
                window=self.open(method)
                self.assertTrue(window.winfo_viewable())
                self.close_windows()

    def test_selector_no_results_and_history_action(self):
        window=self.open('open_single_payment')
        self.assertEqual(len(window.tree.get_children()),1)
        window.entry_szukaj.insert(0,'nieistniejaca osoba')
        window.zaladuj_dane()
        self.assertEqual(len(window.tree.get_children()),0)
        self.assertIn('Brak wyników',window.lbl_count.cget('text'))
        window.resetuj_szukanie()
        row=window.tree.get_children()[0]
        window.tree.selection_set(row)
        window.potwierdz_wybor()
        self.app.update()
        self.assertEqual(len(self.windows()),1)
        self.assertIn('Dodaj składkę',self.windows()[0].title())

    def test_current_balance_native_charts(self):
        window=self.open('open_monthly_stats')
        window.generuj_raport()
        self.app.update()
        self.assertEqual(len(window.charts_frame.winfo_children()),2)
        self.assertEqual(window.aktualne_stats['Standard']['Debt'],1)
        window.generuj_raport()
        self.assertEqual(len(window.charts_frame.winfo_children()),2)

    def test_fee_approval_from_form_and_idempotence(self):
        window=self.open('open_change_fees')
        for status_id,entry in window.entry_dict.items():
            status=self.app.session.get(Status,status_id)
            entry.delete(0,'end')
            entry.insert(0,'40' if status.nazwa=='Standard' else '70')
        window.entry_date.delete(0,'end')
        window.entry_date.insert(0,datetime.now().date().isoformat())
        with patch('tkinter.messagebox.askyesno',return_value=True),patch('tkinter.messagebox.showinfo') as info:
            window.zapisz_zmiany()
            window.confirm()
            self.assertTrue(info.called)
        self.app.update()
        self.assertEqual(self.app.session.query(Czlonek).one().bilans_otwarcia,-55)

    def test_legacy_fee_approval_in_same_window_cancel_and_repeat(self):
        from models import HistoriaNaliczen, NaliczenieCzlonka, NaliczenieMiesiaca, StatusNaliczenia, KorektaStawki
        session = self.app.session
        session.query(StatusNaliczenia).delete()
        session.query(NaliczenieCzlonka).delete()
        session.query(NaliczenieMiesiaca).delete()
        session.add_all(HistoriaNaliczen(rok=self.year, miesiac=m) for m in (6,7,8,9))
        session.commit()  # Pozostaw saldo -35, symulując stare naliczenia.
        window = self.open('open_change_fees')
        self.assertEqual(len(window.previous_entries), 2)
        self.assertEqual(len(window.original_status_entries), 1)
        for status_id, entry in window.entry_dict.items():
            entry.delete(0, 'end')
            entry.insert(0, '40' if session.get(Status, status_id).nazwa == 'Standard' else '70')
        with patch('tkinter.messagebox.showerror') as error:
            window.zapisz_zmiany()
            self.assertTrue(error.called)
        for choice in window.original_status_entries.values():
            self.assertEqual(choice.get(), 'Wybierz status')
            choice.set('Standard')
        with patch('tkinter.messagebox.askyesno', return_value=False):
            window.zapisz_zmiany()
        self.assertEqual(session.query(NaliczenieCzlonka).count(), 0)
        self.assertEqual(session.query(Czlonek).one().bilans_otwarcia, -35)
        with patch('tkinter.messagebox.askyesno', return_value=True), patch('tkinter.messagebox.showinfo'), patch('tkinter.messagebox.showerror') as error:
            window.zapisz_zmiany()
            window.confirm()
            error.assert_not_called()
        self.app.update()
        self.assertEqual(session.query(Czlonek).one().bilans_otwarcia, -55)
        self.assertEqual(session.query(KorektaStawki).count(), 4)
        window = self.open('open_change_fees')
        self.assertEqual(window.previous_entries, {})
        self.assertEqual(window.original_status_entries, {})
        window.zapisz_zmiany()
        self.assertTrue(window.preview[-1].unchanged)
        self.assertEqual(window.btn_confirm.cget('state'), 'disabled')
        self.assertEqual(session.query(KorektaStawki).count(), 4)

    def test_status_effective_june_edit_and_october_approval(self):
        from frames.edit_member_frame import EditMemberWindow
        member = self.app.session.query(Czlonek).one()
        window = EditMemberWindow(self.app, self.app.session, member)
        self.app.update()
        window.dropdown_status.set('Premium')
        window.entry_status_month.delete(0, 'end')
        window.entry_status_month.insert(0, '6')
        window.entry_status_year.delete(0, 'end')
        window.entry_status_year.insert(0, str(self.year))
        with patch('tkinter.messagebox.showinfo'), patch('tkinter.messagebox.showerror') as error:
            window.zapisz_zmiany()
            error.assert_not_called()
        self.app.update()
        self.assertEqual(member.status.nazwa, 'Premium')
        self.assertEqual(member.bilans_otwarcia, -155)
        window = self.open('open_change_fees')
        for status_id, entry in window.entry_dict.items():
            entry.delete(0, 'end')
            entry.insert(0, '40' if self.app.session.get(Status, status_id).nazwa == 'Standard' else '80')
        with patch('tkinter.messagebox.askyesno', return_value=True), patch('tkinter.messagebox.showinfo'), patch('tkinter.messagebox.showerror') as error:
            window.zapisz_zmiany()
            window.confirm()
            error.assert_not_called()
        self.app.update()
        self.assertEqual(member.bilans_otwarcia, -215)

    def test_mail_diagnostics_simulated_and_ui_responsive(self):
        window=self.open('open_email_settings')
        window.check_connection()
        deadline=time.monotonic()+2
        while window.busy and time.monotonic()<deadline:
            self.app.update()
            time.sleep(0.01)
        self.assertFalse(window.busy)
        self.assertIn('SYMULACJA',window.lbl_status.cget('text'))
        with patch('tkinter.messagebox.askyesno',return_value=True):
            window.send_test()
        deadline=time.monotonic()+2
        while window.busy and time.monotonic()<deadline:
            self.app.update()
            time.sleep(0.01)
        self.assertIn('SYMULACJA',window.lbl_status.cget('text'))
        self.assertEqual(window.btn_send.cget('state'),'disabled')

    def test_reminder_preview_and_cancel_send(self):
        window=self.open('open_send_reminder')
        window.entry_name.insert(0,'Przykładowy')
        window.szukaj_czlonka()
        self.assertIn('Jan Przykładowy',window.lbl_imie.cget('text'))
        self.assertIn('[TABELA_WPLAT]',window.txt_tresc.get('1.0','end'))
        with patch('tkinter.messagebox.askyesno',return_value=False) as confirm:
            window.wyslij_monit()
            self.assertTrue(confirm.called)
        self.assertEqual(window.btn_wyslij.cget('state'),'normal')

    def test_new_member_status_is_selected_by_id_not_amount_label(self):
        window=self.open('open_member_add')
        window.entry_name.insert(0,'Druga Przykładowa Osoba')
        window.status_var.set('Standard')
        window.entry_bilans.insert(0,'0')
        with patch('tkinter.messagebox.showinfo'):
            window.save_member()
        self.app.update()
        member=self.app.session.query(Czlonek).filter_by(imie_nazwisko='Druga Przykładowa Osoba').one()
        self.assertEqual(member.status.nazwa,'Standard')
        self.assertEqual(self.app.session.query(Czlonek).count(),2)

    def test_archive_and_later_manual_payment(self):
        selector=self.open('open_member_delete')
        selector.tree.selection_set(selector.tree.get_children()[0])
        selector.potwierdz_wybor()
        self.app.update()
        archive=self.windows()[0]
        with patch('tkinter.messagebox.askyesno',return_value=True),patch('tkinter.messagebox.showinfo'):
            archive.usun_czlonka()
        self.app.update()
        member=self.app.session.query(Czlonek).one()
        self.assertFalse(member.aktywny)
        balance=member.bilans_otwarcia
        selector=self.open('open_single_payment')
        self.assertEqual(len(selector.tree.get_children()),1)
        selector.tree.selection_set(selector.tree.get_children()[0])
        selector.potwierdz_wybor()
        self.app.update()
        payment=self.windows()[0]
        payment.entry_kwota.insert(0,'35,00')
        with patch('tkinter.messagebox.askyesno',return_value=True),patch('tkinter.messagebox.showinfo'):
            payment.process_payment()
        self.assertEqual(member.bilans_otwarcia,balance+35)
        self.assertEqual(self.app.session.query(Wplata).count(),2)


if __name__=='__main__':
    unittest.main()
