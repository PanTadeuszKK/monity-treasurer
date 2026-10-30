import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox
from decimal import Decimal
import os

from models import Czlonek, Wplata, PozycjaWyciagu, WysylkaEmail
from annual_fees import cadence_year, latest_approval
from ui import (configure_theme, cancel_callbacks, fit_window, wrap_labels, format_pln,
                INK, MUTED, GREEN, RED, AMBER_BG, AMBER_INK, BORDER)
from frames.email_settings_frame import EmailSettingsWindow
from frames.bulk_mail_frame import BulkMailWindow
from sqlalchemy.orm import sessionmaker
from datetime import datetime

from models import init_db
from backup import automatic_backup, backup_settings
from frames.handover_frame import HandoverWindow
from paths import data_path, backup_dir
from logic import KalkulatorSkladek

from frames.members_frame import AddMemberWindow
from frames.import_frame import ImportWindow
from frames.single_payment_frame import SinglePaymentWindow
from frames.delete_payment_frame import DeletePaymentWindow
from frames.delete_member_frame import DeleteMemberWindow
from frames.edit_member_frame import EditMemberWindow
from frames.member_stats_frame import MemberStatsWindow
from frames.monthly_stats_frame import MonthlyStatsWindow
from frames.yearly_stats_frame import YearlyStatsWindow
from frames.change_fees_frame import ChangeFeesWindow
from frames.change_columns_frame import ChangeColumnsWindow
from frames.list_members_frame import MembersListWindow
from frames.list_payments_frame import PaymentsListWindow
from frames.list_statuses_frame import StatusListWindow
from frames.list_bank_accounts_frame import BankAccountsListWindow
from frames.send_reminder_frame import SendReminderWindow
from frames.member_selector import MemberSelectorWindow
from frames.dues_window import DuesWindow

configure_theme()

MONTHS = {1: 'Styczeń', 2: 'Luty', 3: 'Marzec', 4: 'Kwiecień', 5: 'Maj', 6: 'Czerwiec', 7: 'Lipiec',
          8: 'Sierpień', 9: 'Wrzesień', 10: 'Październik', 11: 'Listopad', 12: 'Grudzień'}
VIEWS = [('dashboard', 'Przegląd'), ('members', 'Klienci'), ('payments', 'Wpłaty i składki'),
         ('monits', 'Wiadomości'), ('stats', 'Raporty'), ('settings', 'Ustawienia')]


class MonityApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.withdraw()
        self.test_mode = os.environ.get('MONITY_GUI_TEST') == '1'
        self.title('Monity — panel administratora' + (' [TEST]' if self.test_mode else ''))
        self.geometry('1220x790')
        self.minsize(640, 480)
        self.COLOR_SIDEBAR = '#142C47'
        self.COLOR_BG = '#F3F6FA'
        self.COLOR_CARD_BG = '#FFFFFF'
        self.COLOR_ACCENT = GREEN
        self.engine = init_db()
        self.Session = sessionmaker(bind=self.engine)
        self.session = self.Session()
        self.kalkulator = KalkulatorSkladek(self.session)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.setup_sidebar()
        self.main_container = ctk.CTkScrollableFrame(self, corner_radius=0, fg_color=self.COLOR_BG)
        self.main_container.grid(row=0, column=1, sticky='nsew')
        self.protocol('WM_DELETE_WINDOW', self.on_closing)
        self.switch_view('dashboard')
        self.bind('<Configure>', self._resize_layout, add='+')
        self.main_container.bind('<Configure>', self._schedule_text_layout, add='+')
        self.after_idle(self._show_initial_window)

    def setup_sidebar(self):
        self.sidebar = ctk.CTkFrame(self, width=228, corner_radius=0, fg_color=self.COLOR_SIDEBAR)
        self.sidebar.grid(row=0, column=0, sticky='nsew')
        self.sidebar.grid_propagate(False)
        self.sidebar.grid_columnconfigure(0, weight=1)
        self.sidebar.grid_rowconfigure(8, weight=1)
        brand = ctk.CTkFrame(self.sidebar, fg_color='transparent')
        self.sidebar_brand = brand
        brand.grid(row=0, column=0, padx=24, pady=(20, 20), sticky='ew')
        ctk.CTkLabel(brand, text='M', width=42, height=42, corner_radius=12,
                     fg_color='#2C7E68', text_color='white', font=('Segoe UI', 25, 'bold')).pack(side='left')
        ctk.CTkLabel(brand, text='monity', text_color='white', font=('Segoe UI', 27, 'bold')).pack(side='left', padx=12)
        ctk.CTkLabel(self.sidebar, text='PANEL ROZLICZEŃ', font=('Segoe UI', 10, 'bold'), text_color='#8FA8C3').grid(row=1, column=0, sticky='w', padx=26, pady=(0, 12))
        self.menu_buttons = {}
        for index, (key, label) in enumerate(VIEWS, start=1):
            button = ctk.CTkButton(self.sidebar, text=label, anchor='w', height=40,
                corner_radius=9, fg_color='transparent', hover_color='#25415F',
                text_color='#C7D5E5', font=('Segoe UI', 14),
                command=lambda view=key: self.switch_view(view))
            button.grid(row=index+1, column=0, padx=16, pady=4, sticky='ew')
            self.menu_buttons[key] = button
            self.bind(f'<Control-Key-{index}>', lambda event, view=key: self.switch_view(view))
        ctk.CTkLabel(self.sidebar, text='Ctrl+1…6 — szybkie przejście', text_color='#6F89A6',
                     font=('Segoe UI', 10)).grid(row=8, column=0, sticky='nw', padx=26, pady=(8, 0))
        today = datetime.now()
        year = cadence_year(today.year, today.month)
        ctk.CTkLabel(self.sidebar, text=f'KADENCJA {year}/{year+1}', text_color='#B8CADD', font=('Segoe UI',11,'bold')).grid(row=9,column=0,sticky='w',padx=26,pady=(10,4))
        ctk.CTkLabel(self.sidebar, text='Dane na tym komputerze', text_color='#8FA8C3', font=('Segoe UI',11)).grid(row=10,column=0,sticky='w',padx=26,pady=(0,25))

    def _show_initial_window(self):
        # Native DPI setup may have replaced the initial geometry with 200x200.
        self.deiconify()
        self.geometry('1220x790')
        fit_window(self)
        self.update_idletasks()
        self.switch_view(self.current_view)  # nagłówek dopasowany do faktycznej wysokości okna

    def _schedule_text_layout(self, event=None):
        pending = getattr(self, '_text_layout_after', None)
        if pending is not None:
            self.after_cancel(pending)
        self._text_layout_after = self.after(60, self._refresh_text_layout)

    def _refresh_text_layout(self):
        self._text_layout_after = None
        wrap_labels(self)

    def _resize_layout(self, event):
        if event.widget is not self:
            return
        self._schedule_text_layout()
        scale = self.sidebar._get_widget_scaling()
        compact = self.winfo_height() / scale < 480
        state = (compact, self.winfo_width() / scale < 760)
        if getattr(self, '_layout_state', None) == state:
            return
        self._layout_state = state
        self.sidebar.configure(width=180 if state[1] else 228)
        self.sidebar_brand.grid_configure(pady=(5, 5) if compact else (20, 20))
        for button in self.menu_buttons.values():
            button.configure(height=24 if compact else 40)
            button.grid_configure(pady=2 if compact else 4)
        wrap_labels(self)

    def switch_view(self, view_name):
        self.current_view = view_name
        for widget in self.main_container.winfo_children():
            widget.destroy()
        for key, button in self.menu_buttons.items():
            button.configure(fg_color='#2B4967' if key == view_name else 'transparent',
                             text_color='white' if key == view_name else '#C7D5E5')
        if self.test_mode:
            ctk.CTkLabel(self.main_container, text='TRYB TESTOWY  •  wyłącznie fikcyjne dane  •  poczta symulowana',
                         fg_color='#FFF2D9', text_color='#875C19', corner_radius=7, height=30).pack(fill='x',padx=30,pady=(15,0))
        getattr(self, f'render_{view_name}_view')()
        self._schedule_text_layout()

    def create_view_header(self, title, subtitle=''):
        frame = ctk.CTkFrame(self.main_container, fg_color='transparent')
        # Na małych ekranach (np. 1280x800 przy skali 150%) oszczędzaj wysokość.
        compact = self.winfo_height() / self._get_window_scaling() < 640
        frame.pack(fill='x', padx=32, pady=(8,6) if compact else (18,12))
        ctk.CTkLabel(frame, text=title, font=('Segoe UI',21 if compact else 26,'bold'), text_color=INK).pack(anchor='w')
        if subtitle:
            ctk.CTkLabel(frame, text=subtitle, font=('Segoe UI',13), text_color=MUTED, wraplength=760, justify='left').pack(anchor='w',pady=(2 if compact else 6,0))

    def create_card(self, parent, row, col, title, is_pack=False, description=''):
        frame = ctk.CTkFrame(parent, fg_color='white', corner_radius=14, border_width=1, border_color=BORDER)
        if is_pack:
            frame.pack(fill='x',padx=32,pady=10)
        else:
            frame.grid(row=row,column=col,padx=8,pady=8,sticky='nsew')
        ctk.CTkLabel(frame,text=title,font=('Segoe UI',17,'bold'),text_color=INK).pack(anchor='w',padx=18,pady=(16,6))
        if description:
            ctk.CTkLabel(frame,text=description,font=('Segoe UI',12),text_color=MUTED,wraplength=310,justify='left').pack(anchor='w',padx=18,pady=(0,8))
        ctk.CTkFrame(frame,height=1,fg_color=BORDER).pack(fill='x',padx=18,pady=(2,8))
        # Dolny odstęp jest częścią kontenera, a nie pustym przyciskiem.
        frame.configure(height=260)
        return frame

    def create_action_button(self, card, text, command, primary=False, disabled=False):
        button = ctk.CTkButton(card,text=text,command=command,anchor='w',height=38,
            fg_color=GREEN if primary else '#EFF4F8',hover_color='#105B49' if primary else '#E2EBF3',
            text_color='white' if primary else INK,font=('Segoe UI',13),corner_radius=8,
            state='disabled' if disabled else 'normal')
        button.pack(fill='x',padx=18,pady=(0,8))
        return button

    def _grid(self):
        grid = ctk.CTkFrame(self.main_container,fg_color='transparent')
        grid.pack(fill='x',padx=24,pady=2)
        grid.grid_columnconfigure((0,1),weight=1,uniform='cards')
        return grid

    def _todo_items(self, now, year, members):
        """Zadania wymagające uwagi administratora: (tekst, przycisk, akcja)."""
        items = []
        if not self.kalkulator.czy_naliczone(now.year, now.month):
            items.append((f'Składki za {MONTHS[now.month].lower()} {now.year} nie są jeszcze naliczone.',
                          'Nalicz miesiąc', self.open_dues_window))
        if (now.month >= 10 or now.month < 6) and latest_approval(self.session, year) is None:
            items.append((f'Stawki kadencji {year}/{year+1} czekają na październikowe zatwierdzenie.',
                          'Zatwierdź stawki', self.open_change_fees))
        omitted = self.session.query(PozycjaWyciagu).filter_by(stan='omitted').count()
        if omitted:
            items.append((f'Niezaksięgowane pozycje z wyciągów: {omitted} — wymagają ręcznego przypisania.',
                          'Otwórz import', self.import_excel))
        uncertain = self.session.query(WysylkaEmail).filter_by(stan='uncertain').count()
        if uncertain:
            items.append((f'Wiadomości o niepewnym doręczeniu: {uncertain}. Sprawdź skrzynkę przed ponowieniem.',
                          'Historia wysyłek', self.open_bulk_mail))
        no_email = sum(1 for m in members if m.aktywny and not (m.email or '').strip())
        if no_email:
            items.append((f'Aktywni klienci bez adresu e-mail: {no_email} — nie dostaną przypomnień.',
                          'Lista klientów', self.open_list_all))
        if not backup_settings(data_path('config_kopie.json')).get('dodatkowy_katalog'):
            items.append(('Kopie zapasowe trafiają tylko na ten dysk. Ustaw dodatkowy folder (pendrive, dysk zewnętrzny).',
                          'Ustaw kopie', self.open_handover))
        if now.month in (5, 6):
            items.append(('Zbliża się koniec okresu rozliczeniowego.', 'Kopie i rozliczenie', self.open_handover))
        return items

    def _metric_tile(self, parent, col, label, value, note, color):
        parent.grid_columnconfigure(col, weight=1, uniform='metrics')
        tile = ctk.CTkFrame(parent, fg_color='white', corner_radius=14, border_width=1, border_color=BORDER)
        tile.grid(row=0, column=col, sticky='nsew', padx=8)
        ctk.CTkLabel(tile, text=label, text_color=MUTED, font=('Segoe UI', 10, 'bold'),
                     anchor='w', justify='left').pack(fill='x', padx=16, pady=(14, 2))
        amount = ctk.CTkLabel(tile, text=value, text_color=color, font=('Segoe UI', 24, 'bold'), anchor='w')
        amount._nowrap = True
        amount.pack(fill='x', padx=16)
        ctk.CTkLabel(tile, text=note, text_color=MUTED, font=('Segoe UI', 11),
                     anchor='w', justify='left').pack(fill='x', padx=16, pady=(2, 14))

    def render_dashboard_view(self):
        now = datetime.now()
        year = cadence_year(now.year,now.month)
        self.create_view_header('Finanse pod kontrolą',f'Kadencja {year}/{year+1}  ·  1 czerwca – 31 maja  ·  dziś {now:%d.%m.%Y}')
        members = self.session.query(Czlonek).all()
        payments = self.session.query(Wplata).filter(Wplata.data_przelewu >= datetime(year,6,1), Wplata.data_przelewu < datetime(year+1,6,1)).all()
        received = sum((Decimal(str(p.kwota)) for p in payments),Decimal(0))
        debtors = [m for m in members if (m.bilans_otwarcia or 0) < 0]
        debt = -sum((Decimal(str(m.bilans_otwarcia)) for m in debtors),Decimal(0))
        metrics = ctk.CTkFrame(self.main_container,fg_color='transparent')
        metrics.pack(fill='x',padx=24,pady=(0,16))
        active = sum(bool(m.aktywny) for m in members)
        self._metric_tile(metrics, 0, 'CZŁONKOWIE', str(active), f'aktywni · archiwum {len(members)-active}', INK)
        self._metric_tile(metrics, 1, 'WPŁATY', format_pln(received), f'w kadencji · sztuk {len(payments)}', GREEN)
        self._metric_tile(metrics, 2, 'ZALEGŁOŚCI', format_pln(debt),
                          f'łącznie · osób {len(debtors)}' if debtors else 'brak zaległości', RED if debt else GREEN)
        todo = self._todo_items(now, year, members)
        panel = ctk.CTkFrame(self.main_container, fg_color=AMBER_BG if todo else '#E6F2EC', corner_radius=12)
        panel.pack(fill='x', padx=32, pady=(0, 16))
        ctk.CTkLabel(panel, text='Do zrobienia' if todo else 'Wszystko aktualne — nic nie czeka na Twoją decyzję',
                     text_color=AMBER_INK if todo else '#205D47', font=('Segoe UI', 15, 'bold'),
                     anchor='w').pack(fill='x', padx=16, pady=(12, 4 if todo else 12))
        for text, label, command in todo:
            row = ctk.CTkFrame(panel, fg_color='transparent')
            row.pack(fill='x', padx=16, pady=(0, 6))
            row.grid_columnconfigure(0, weight=1)
            cell = ctk.CTkFrame(row, fg_color='transparent')
            cell.grid(row=0, column=0, sticky='ew')
            ctk.CTkLabel(cell, text='•  ' + text, text_color=INK, font=('Segoe UI', 13),
                         anchor='w', justify='left').pack(fill='x')
            ctk.CTkButton(row, text=label, command=command, width=150, height=32).grid(row=0, column=1, padx=(12, 0))
        if todo:
            ctk.CTkFrame(panel, height=6, fg_color='transparent').pack()
        grid=self._grid()
        card=self.create_card(grid,0,0,'Codzienne działania',description='Najczęściej używane operacje w jednym miejscu.')
        self.create_action_button(card,'Wprowadź wpłatę',self.open_single_payment,primary=True)
        self.create_action_button(card,'Przeglądaj klientów',self.open_list_all)
        self.create_action_button(card,'Otwórz rejestr wpłat',self.open_payment_list)
        approval=latest_approval(self.session,year)
        text=(f'Stawki zatwierdzone {approval.data_decyzji:%d.%m.%Y}. Obowiązują od 1 czerwca.' if approval else 'Stawki oczekują na zatwierdzenie. Październikowa decyzja obowiązuje od czerwca.')
        card=self.create_card(grid,0,1,'Składki na tę kadencję',description=text)
        self.create_action_button(card,'Zatwierdź stawki i wyrównanie',self.open_change_fees)
        self.create_action_button(card,'Sprawdź połączenie Gmail',self.open_email_settings)

    def render_members_view(self):
        self.create_view_header('Klienci','Kartoteki, dane kontaktowe i historia umowy.')
        grid=self._grid()
        card=self.create_card(grid,0,0,'Kartoteki',description='Dodawaj i aktualizuj dane bez utraty historii.')
        self.create_action_button(card,'Dodaj klienta',self.open_member_add,primary=True)
        self.create_action_button(card,'Edytuj dane klienta',self.open_edit_member)
        self.create_action_button(card,'Karta finansowa klienta',self.open_member_stats)
        self.create_action_button(card,'Zarchiwizuj klienta',self.open_member_delete)
        card=self.create_card(grid,0,1,'Listy klientów',description='Znajdź osobę po imieniu lub nazwisku.')
        for label,cmd in [('Wszyscy aktywni',self.open_list_all),('Pakiet Premium',self.open_list_premium),('Pakiet Standard',self.open_list_standard),('Archiwum',self.open_list_archived)]:
            self.create_action_button(card,label,cmd)

    def render_payments_view(self):
        self.create_view_header('Wpłaty i składki','Wprowadzaj wpływy i zarządzaj miesięcznymi należnościami.')
        grid=self._grid()
        card=self.create_card(grid,0,0,'Należności',description='Pełne miesiące umowy. Zatwierdzenie stawek może wyrównać okres od czerwca.')
        self.btn_naleznosci=self.create_action_button(card,'Nalicz lub cofnij miesiąc',self.open_dues_window,primary=True)
        self.create_action_button(card,'Zatwierdź stawki kadencji',self.open_change_fees)
        card=self.create_card(grid,0,1,'Wpłaty',description='Każda wpłata zachowuje rzeczywistą datę wpływu.')
        self.create_action_button(card,'Wprowadź wpłatę ręcznie',self.open_single_payment,primary=True)
        self.create_action_button(card,'Rejestr wszystkich wpłat',self.open_payment_list)
        self.create_action_button(card,'Karta finansowa klienta',self.open_member_stats)
        card=self.create_card(self.main_container,0,0,'Wyciągi bankowe',is_pack=True,description='Podgląd, walidacja PLN i dat, ochrona duplikatów oraz kolejka ręcznego sprawdzenia.')
        self.create_action_button(card,'Importuj wyciąg XLSX',self.import_excel)
        self.create_action_button(card,'Konta bankowe klientów',self.open_bank_accounts)

    def render_monits_view(self):
        self.create_view_header('Wiadomości','Sprawdź odbiorcę i treść przed wysłaniem przypomnienia.')
        grid=self._grid()
        card=self.create_card(grid,0,0,'Pojedyncze przypomnienie',description='Przygotuj zestawienie wpłat i aktualnego salda wybranej osoby.')
        self.create_action_button(card,'Przygotuj wiadomość',self.open_send_reminder,primary=True)
        card=self.create_card(grid,0,1,'Poczta Gmail',description='Test połączenia nie wysyła wiadomości. Test wysyłki wymaga potwierdzenia odbiorcy.')
        self.create_action_button(card,'Sprawdź Gmail / wyślij test',self.open_email_settings)
        card=self.create_card(self.main_container,0,0,'Wysyłka zbiorcza',is_pack=True,description='Osobne wiadomości, podgląd treści i trwała historia wysyłek.')
        self.create_action_button(card,'Przygotuj wysyłkę / historia',self.open_bulk_mail,primary=True)

    def render_stats_view(self):
        self.create_view_header('Raporty','Zestawienia wpłat i bieżących sald.')
        card=self.create_card(self.main_container,0,0,'Zestawienia',is_pack=True,description='Zapisane wpłaty, naliczenia i korekty. Braki historii są wyraźnie oznaczone.')
        self.create_action_button(card,'Karta finansowa klienta',self.open_member_stats)
        self.create_action_button(card,'Bieżące salda i zaległości',self.open_monthly_stats)
        self.create_action_button(card,'Zestawienie kadencji — Excel',self.open_yearly_stats)

    def render_settings_view(self):
        self.create_view_header('Ustawienia','Stawki, poczta i format importowanego wyciągu.')
        grid=self._grid()
        card=self.create_card(grid,0,0,'Składki',description='Decyzja z października obowiązuje od 1 czerwca wybranej kadencji.')
        self.create_action_button(card,'Zatwierdź stawki kadencji',self.open_change_fees,primary=True)
        self.create_action_button(card,'Statusy i stawki bazowe',self.open_statuses_list)
        card=self.create_card(grid,0,1,'Poczta i import',description='Sprawdź konfigurację przed pracą z rzeczywistymi danymi.')
        self.create_action_button(card,'Poczta Gmail i wiadomość testowa',self.open_email_settings)
        self.create_action_button(card,'Nazwy kolumn wyciągu',self.open_change_columns)
        card=self.create_card(self.main_container,0,0,'Kopie i przekazanie kadencji',is_pack=True,
            description='Kopia powstaje przy każdym zamknięciu. Tu ustawisz dodatkowy nośnik i przygotujesz czerwcowe przekazanie następcy.')
        self.create_action_button(card,'Kopie zapasowe i przekazanie',self.open_handover,primary=True)

    def refresh_current_view(self):
        self.switch_view(self.current_view)

    def sprawdz_pulsowanie(self):
        # Spokojny status zamiast migającego alarmu.
        if self.current_view == 'dashboard':
            self.switch_view('dashboard')

    def open_list_all(self):
        MembersListWindow(self,self.session,'Wszyscy aktywni klienci',czy_aktywny=True)

    def open_email_settings(self):
        EmailSettingsWindow(self)

    def open_member_add(self):
        AddMemberWindow(self, self.session, self.refresh_current_view)

    def import_excel(self):
        ImportWindow(self, self.session)

    def open_dues_window(self):
        DuesWindow(self, self.session, self.kalkulator, on_close_callback=self.sprawdz_pulsowanie)

    def open_single_payment(self):
        MemberSelectorWindow(
            master=self, session=self.session, title="Wybierz klienta do zaksięgowania wpłaty", include_archived=True,
            action_button_text="Wprowadź wpłatę",
            on_select_callback=lambda m: SinglePaymentWindow(self, self.session, m)
        )

    def open_delete_payment(self):
        MemberSelectorWindow(
            master=self, session=self.session, title="Wybierz klienta — historia wpłat", include_archived=True,
            action_button_text="Pokaż wpłaty", on_select_callback=lambda m: DeletePaymentWindow(self, self.session, m)
        )

    def open_member_delete(self):
        MemberSelectorWindow(
            master=self, session=self.session, title="Wybierz klienta do zarchiwizowania",
            action_button_text="Zarchiwizuj klienta", on_select_callback=lambda m: DeleteMemberWindow(self, self.session, m)
        )

    def open_edit_member(self):
        MemberSelectorWindow(
            master=self, session=self.session, title="Wybierz klienta do edycji danych", include_archived=True,
            action_button_text="Edytuj dane", on_select_callback=lambda m: EditMemberWindow(self, self.session, m)
        )

    def open_member_stats(self):
        MemberSelectorWindow(
            master=self, session=self.session, title="Wybierz klienta — karta finansowa", include_archived=True,
            action_button_text="Pokaż kartę finansową", on_select_callback=lambda m: MemberStatsWindow(self, self.session, m)
        )

    def open_monthly_stats(self):
        MonthlyStatsWindow(self, self.session)

    def open_yearly_stats(self):
        YearlyStatsWindow(self, self.session)

    def open_change_fees(self):
        ChangeFeesWindow(self, self.session)

    def open_change_columns(self):
        ChangeColumnsWindow(self)

    def open_list_premium(self):
        MembersListWindow(self, self.session, "Klienci — Premium", status_filter="Premium", czy_aktywny=True)

    def open_list_standard(self):
        MembersListWindow(self, self.session, "Klienci — Standard", status_filter="Standard", czy_aktywny=True)

    def open_list_archived(self):
        MembersListWindow(self, self.session, "Archiwum: Byli klienci", status_filter=None, czy_aktywny=False)

    def open_payment_list(self):
        PaymentsListWindow(self, self.session)

    def open_statuses_list(self):
        StatusListWindow(self, self.session)

    def open_bank_accounts(self):
        BankAccountsListWindow(self, self.session)

    def open_handover(self):
        HandoverWindow(self, self.session)

    def open_bulk_mail(self):
        BulkMailWindow(self, self.session)

    def open_send_reminder(self):
        SendReminderWindow(self, self.session)

    def report_callback_exception(self, exc, value, traceback):
        messagebox.showerror('Nie udało się wykonać operacji',
            'Wystąpił błąd interfejsu. Zamknij okno operacji i spróbuj ponownie.\n'
            'Nie ponawiaj wysyłki wiadomości bez sprawdzenia jej stanu.',parent=self)
        print(f'GUI_ERROR: {exc.__name__}')

    def on_closing(self):
        active = [(job, stop) for job, stop in getattr(self, 'background_jobs', []) if job.is_alive()]
        if active:
            for job, stop in active:
                if stop is not None:
                    stop.set()
            self.title('Monity — kończenie bieżącej operacji…')
            self.after(150, self.on_closing)
            return
        cancel_callbacks(self, all_tasks=True)
        self.session.close()
        self.engine.dispose()
        self.title('Monity — tworzenie kopii zapasowej…')
        errors = automatic_backup(data_path('monity.db'), backup_dir(), data_path('config_kopie.json'))
        if errors:
            print('BACKUP_ERROR')
            if not self.test_mode:
                messagebox.showwarning('Kopia zapasowa', 'Nie udało się utworzyć kopii przy zamykaniu:\n'
                    + '\n'.join(errors) + '\n\nDane w bazie są zapisane. Sprawdź dysk lub folder kopii.', parent=self)
        self.destroy()


if __name__ == '__main__':
    try:
        app=MonityApp()
    except (FileNotFoundError, ValueError) as exc:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror('Monity — brak katalogu danych', str(exc))
        raise SystemExit(1)
    app.mainloop()
