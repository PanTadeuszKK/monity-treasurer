from ui import prepare_window, MonityToplevel
import customtkinter as ctk
from tkinter import ttk, messagebox
from models import Czlonek
from member_search import name_matches
from ui import pack_footer, format_balance, balance_tags, balance_tag, secondary_button, live_search, GREEN, GREEN_HOVER, MUTED


class MemberSelectorWindow(MonityToplevel):
    def __init__(self, master, session, title, action_button_text, on_select_callback, include_archived=False, initial_query="", **kwargs):
        """
        Uniwersalne okno wyboru klienta.
        :param title: Tytuł okna (np. "Wybierz klienta do usunięcia")
        :param action_button_text: Tekst na guziku (np. "USUŃ CZŁONKA")
        :param on_select_callback: Funkcja, która zostanie wywołana po wybraniu osoby (przekazuje obiekt Czlonek)
        """
        super().__init__(master, **kwargs)
        prepare_window(self, master)
        self.session = session
        self.on_select_callback = on_select_callback
        self.include_archived = include_archived

        self.title(title)
        self.geometry("750x500")
        self.lift()

        self.frame_search = ctk.CTkFrame(self, fg_color="transparent")
        self.frame_search.pack(fill="x", padx=20, pady=15)

        self.lbl_szukaj = ctk.CTkLabel(self.frame_search, text="Szukaj po:")
        self.lbl_szukaj.pack(side="left", padx=(0, 10))

        self.kryteria = ["Imię i Nazwisko", "Email"]
        self.dropdown_kryterium = ctk.CTkOptionMenu(
            self.frame_search, values=self.kryteria, width=150,
            text_color="black", fg_color="white", button_color="#E0E0E0"
        )
        self.dropdown_kryterium.pack(side="left", padx=(0, 10))

        self.entry_szukaj = ctk.CTkEntry(self.frame_search, width=200, placeholder_text="Zacznij pisać imię lub nazwisko…")
        self.entry_szukaj.pack(side="left", padx=(0, 10))
        self.entry_szukaj.insert(0, initial_query)

        self.btn_szukaj = ctk.CTkButton(
            self.frame_search, text="Szukaj", command=self.zaladuj_dane, width=80
        )
        self.btn_szukaj.pack(side="left", padx=(0, 10))

        self.btn_reset = secondary_button(
            self.frame_search, text="Wyczyść", command=self.resetuj_szukanie, width=80
        )
        self.btn_reset.pack(side="left")

        self.frame_table = ctk.CTkFrame(self)
        self.frame_table.pack(fill="both", expand=True, padx=20, pady=(0, 10))

        # Ukryta kolumna na bazodanowe ID obiektu (żeby łatwo go potem pobrać)
        kolumny = ("db_id", "id_a", "imie", "status", "saldo")
        self.tree = ttk.Treeview(self.frame_table, columns=kolumny, show="headings", selectmode="browse")

        self.tree.heading("db_id", text="DB_ID")
        self.tree.heading("id_a", text="ID A!")
        self.tree.heading("imie", text="Imię i Nazwisko")
        self.tree.heading("status", text="Status")
        self.tree.heading("saldo", text="Saldo")

        # Ukrywamy pierwszą kolumnę z ID z bazy, użytkownik nie musi tego widzieć
        self.tree.column("db_id", width=0, stretch=False)
        self.tree.column("id_a", width=60, anchor="center")
        self.tree.column("imie", width=250, anchor="w")
        self.tree.column("status", width=150, anchor="center")
        self.tree.column("saldo", width=170, anchor="e")
        balance_tags(self.tree)

        scrollbar = ttk.Scrollbar(self.frame_table, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscroll=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)

        # Powiązanie podwójnego kliknięcia z wyborem
        self.tree.bind("<Double-1>", lambda event: self.potwierdz_wybor())
        self.tree.bind("<Return>", lambda event: self.potwierdz_wybor())

        self.btn_wybierz = ctk.CTkButton(
            self, text=action_button_text, command=self.potwierdz_wybor,
            fg_color=GREEN, hover_color=GREEN_HOVER, font=("Segoe UI", 14, "bold"), height=40, width=260
        )
        pack_footer(self.btn_wybierz)

        self.lbl_count = ctk.CTkLabel(self, text="", text_color=MUTED)
        self.lbl_count.pack(pady=(0,10))
        self.entry_szukaj.bind("<Return>", lambda event: self.zaladuj_dane())
        self.entry_szukaj.bind("<Down>", lambda event: self._focus_first_row())
        live_search(self.entry_szukaj, self.zaladuj_dane)
        self.after_idle(lambda: self.entry_szukaj.focus_set() if self.entry_szukaj.winfo_exists() else None)
        self.zaladuj_dane()

    def resetuj_szukanie(self):
        self.entry_szukaj.delete(0, 'end')
        self.zaladuj_dane()

    def zaladuj_dane(self):
        for row in self.tree.get_children():
            self.tree.delete(row)

        kryterium = self.dropdown_kryterium.get()
        fraza = self.entry_szukaj.get().strip().lower()

        query = self.session.query(Czlonek)
        if not self.include_archived:
            query = query.filter_by(aktywny=True)
        czlonkowie = query.order_by(Czlonek.imie_nazwisko).all()

        for c in czlonkowie:
            if fraza:
                pasuje = False
                if kryterium == "Imię i Nazwisko" and name_matches(c.imie_nazwisko,fraza):
                    pasuje = True
                elif kryterium == "Email" and c.email and fraza in c.email.lower():
                    pasuje = True

                if not pasuje:
                    continue

            status_nazwa = c.status.nazwa if c.status else "Brak"
            if not c.aktywny:
                status_nazwa += " (archiwum)"

            self.tree.insert("", "end", values=(
                c.id,  # Ukryte ID z bazy danych
                c.numer_identyfikacyjny,
                c.imie_nazwisko,
                status_nazwa,
                format_balance(c.bilans_otwarcia)
            ), tags=balance_tag(c.bilans_otwarcia))

        rows = self.tree.get_children()
        count = len(rows)
        if count == 1:
            self.tree.selection_set(rows[0])
        self.lbl_count.configure(text=(f"Znaleziono osób: {count}. Dwuklik lub Enter wybiera osobę." if count
            else "Brak wyników. Zmień frazę lub wyczyść wyszukiwanie."))

    def _focus_first_row(self):
        rows = self.tree.get_children()
        if rows:
            self.tree.focus_set()
            self.tree.focus(rows[0])
            self.tree.selection_set(rows[0])
        return "break"

    def potwierdz_wybor(self):
        wybrany_element = self.tree.selection()
        if not wybrany_element:
            self.attributes("-topmost", False)
            messagebox.showwarning("Brak wyboru", "Najpierw kliknij osobę na liście, aby ją zaznaczyć.", parent=self)
            self.lift()
            return

        # Pobieramy ukryte ID z bazy danych z pierwszej kolumny
        wartosci = self.tree.item(wybrany_element[0], "values")
        db_id = int(wartosci[0])

        czlonek = self.session.get(Czlonek, db_id)

        if czlonek:
            # Wywołujemy funkcję docelową i przekazujemy jej klienta
            self.destroy()  # Najpierw usuń stary fokus, potem otwórz formularz.
            self.on_select_callback(czlonek)