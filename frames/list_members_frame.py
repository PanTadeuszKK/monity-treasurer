from member_search import name_matches
from ui import prepare_window, MonityToplevel, format_balance, balance_tags, balance_tag, secondary_button, live_search, MUTED
import customtkinter as ctk
from tkinter import ttk
from models import Czlonek, Status

class MembersListWindow(MonityToplevel):
    def __init__(self, master, session, title_text, status_filter=None, czy_aktywny=True, **kwargs):
        super().__init__(master, **kwargs)
        prepare_window(self, master)
        self.session = session
        self.status_filter = status_filter
        self.czy_aktywny = czy_aktywny

        self.title(title_text)
        self.geometry("800x500")
        self.lift()

        self.frame_search = ctk.CTkFrame(self, fg_color="transparent")
        self.frame_search.pack(fill="x", padx=20, pady=10)

        self.entry_szukaj = ctk.CTkEntry(self.frame_search, width=250, placeholder_text="Zacznij pisać imię lub nazwisko…")
        self.entry_szukaj.pack(side="left", padx=(0, 10))

        self.btn_szukaj = ctk.CTkButton(self.frame_search, text="Szukaj", command=self.zaladuj_dane, width=80)
        self.btn_szukaj.pack(side="left", padx=(0, 10))

        self.btn_reset = secondary_button(self.frame_search, text="Wyczyść", command=self.resetuj_szukanie, width=80)
        self.btn_reset.pack(side="left")
        ctk.CTkButton(self.frame_search, text="Karta finansowa", command=self.open_finances, width=145).pack(side="right", padx=8)

        self.frame_table = ctk.CTkFrame(self)
        self.frame_table.pack(fill="both", expand=True, padx=20, pady=(0, 20))

        kolumny = ("id", "imie", "email", "status", "saldo")
        self.tree = ttk.Treeview(self.frame_table, columns=kolumny, show="headings", selectmode="browse")

        self.tree.heading("id", text="ID A!")
        self.tree.heading("imie", text="Imię i Nazwisko")
        self.tree.heading("email", text="Email")
        self.tree.heading("status", text="Status")
        self.tree.heading("saldo", text="Saldo")

        self.tree.column("id", width=60, anchor="center")
        self.tree.column("imie", width=200, anchor="w")
        self.tree.column("email", width=200, anchor="w")
        self.tree.column("status", width=120, anchor="center")
        self.tree.column("saldo", width=170, anchor="e")
        balance_tags(self.tree)

        scrollbar = ttk.Scrollbar(self.frame_table, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscroll=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind('<Double-1>', self.open_finances)
        self.tree.bind('<Return>', self.open_finances)

        self.entry_szukaj.bind("<Return>", lambda event: self.zaladuj_dane())
        live_search(self.entry_szukaj, self.zaladuj_dane)
        self.lbl_count = ctk.CTkLabel(self, text="", text_color=MUTED)
        self.lbl_count.pack(before=self.frame_table, anchor="w", padx=22)
        self.zaladuj_dane()

    def resetuj_szukanie(self):
        self.entry_szukaj.delete(0, 'end')
        self.zaladuj_dane()

    def zaladuj_dane(self):
        for row in self.tree.get_children():
            self.tree.delete(row)

        fraza = self.entry_szukaj.get().strip().lower()

        # Budowanie zapytania bazy danych (FILTR AKTYWNOŚCI JEST KLUCZOWY!)
        query = self.session.query(Czlonek).filter_by(aktywny=self.czy_aktywny)

        # Filtrowanie po statusie (Premium / Standard), jeśli zostało podane
        if self.status_filter:
            query = query.join(Status).filter(Status.nazwa.ilike(f"%{self.status_filter}%"))

        czlonkowie = query.order_by(Czlonek.imie_nazwisko).all()

        for c in czlonkowie:
            if fraza:
                if not name_matches(c.imie_nazwisko,fraza):
                    continue

            status_nazwa = c.status.nazwa if c.status else "-"
            self.tree.insert("", "end", values=(
                c.numer_identyfikacyjny,
                c.imie_nazwisko,
                c.email if c.email else "-",
                status_nazwa,
                format_balance(c.bilans_otwarcia)
            ), tags=balance_tag(c.bilans_otwarcia))
        rows = len(self.tree.get_children())
        debt = sum(1 for c in czlonkowie if (c.bilans_otwarcia or 0) < 0 and (not fraza or name_matches(c.imie_nazwisko, fraza)))
        self.lbl_count.configure(text=f"Osób: {rows}  ·  z zaległością: {debt}  ·  dwuklik otwiera kartę finansową")

    def open_finances(self, event=None):
        if event is not None and getattr(event, 'num', None) == 1:
            row = self.tree.identify_row(event.y)
            if not row:
                return
            self.tree.selection_set(row)
        selected = self.tree.selection()
        if selected:
            public_id = int(self.tree.item(selected[0], 'values')[0])
            member = self.session.query(Czlonek).filter_by(numer_identyfikacyjny=public_id).one()
            from frames.member_stats_frame import MemberStatsWindow
            window = getattr(self, '_finance_window', None)
            if window is not None and window.winfo_exists():
                window.wczytaj_czlonka(member)
                window.lift()
            else:
                self._finance_window = MemberStatsWindow(self, self.session, member)
