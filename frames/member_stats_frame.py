from decimal import Decimal
import customtkinter as ctk
from member_search import name_matches
from frames.member_selector import MemberSelectorWindow
from models import Czlonek
from member_ledger import member_ledger
from annual_fees import cadence_year
from allocation import member_settlement, describe
from ui import prepare_window, MonityToplevel, data_table, set_text, format_balance, format_pln, MUTED, GREEN, RED, INK


class MemberStatsWindow(MonityToplevel):
    def __init__(self, master, session, czlonek=None, **kwargs):
        super().__init__(master, **kwargs)
        prepare_window(self, master)
        self.session, self.czlonek = session, None
        self.title('Karta finansowa klienta')
        self.geometry('1120x720')
        self.preferred_width = 1120
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)
        header = ctk.CTkFrame(self, fg_color='transparent')
        header.grid(row=0, column=0, sticky='ew', padx=20, pady=(8, 2))
        self.lbl_imie = ctk.CTkLabel(header, text='Karta finansowa klienta', font=('Segoe UI', 22, 'bold'), anchor='w')
        self.lbl_imie.pack(side='left', fill='x', expand=True)
        self.lbl_saldo = ctk.CTkLabel(header, text='Saldo: —', font=('Segoe UI', 18, 'bold'))
        self.lbl_saldo.pack(side='right', padx=8)
        search = ctk.CTkFrame(self, fg_color='transparent')
        search.grid(row=1, column=0, sticky='ew', padx=20, pady=2)
        self.entry_name = ctk.CTkEntry(search, placeholder_text='Imię lub nazwisko', width=240)
        self.entry_id = self.entry_name
        self.entry_name.pack(side='left', fill='x', expand=True, padx=(0, 8))
        self.entry_name.bind('<Return>', lambda event: self.szukaj_czlonka())
        ctk.CTkButton(search, text='Wybierz klienta', command=self.szukaj_czlonka, width=140).pack(side='left')
        filters = ctk.CTkFrame(self, fg_color='transparent')
        filters.grid(row=2, column=0, sticky='ew', padx=20, pady=2)
        self.miesiace = {'Wszystkie miesiące': 0, **{f'{m:02}': m for m in range(1, 13)}}
        self.dropdown_okres = ctk.CTkOptionMenu(filters, values=['Wszystkie kadencje'], width=140,
            command=lambda value: self.pokaz_wplaty())
        self.dropdown_okres.grid(row=0, column=0, padx=(0, 8), pady=3, sticky='ew')
        self.dropdown_miesiac = ctk.CTkOptionMenu(filters, values=list(self.miesiace), width=110,
            command=lambda value: self.pokaz_wplaty())
        self.dropdown_miesiac.grid(row=0, column=1, padx=(0, 8), pady=3, sticky='ew')
        self.kind = ctk.CTkOptionMenu(filters, values=['Wszystkie operacje', 'Wpłaty', 'Należności', 'Salda początkowe'],
            width=140, command=lambda value: self.pokaz_wplaty())
        self.kind.grid(row=0, column=2, padx=(0, 8), pady=3, sticky='ew')
        self.btn_filtruj = ctk.CTkButton(filters, text='Odśwież', width=75, command=self.pokaz_wplaty)
        self.btn_filtruj.grid(row=0, column=3, pady=3, sticky='e')
        filters.grid_columnconfigure((0, 1), weight=1)
        self.scroll_wplaty = ctk.CTkFrame(self, fg_color='white')
        self.scroll_wplaty.grid(row=3, column=0, sticky='nsew', padx=20, pady=3)
        self.tree = data_table(self.scroll_wplaty, [
            ('date', 'Data', 96), ('period', 'Okres', 75), ('kind', 'Rodzaj', 155),
            ('amount', 'Zmiana / kwota PLN', 145), ('state', 'Stan', 140),
            ('description', 'Opis transakcji / należności', 380)], selectmode='browse', height=6)
        self.tree.tag_configure('info', foreground=MUTED)
        self.tree.tag_configure('reversed', foreground=MUTED)
        self.tree.bind('<<TreeviewSelect>>', self.show_details)
        self.summary = ctk.CTkLabel(self, text='Wybierz osobę, aby zobaczyć zapisane operacje.', anchor='w',
            height=18, font=('Segoe UI', 11))
        self.summary.grid(row=5, column=0, sticky='ew', padx=20)
        self.lbl_rozliczenie = ctk.CTkLabel(self, text='', anchor='w', justify='left',
            font=('Segoe UI', 12, 'bold'), text_color=INK)
        self.lbl_rozliczenie.grid(row=4, column=0, sticky='ew', padx=20, pady=(4, 0))
        self.details = ctk.CTkTextbox(self, height=110)
        self.details.grid(row=6, column=0, sticky='ew', padx=20, pady=2)
        set_text(self.details, 'Wybierz wiersz, aby zobaczyć pełny opis i źródło operacji.')
        self.warning = ctk.CTkLabel(self, text='', justify='left', anchor='w', wraplength=1000,
            font=('Segoe UI', 11), text_color=MUTED, height=18)
        self.warning.grid(row=7, column=0, sticky='ew', padx=20, pady=(0, 6))
        self.rows = {}
        if czlonek is not None:
            self.wczytaj_czlonka(czlonek)
        self._compact = None
        self.bind('<Configure>', self.layout_controls, add='+')

    def layout_controls(self, event=None):
        if event is not None and event.widget is not self:
            return
        narrow = self.winfo_width() / self._get_window_scaling() < 540
        compact = self.winfo_height() / self._get_window_scaling() < 550
        if (compact, narrow) != self._compact:
            self._compact = (compact, narrow)
            self.kind.grid(row=1 if narrow else 0, column=0 if narrow else 2, padx=(0, 8), pady=3, sticky='ew')
            self.btn_filtruj.grid(row=1 if narrow else 0, column=1 if narrow else 3, pady=3, sticky='e')
            self.details.configure(height=35 if compact else 110)
            self.lbl_imie.configure(font=('Segoe UI', 16 if compact else 22, 'bold'))
            self.lbl_saldo.configure(font=('Segoe UI', 14 if compact else 18, 'bold'))

    def szukaj_czlonka(self):
        query = self.entry_name.get().strip()
        matches = [m for m in self.session.query(Czlonek).order_by(Czlonek.imie_nazwisko)
                   if name_matches(m.imie_nazwisko, query)]
        if query and len(matches) == 1:
            self.wczytaj_czlonka(matches[0])
        else:
            MemberSelectorWindow(self, self.session, 'Wybierz klienta', 'Pokaż kartę finansową',
                self.wczytaj_czlonka, include_archived=True, initial_query=query)

    def wczytaj_czlonka(self, member):
        self.czlonek = member
        self.entry_name.delete(0, 'end')
        if member:
            self.entry_name.insert(0, member.imie_nazwisko)
        self.pokaz_wplaty()

    def pokaz_wplaty(self):
        self.tree.delete(*self.tree.get_children())
        self.rows = {}
        if self.czlonek is None:
            return
        ledger = member_ledger(self.session, self.czlonek.id)
        self.lbl_imie.configure(text=f"{ledger['name']} · A!{ledger['public_id']}" + (' · archiwum' if ledger['archived'] else ''))
        balance = Decimal(ledger['balance']) / 100
        self.lbl_saldo.configure(text=format_balance(balance).capitalize(), text_color=GREEN if balance >= 0 else RED)
        self.settlement = member_settlement(self.session, self.czlonek.id)
        self.lbl_rozliczenie.configure(text=describe(self.settlement),
            text_color=RED if self.settlement.unpaid or self.settlement.older_debt_cents else GREEN)
        years = sorted({cadence_year(r.period.year, r.period.month) for r in ledger['rows']}, reverse=True)
        periods = ['Wszystkie kadencje'] + [f'{y}/{y + 1}' for y in years]
        self.dropdown_okres.configure(values=periods)
        if self.dropdown_okres.get() not in periods:
            self.dropdown_okres.set(periods[0])
        year = None if self.dropdown_okres.get() == periods[0] else int(self.dropdown_okres.get().split('/')[0])
        month = self.miesiace[self.dropdown_miesiac.get()]
        kind = self.kind.get()
        for row in ledger['rows']:
            if year is not None and cadence_year(row.period.year, row.period.month) != year:
                continue
            if month and row.period.month != month:
                continue
            if kind == 'Wpłaty' and row.kind != 'Wpłata':
                continue
            if kind == 'Należności' and row.kind in ('Wpłata', 'Saldo początkowe'):
                continue
            if kind == 'Salda początkowe' and row.kind != 'Saldo początkowe':
                continue
            self.rows[row.key] = row
            amount = 'Nieznana' if row.cents is None else f'{Decimal(row.cents) / 100:+.2f}'
            tag = 'info' if not row.affects_balance else ('reversed' if row.state == 'Cofnięte' else '')
            self.tree.insert('', 'end', iid=row.key, values=(row.date, f'{row.period:%Y-%m}', row.kind,
                amount, row.state, row.description.replace('\n', ' ')), tags=(tag,))
        paid = sum(r.cents for r in self.rows.values() if r.kind == 'Wpłata')
        self.summary.configure(text=f'Pozycji: {len(self.rows)} · Wpłaty w filtrze: {format_pln(Decimal(paid) / 100)} · '
            '− obciążenie / + wpływ lub zwrot')
        self.warning.configure(text='Saldo początkowe: informacja. Dawne wpisowe i niezapisane operacje mogą być nieudokumentowane.')
        set_text(self.details, 'Wybierz wiersz, aby zobaczyć pełny opis, nadawcę i źródło operacji.')

    def show_details(self, event=None):
        selected = self.tree.selection()
        if selected and selected[0] in self.rows:
            row = self.rows[selected[0]]
            set_text(self.details, f'{row.kind} · {row.state}\n{row.details}')
