"""Pełne przebiegi GUI na fikcyjnej bazie, bez połączeń sieciowych."""
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from decimal import Decimal
import customtkinter as ctk
from sqlalchemy.orm import Session
import gui_smoke as fixtures
from models import Czlonek, WysylkaEmail, Wplata
from ui import fit_window


class SystemGuiTests(unittest.TestCase):
    setUp=fixtures.GuiSmokeTests.setUp
    tearDown=fixtures.GuiSmokeTests.tearDown
    windows=fixtures.GuiSmokeTests.windows
    def open(self,method):
        window=fixtures.GuiSmokeTests.open(self,method)
        deadline=time.monotonic()+.22
        while time.monotonic()<deadline:
            self.app.update()
            time.sleep(.01)
        return window
    close_windows=fixtures.GuiSmokeTests.close_windows

    def pump_until(self,predicate,timeout=8):
        deadline=time.monotonic()+timeout
        while not predicate() and time.monotonic()<deadline:
            self.app.update()
            time.sleep(.01)
        self.assertTrue(predicate())

    def test_bulk_preview_cancel_send_then_history_and_duplicate_block(self):
        from mail_service import send_campaign
        def fast(*args,**kwargs):
            kwargs['interval']=0
            return send_campaign(*args,**kwargs)
        window=self.open('open_bulk_mail')
        window.preview()
        self.app.update()
        self.assertEqual(len(window.tree.get_children()),1)
        self.assertIn('member@example.invalid',window.message.get('1.0','end'))
        with patch('tkinter.messagebox.askyesno',return_value=False):
            window.send()
        self.assertEqual(self.app.session.query(WysylkaEmail).count(),0)
        with patch('tkinter.messagebox.askyesno',return_value=True), patch('frames.bulk_mail_frame.send_campaign',side_effect=fast):
            window.send()
            self.pump_until(lambda:not window.busy)
        self.assertEqual(self.app.session.query(WysylkaEmail).one().stan,'accepted')
        window.refresh_history()
        self.assertEqual(len(window.history.get_children()),1)
        with patch('tkinter.messagebox.askyesno',return_value=True),patch('tkinter.messagebox.showerror') as error:
            window.send()
            self.assertTrue(error.called)
        self.assertEqual(self.app.session.query(WysylkaEmail).count(),1)

    def test_import_xlsx_preview_commit_and_manual_queue(self):
        import pandas as pd
        path=Path(self.tmp.name)/'synthetic.xlsx'
        pd.DataFrame([['2026-06-15','35','A!12','PLN'],['2026-06-16','40','Brak ID','PLN']],
            columns=['Data operacji','Kwota','Opis transakcji','Waluta']).to_excel(path,index=False)
        window=self.open('import_excel')
        with patch('tkinter.filedialog.askopenfilename',return_value=str(path)):
            window.process_file()
        self.assertEqual(len(window.tree.get_children()),2)
        self.assertEqual(window.included,{2})
        with patch('tkinter.messagebox.askyesno',return_value=True),patch('tkinter.messagebox.showinfo'),patch('tkinter.messagebox.showerror') as error:
            window.commit()
            window.confirmation.btn_save.invoke()
            error.assert_not_called()
        self.assertEqual(self.app.session.query(Czlonek).one().bilans_otwarcia,0)
        self.assertEqual(len(window.pending),1)
        key=window.tree.get_children()[0]
        window.tree.selection_set(key)
        window.assign()
        window.choice.editor.set(next(iter(window.members.values())))
        window.choice.editor.event_generate('<<ComboboxSelected>>')
        with patch('tkinter.messagebox.askyesno',return_value=True),patch('tkinter.messagebox.showinfo'),patch('tkinter.messagebox.showerror') as error:
            window.commit()
            window.confirmation.btn_save.invoke()
            error.assert_not_called()
        self.assertEqual(self.app.session.query(Czlonek).one().bilans_otwarcia,40)
        self.assertEqual(self.app.session.query(Wplata).count(),3)
        self.assertEqual(len(window.pending),0)

    def test_configuration_saved_in_isolated_data_directory(self):
        import json
        window=self.open('open_change_columns')
        window.entries['bank_id'].insert(0,'ID bankowe')
        with patch('tkinter.messagebox.showinfo'):
            window.zapisz_konfiguracje()
        config=json.loads((Path(self.tmp.name)/'config_kolumn.json').read_text(encoding='utf-8'))
        self.assertEqual(config['kol_id'],'ID bankowe')

    def test_yearly_and_current_balance_exports(self):
        from openpyxl import load_workbook
        for method,action in [('open_yearly_stats','eksportuj_raport_roczny'),('open_monthly_stats','export_to_excel')]:
            window=self.open(method)
            if method=='open_monthly_stats': window.generuj_raport()
            path=Path(self.tmp.name)/(method+'.xlsx')
            with patch('tkinter.filedialog.asksaveasfilename',return_value=str(path)),patch('tkinter.messagebox.showinfo'),patch('tkinter.messagebox.showerror') as error:
                getattr(window,action)()
                error.assert_not_called()
            self.assertTrue(path.exists())
            workbook=load_workbook(path)
            self.assertGreater(len(workbook.sheetnames),1)
            workbook.close()
            self.close_windows()

    def test_lists_search_and_archived_views(self):
        window=self.open('open_list_all')
        window.entry_szukaj.insert(0,'Jan')
        window.zaladuj_dane()
        self.assertEqual(len(window.tree.get_children()),1)
        self.close_windows()
        window=self.open('open_payment_list')
        window.dropdown_kryterium.set('Imię i Nazwisko')
        window.entry_szukaj.insert(0,'Przykladowy Jan')
        window.zaladuj_dane()
        self.assertEqual(len(window.tree.get_children()),1)
        self.close_windows()
        window=self.open('open_list_archived')
        self.assertEqual(len(window.tree.get_children()),0)

    def test_500_members_bulk_and_list_remain_usable(self):
        from models import Status
        status_id=self.app.session.query(Status).filter_by(nazwa='Standard').one().id
        self.app.session.add_all(Czlonek(numer_identyfikacyjny=100+i,imie_nazwisko=f'Osoba {i:03}',
            email=f'member{i}@example.invalid',status_id=status_id,aktywny=True,bilans_otwarcia=-35,
            rok_dolaczenia=self.year,miesiac_dolaczenia=6) for i in range(499))
        self.app.session.commit()
        window=self.open('open_bulk_mail')
        window.preview()
        self.app.update()
        self.assertEqual(len(window.tree.get_children()),500)
        self.assertTrue(window.btn_send.winfo_viewable())
        self.close_windows()
        window=self.open('open_list_all')
        self.assertEqual(len(window.tree.get_children()),500)
        window.entry_szukaj.insert(0,'Osoba 498')
        window.zaladuj_dane()
        self.assertEqual(len(window.tree.get_children()),1)

    def test_primary_actions_visible_at_100_125_150_percent_scaling(self):
        targets=[('open_member_add','btn_save'),('open_dues_window','btn_akcja'),
            ('open_email_settings','btn_send'),('open_send_reminder','btn_wyslij'),
            ('open_yearly_stats','btn_export'),('open_bulk_mail','btn_send'),('import_excel','btn_commit')]
        try:
            for scale in (1.0,1.25,1.5):
                ctk.set_widget_scaling(scale)
                ctk.set_window_scaling(scale)
                fit_window(self.app)
                self.app.update()
                for method,attribute in targets:
                    window=self.open(method)
                    self.app.update()
                    button=getattr(window,attribute)
                    self.assertTrue(button.winfo_viewable(),(scale,method,'not visible'))
                    self.assertGreaterEqual(button.winfo_rooty(),window.winfo_rooty(),(scale,method,'above'))
                    self.assertLessEqual(button.winfo_rooty()+button.winfo_height(),window.winfo_rooty()+window.winfo_height(),(scale,method,'below'))
                    self.assertLessEqual(window.winfo_width(),window.winfo_screenwidth(),(scale,method,'wide'))
                    self.assertLessEqual(window.winfo_height()+60,window.winfo_screenheight(),(scale,method,'tall'))
                    self.close_windows()
        finally:
            ctk.set_widget_scaling(1.0)
            ctk.set_window_scaling(1.0)

    def test_escape_closes_window_and_financial_delete_is_blocked(self):
        window=self.open('open_email_settings')
        window.event_generate('<Escape>')
        self.app.update()
        self.close_windows()
        from frames.delete_payment_frame import DeletePaymentWindow
        member=self.app.session.query(Czlonek).one()
        window=DeletePaymentWindow(self.app,self.app.session,member)
        self.app.update()
        self.assertEqual(self.app.session.query(Wplata).count(),1)
        window.destroy()
        self.app.update()

    def test_navigation_buttons_fit_at_large_scaling(self):
        try:
            ctk.set_widget_scaling(1.5)
            ctk.set_window_scaling(1.5)
            fit_window(self.app)
            self.app.update()
            for button in self.app.menu_buttons.values():
                self.assertGreaterEqual(button.winfo_rooty(),self.app.winfo_rooty())
                self.assertLessEqual(button.winfo_rooty()+button.winfo_height(),self.app.winfo_rooty()+self.app.winfo_height())
        finally:
            ctk.set_widget_scaling(1.0)
            ctk.set_window_scaling(1.0)

    def test_startup_and_resize_reflow_without_switching_tabs(self):
        from ui import wrap_labels
        self.assertGreater(self.app.winfo_width(),640)
        self.assertGreater(self.app.winfo_height(),400)
        original_view=self.app.current_view
        def labels(widget):
            result=[]
            for child in widget.winfo_children():
                if isinstance(child,ctk.CTkLabel): result.append(child)
                result.extend(labels(child))
            return result
        widgets=labels(self.app.main_container)
        subtitle=next(w for w in widgets if w.cget("text")=="Najczęściej używane operacje w jednym miejscu.")
        def settle():
            deadline=time.monotonic()+.35
            while time.monotonic()<deadline:
                self.app.update()
                time.sleep(.01)
        self.app.geometry("680x500")
        settle()
        narrow=subtitle.cget("wraplength")
        self.app.geometry("1050x700")
        settle()
        wide=subtitle.cget("wraplength")
        self.assertGreater(wide,narrow)
        self.assertEqual(self.app.current_view,original_view)
        self.assertTrue(subtitle.winfo_exists())
        wrap_labels(self.app)
        self.assertEqual(subtitle.cget("wraplength"),wide)

    def test_opening_balance_edit_and_reminder_content(self):
        from frames.edit_member_frame import EditMemberWindow
        from opening_balance import opening_balances
        member=self.app.session.query(Czlonek).one()
        before=member.bilans_otwarcia
        window=EditMemberWindow(self.app,self.app.session,member)
        self.app.update()
        window.entry_opening.insert(0,"-50")
        with patch("tkinter.messagebox.showinfo"),patch("tkinter.messagebox.showerror") as error:
            window.zapisz_zmiany()
            error.assert_not_called()
        self.app.update()
        self.assertEqual(member.bilans_otwarcia,before)
        self.assertEqual(opening_balances(self.app.session,self.year)[member.id],-5000)
        window=self.open("open_send_reminder")
        window.entry_name.insert(0,"Przykładowy")
        window.szukaj_czlonka()
        self.assertIn("Zaległość przeniesiona",window.txt_tresc.get("1.0","end"))
        self.assertIn("50.00 PLN",window.txt_tresc.get("1.0","end"))
        self.assertIn("Do zapłaty na dziś",window.txt_tresc.get("1.0","end"))

    def test_reminder_opening_50_payment_100_credit_50_without_duplicate_summary(self):
        from opening_balance import record_opening
        import html
        member=self.app.session.query(Czlonek).one()
        member.bilans_otwarcia=50
        record_opening(self.app.session,member.id,self.year,"-50","Potwierdzenie testowe")
        self.app.session.commit()
        window=self.open("open_send_reminder")
        window.entry_name.insert(0,"Przykładowy")
        window.szukaj_czlonka()
        body=html.escape(window.txt_tresc.get("1.0","end")).replace("[TABELA_WPLAT]",window.tabela_html)
        self.assertEqual(body.count(f"Zaległość przeniesiona na 01.06.{self.year}: 50.00 PLN."),1)
        self.assertEqual(body.count("Do zapłaty na dziś:"),1)
        self.assertEqual(body.count("Nadpłata na dziś:"),1)
        self.assertIn("Nadpłata na dziś: 50.00 PLN",body)
        self.assertNotIn("nieuzupełnione",body)

    def test_duplicate_names_require_explicit_choice_for_reminder(self):
        member=self.app.session.query(Czlonek).one()
        second=Czlonek(numer_identyfikacyjny=99,imie_nazwisko=member.imie_nazwisko,
            email="second@example.invalid",status_id=member.status_id,aktywny=False,
            bilans_otwarcia=-10,rok_dolaczenia=self.year,miesiac_dolaczenia=6)
        self.app.session.add(second);self.app.session.commit()
        window=self.open("open_send_reminder")
        window.entry_name.insert(0,"przykladowy jan")
        window.szukaj_czlonka()
        self.app.update()
        self.assertIsNone(window.czlonek)
        self.assertEqual(window.btn_wyslij.cget("state"),"disabled")
        selector=next(w for w in window.winfo_children() if isinstance(w,ctk.CTkToplevel))
        self.assertEqual(len(selector.tree.get_children()),2)
        chosen=next(key for key in selector.tree.get_children() if int(selector.tree.item(key,"values")[0])==second.id)
        selector.tree.selection_set(chosen);selector.potwierdz_wybor()
        self.assertEqual(window.czlonek.id,second.id)
        self.assertIn("second@example.invalid",window.lbl_email.cget("text"))

    def test_import_details_show_sender_after_title_in_preview_and_pending(self):
        import pandas as pd
        path=Path(self.tmp.name)/"sender.xlsx"
        pd.DataFrame([["2026-06-15","35","Składka","PLN","Jan Przykładowy"],
            ["2026-06-16","10","A!12","PLN",""]],
            columns=["Data operacji","Kwota","Opis transakcji","Waluta","Nazwa nadawcy"]).to_excel(path,index=False)
        window=self.open("import_excel")
        with patch("tkinter.filedialog.askopenfilename",return_value=str(path)):
            window.process_file()
        window.tree.selection_set("2");window.show_details()
        self.assertIn("Tytuł: Składka\nNazwa nadawcy: Jan Przykładowy",window.details.get("1.0","end"))
        window.tree.selection_set("3")
        with patch("tkinter.messagebox.askyesno",return_value=True),patch("tkinter.messagebox.showinfo"):
            window.commit()
            window.confirmation.btn_save.invoke()
        window.tree.selection_set(window.tree.get_children()[0]);window.show_details()
        self.assertIn("Nazwa nadawcy: Jan Przykładowy",window.details.get("1.0","end"))

    def test_financial_history_searches_name_and_keeps_selected_identity(self):
        from frames.member_stats_frame import MemberStatsWindow
        member=self.app.session.query(Czlonek).one()
        window=MemberStatsWindow(self.app,self.app.session)
        window.entry_name.insert(0,"przykladowy JAN")
        window.szukaj_czlonka()
        self.assertEqual(window.czlonek.id,member.id)
        self.assertGreater(len(window.scroll_wplaty.winfo_children()),0)
        window.destroy()

    def test_bank_accounts_default_name_search(self):
        from models import KontoBankowe
        member=self.app.session.query(Czlonek).one()
        self.app.session.add(KontoBankowe(numer_konta="61109010140000071219812874",czlonek_id=member.id))
        self.app.session.commit()
        window=self.open("open_bank_accounts")
        self.assertEqual(window.dropdown_kryterium.get(),"Imię i Nazwisko")
        window.entry_szukaj.insert(0,"przykladowy jan")
        window.zaladuj_dane()
        self.assertEqual(len(window.tree.get_children()),1)
        self.assertNotIn("ID A!",window.kryteria)
