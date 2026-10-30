from member_search import name_matches
from ui import prepare_window, MonityToplevel, data_table, set_text
import customtkinter as ctk
from sqlalchemy.orm import joinedload
from models import Wplata, Czlonek
from member_ledger import payment_sources, payment_details


class PaymentsListWindow(MonityToplevel):
    def __init__(self, master, session, **kwargs):
        super().__init__(master, **kwargs)
        prepare_window(self, master)
        self.session = session

        self.title("Historia wszystkich wpłat")
        self.geometry("1120x650")
        self.lift()

        self.frame_search = ctk.CTkFrame(self, fg_color="transparent")
        self.frame_search.pack(fill="x", padx=20, pady=10)

        self.lbl_szukaj = ctk.CTkLabel(self.frame_search, text="Szukaj po:")
        self.lbl_szukaj.pack(side="left", padx=(0, 10))

        # Opcje wyszukiwania
        self.kryteria = ["Imię i Nazwisko", "Data (np. 2026-05)", "Metoda księgowania", "Opis transakcji"]
        self.dropdown_kryterium = ctk.CTkOptionMenu(
            self.frame_search, values=self.kryteria, width=160,
            text_color="black", fg_color="white", button_color="#E0E0E0"
        )
        self.dropdown_kryterium.pack(side="left", padx=(0, 10))

        self.entry_szukaj = ctk.CTkEntry(self.frame_search, width=200, placeholder_text="Wpisz szukaną frazę...")
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

        self.details = ctk.CTkTextbox(self, height=145)
        self.details.pack(side='bottom', fill='x', padx=20, pady=(0, 14))
        set_text(self.details, 'Wybierz wpłatę, aby zobaczyć pełny opis i pochodzenie transakcji.')
        self.frame_table = ctk.CTkFrame(self)
        self.frame_table.pack(fill="both", expand=True, padx=20, pady=(0, 8))
        self.tree = data_table(self.frame_table, [('data', 'Data wpływu', 100), ('id_a', 'ID A!', 65),
            ('imie', 'Przypisano do', 210), ('kwota', 'PLN', 90),
            ('description', 'Opis transakcji', 340), ('metoda', 'Metoda', 150)], selectmode='browse')
        self.tree.bind('<<TreeviewSelect>>', self.show_details)

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

        # Pobieramy wszystkie wpłaty z bazy posortowane od najnowszej do najstarszej
        # joinedload pobiera od razu powiązanego klienta -> brak problemu N+1
        wplaty = self.session.query(Wplata).options(
            joinedload(Wplata.czlonek)
        ).order_by(Wplata.data_przelewu.desc()).all()
        sources = payment_sources(self.session, [w.id for w in wplaty])
        self.payment_details = {}
        set_text(self.details, 'Wybierz wpłatę, aby zobaczyć pełny opis i pochodzenie transakcji.')

        for w in wplaty:
            # Ponieważ mamy zdefiniowaną relację w models.py, możemy bezpośrednio odwołać się do w.czlonek
            czlonek = w.czlonek
            imie_nazwisko = czlonek.imie_nazwisko if czlonek else "Nieznany"
            id_a = str(czlonek.numer_identyfikacyjny) if czlonek else "Brak"
            data_str = w.data_przelewu.strftime('%Y-%m-%d')
            metoda = w.metoda_dopasowania if w.metoda_dopasowania else ""

            # Filtrowanie
            if fraza:
                pasuje = False
                if kryterium == "Imię i Nazwisko" and name_matches(imie_nazwisko,fraza):
                    pasuje = True
                elif kryterium == "Data (np. 2026-05)" and fraza in data_str:
                    pasuje = True
                elif kryterium == "Metoda księgowania" and fraza in metoda.lower():
                    pasuje = True
                elif kryterium == "Opis transakcji" and fraza in (w.tytul_oryginalny or '').lower():
                    pasuje = True

                if not pasuje:
                    continue  # Pomijamy wpłatę, jeśli nie pasuje

            # Wrzucamy wiersz do tabeli
            self.payment_details[str(w.id)] = f'Przypisano do: {imie_nazwisko} (A!{id_a})\n' + payment_details(w, sources.get(w.id, ''))
            self.tree.insert("", "end", iid=str(w.id), values=(
                data_str,
                id_a,
                imie_nazwisko,
                f"{w.kwota:.2f}",
                (w.tytul_oryginalny or 'Brak zapisanego opisu').replace('\n', ' '),
                metoda
            ))

    def show_details(self, event=None):
        selected = self.tree.selection()
        if selected:
            set_text(self.details, self.payment_details[selected[0]])
