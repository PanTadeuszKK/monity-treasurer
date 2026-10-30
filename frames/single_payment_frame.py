from ui import prepare_window, MonityToplevel, pack_footer
import customtkinter as ctk
from tkinter import messagebox
from datetime import datetime
from models import Czlonek, Wplata
from decimal import Decimal
from fee_service import parse_amount
from finance_service import record_payment
from uuid import uuid4


class SinglePaymentWindow(MonityToplevel):
    def __init__(self, master, session, czlonek, on_success_callback=None, **kwargs):
        super().__init__(master, **kwargs)
        prepare_window(self, master)
        self.payment_token = uuid4().hex
        self.session = session
        self.czlonek = czlonek
        self.on_success_callback = on_success_callback

        self.title(f"Dodaj składkę - {czlonek.imie_nazwisko}")
        self.geometry("400x350")
        self.lift()

        # Nagłówek
        self.lbl_title = ctk.CTkLabel(self, text="Wprowadź pojedynczą składkę", font=("Segoe UI", 16, "bold"))
        self.lbl_title.pack(pady=(15, 5))

        info_text = f"Klient: {czlonek.imie_nazwisko} (ID A!{czlonek.numer_identyfikacyjny})\nObecne saldo: {czlonek.bilans_otwarcia:.2f} PLN"
        ctk.CTkLabel(self, text=info_text, text_color="gray", justify="center").pack(pady=(0, 15))

        # Pole 1: Data
        self.lbl_data = ctk.CTkLabel(self, text="Data (RRRR-MM-DD):")
        self.lbl_data.pack(anchor="w", padx=50)
        self.entry_data = ctk.CTkEntry(self, width=300)
        self.entry_data.pack(pady=(0, 10))
        # Automatycznie wpisujemy dzisiejszą datę dla wygody
        self.entry_data.insert(0, datetime.today().strftime('%Y-%m-%d'))

        # Pole 2: Kwota (Zamiast ID, bo ID mamy z Selektora)
        self.lbl_kwota = ctk.CTkLabel(self, text="Kwota (PLN):")
        self.lbl_kwota.pack(anchor="w", padx=50)
        self.entry_kwota = ctk.CTkEntry(self, width=300)
        self.entry_kwota.pack(pady=(0, 20))

        # Przycisk Zapisz
        self.btn_zapisz = ctk.CTkButton(
            self, text="DODAJ WPŁATĘ", command=self.process_payment,
            fg_color="#18735D", hover_color="#105B49", font=("Segoe UI", 13, "bold")
        )
        pack_footer(self.btn_zapisz)

    def process_payment(self):
        data_str = self.entry_data.get().strip()
        kwota_str = self.entry_kwota.get().strip()

        # Zdejmujemy atrybut topmost na chwilę, żeby messagebox był poprawnie widoczny
        self.attributes("-topmost", False)

        # 1. Najpierw sprawdzamy puste pola (wcześniej ten warunek był nieosiągalny)
        if not data_str or not kwota_str:
            messagebox.showerror("Błąd", "Pola z datą i kwotą nie mogą być puste.", parent=self)
            self.lift()
            return

        # 2. Walidacja wpisanych danych i konwersja typów
        try:
            kwota = parse_amount(kwota_str)
            # Konwersja tekstu na obiekt daty wymagany przez bazę danych
            data_obj = datetime.strptime(data_str, '%Y-%m-%d')
        except ValueError:
            messagebox.showerror(
                "Błąd",
                "Błędne dane! Sprawdź czy data to RRRR-MM-DD, a Kwota to liczba.",
                parent=self
            )
            self.lift()
            return

        # 3. Wyświetlenie potwierdzenia z danymi z bazy
        pytanie = (
            f"Czy na pewno chcesz dodać wpłatę składki o wysokości {kwota} PLN\n"
            f"dla klienta: {self.czlonek.imie_nazwisko}\n"
            f"Data księgowania: {data_str}?"
        )

        potwierdzenie = messagebox.askyesno("Potwierdź operację", pytanie, parent=self)

        # 4. Zapis do bazy danych
        if potwierdzenie:
            try:
                record_payment(self.session,self.czlonek.id,kwota_str,data_obj,self.payment_token)

                messagebox.showinfo("Sukces", "Wpłata została pomyślnie zapisana w historii i dodana do salda.",
                                    parent=self)

                if self.on_success_callback:
                    self.on_success_callback()

                self.destroy()  # Zamykamy okienko po udanym dodaniu
            except ValueError as exc:
                messagebox.showerror("Nie zapisano",str(exc),parent=self)
                self.lift()
            except Exception:
                messagebox.showerror("Błąd zapisu", "Nie zapisano wpłaty. Sprawdź dostęp do bazy i spróbuj ponownie.", parent=self)
                self.lift()
        else:
            # Jeśli kliknięto "Nie", po prostu wracamy do aktywnego okienka
            self.lift()