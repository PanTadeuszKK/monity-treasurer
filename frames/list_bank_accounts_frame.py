from member_search import name_matches
from ui import prepare_window, MonityToplevel
import customtkinter as ctk
from tkinter import ttk
from sqlalchemy.orm import joinedload
from models import KontoBankowe, Czlonek


class BankAccountsListWindow(MonityToplevel):
    def __init__(self, master, session, **kwargs):
        super().__init__(master, **kwargs)
        prepare_window(self, master)
        self.session = session

        self.title("Lista Kont Bankowych")
        self.geometry("750x450")
        self.lift()

        self.frame_search = ctk.CTkFrame(self, fg_color="transparent")
        self.frame_search.pack(fill="x", padx=20, pady=10)

        self.lbl_szukaj = ctk.CTkLabel(self.frame_search, text="Szukaj po:")
        self.lbl_szukaj.pack(side="left", padx=(0, 10))

        # Opcje wyszukiwania
        self.kryteria = ["Imię i Nazwisko", "Numer konta"]
        self.dropdown_kryterium = ctk.CTkOptionMenu(
            self.frame_search, values=self.kryteria, width=150,
            text_color="black", fg_color="white", button_color="#E0E0E0"
        )
        self.dropdown_kryterium.pack(side="left", padx=(0, 10))

        self.entry_szukaj = ctk.CTkEntry(self.frame_search, width=250, placeholder_text="Wpisz szukaną frazę...")
        self.entry_szukaj.pack(side="left", padx=(0, 10))
        self.entry_szukaj.bind('<Return>',lambda event:self.zaladuj_dane())

        self.btn_szukaj = ctk.CTkButton(
            self.frame_search, text="Szukaj", command=self.zaladuj_dane, width=80, fg_color="#203B5D"
        )
        self.btn_szukaj.pack(side="left", padx=(0, 10))

        self.btn_reset = ctk.CTkButton(
            self.frame_search, text="Reset", command=self.resetuj_szukanie, width=80, fg_color="#B65348"
        )
        self.btn_reset.pack(side="left")

        self.frame_table = ctk.CTkFrame(self)
        self.frame_table.pack(fill="both", expand=True, padx=20, pady=(0, 20))

        kolumny = ("id_konta", "numer_konta", "id_a", "imie")
        self.tree = ttk.Treeview(self.frame_table, columns=kolumny, show="headings", selectmode="browse")

        self.tree.heading("id_konta", text="ID w bazie")
        self.tree.heading("numer_konta", text="Numer Konta Bankowego")
        self.tree.heading("id_a", text="ID A!")
        self.tree.heading("imie", text="Imię i Nazwisko Właściciela")

        self.tree.column("id_konta", width=80, anchor="center")
        self.tree.column("numer_konta", width=250, anchor="w")
        self.tree.column("id_a", width=60, anchor="center")
        self.tree.column("imie", width=250, anchor="w")

        # Scrollbar dla tabeli
        scrollbar = ttk.Scrollbar(self.frame_table, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscroll=scrollbar.set)

        scrollbar.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)

        # Ładujemy dane przy starcie
        self.zaladuj_dane()

    def resetuj_szukanie(self):
        self.entry_szukaj.delete(0, 'end')
        self.zaladuj_dane()

    def zaladuj_dane(self):
        # Czyszczenie obecnych danych w tabeli
        for row in self.tree.get_children():
            self.tree.delete(row)

        kryterium = self.dropdown_kryterium.get()
        fraza = self.entry_szukaj.get().strip().lower()

        # Pobieramy wszystkie konta z bazy (z powiązanym członkiem -> brak N+1)
        konta = self.session.query(KontoBankowe).options(
            joinedload(KontoBankowe.czlonek)
        ).all()

        for k in konta:
            czlonek = k.czlonek
            imie_nazwisko = czlonek.imie_nazwisko if czlonek else "Brak przypisania"
            id_a = str(czlonek.numer_identyfikacyjny) if czlonek else "-"
            nr_konta = k.numer_konta

            # Filtrowanie
            if fraza:
                pasuje = False
                nr_konta_czysty = nr_konta.replace(" ", "")
                fraza_czysta = fraza.replace(" ", "")

                if kryterium == "Numer konta" and fraza_czysta in nr_konta_czysty.lower():
                    pasuje = True
                elif kryterium == "Imię i Nazwisko" and name_matches(imie_nazwisko,fraza):
                    pasuje = True

                if not pasuje:
                    continue  # Pomijamy, jeśli nie pasuje

            # Wrzucamy wiersz do tabeli
            self.tree.insert("", "end", values=(
                k.numer_konta,
                nr_konta,
                id_a,
                imie_nazwisko
            ))
