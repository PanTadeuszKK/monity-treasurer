from ui import pack_footer, prepare_window, MonityToplevel, GREEN, GREEN_HOVER, RED, INK, MUTED, NEUTRAL, NEUTRAL_HOVER
import customtkinter as ctk
from tkinter import messagebox
from datetime import datetime


class DuesWindow(MonityToplevel):
    def __init__(self, master, session, kalkulator, on_close_callback=None, **kwargs):
        super().__init__(master, **kwargs)
        prepare_window(self, master)
        self.session = session
        self.kalkulator = kalkulator
        self.on_close_callback = on_close_callback

        self.title("Naliczenia miesięczne")
        self.geometry("550x650")
        self.lift()

        # Ustalanie domyślnego cyklu na podstawie dzisiejszej daty
        now = datetime.now()
        if now.month >= 6:
            self.cykl_start_rok = now.year
        else:
            self.cykl_start_rok = now.year - 1

        # Aktualny miesiąc do zaznaczenia na start
        self.wybrany_miesiac = now.month

        # Lista miesięcy w cyklu Czerwiec-Maj (Krotka: numer miesiąca, nazwa)
        self.miesiace_cyklu = [
            (6, "Czerwiec"), (7, "Lipiec"), (8, "Sierpień"),
            (9, "Wrzesień"), (10, "Październik"), (11, "Listopad"),
            (12, "Grudzień"), (1, "Styczeń"), (2, "Luty"),
            (3, "Marzec"), (4, "Kwiecień"), (5, "Maj")
        ]

        self.frame_rok = ctk.CTkFrame(self, fg_color="transparent")
        self.frame_rok.pack(pady=(20, 10))

        btn_rok_minus = ctk.CTkButton(self.frame_rok, text="<", width=40, command=lambda: self.zmien_cykl(-1))
        btn_rok_minus.pack(side="left", padx=10)

        self.lbl_rok = ctk.CTkLabel(self.frame_rok, text=self.get_cykl_text(), font=("Segoe UI", 24, "bold"))
        self.lbl_rok.pack(side="left", padx=20)

        btn_rok_plus = ctk.CTkButton(self.frame_rok, text=">", width=40, command=lambda: self.zmien_cykl(1))
        btn_rok_plus.pack(side="left", padx=10)

        self.frame_miesiace = ctk.CTkFrame(self, fg_color="transparent")
        self.frame_miesiace.pack(pady=10, padx=16)

        self.przycisk_miesiaca = []

        for i, (num_miesiaca, nazwa) in enumerate(self.miesiace_cyklu):
            btn = ctk.CTkButton(
                self.frame_miesiace, text=nazwa,
                width=140, height=46, font=("Segoe UI", 14, "bold"),
                command=lambda m=num_miesiaca: self.wybierz_miesiac(m)
            )
            row = i // 3
            col = i % 3
            btn.grid(row=row, column=col, padx=6, pady=6)
            self.przycisk_miesiaca.append((num_miesiaca, btn))

        self.legenda = ctk.CTkFrame(self, fg_color="transparent")
        self.legenda.pack(pady=(4, 0))
        for kolor, opis in ((GREEN, "naliczony"), ("#C98A2B", "do naliczenia"), ("#C5D0DC", "przyszły")):
            ctk.CTkLabel(self.legenda, text="", width=14, height=14, corner_radius=4, fg_color=kolor).pack(side="left", padx=(10, 4))
            ctk.CTkLabel(self.legenda, text=opis, text_color=MUTED, font=("Segoe UI", 12)).pack(side="left")
        self.lbl_wybrany = ctk.CTkLabel(self, text="", font=("Segoe UI", 16))
        self.lbl_wybrany.pack(pady=(10, 5))

        self.btn_akcja = ctk.CTkButton(self, text="Wybierz miesiąc", font=("Segoe UI", 14, "bold"), height=46,
                                       width=340, state="disabled")
        pack_footer(self.btn_akcja)

        self.odswiez_widok()

    def get_cykl_text(self):
        """Zwraca tekst np. 'Cykl 2025/2026'"""
        return f"Kadencja {self.cykl_start_rok}/{self.cykl_start_rok + 1}"

    def stan_miesiaca(self, miesiac_num):
        rok = self.get_kalendarzowy_rok(miesiac_num)
        if self.kalkulator.czy_naliczone(rok, miesiac_num):
            return "naliczony"
        now = datetime.now()
        return "przyszły" if (rok, miesiac_num) > (now.year, now.month) else "do naliczenia"

    def get_kalendarzowy_rok(self, miesiac_num):
        """Mapuje miesiąc cyklu na faktyczny rok kalendarzowy dla bazy danych."""
        if miesiac_num >= 6:
            return self.cykl_start_rok
        else:
            return self.cykl_start_rok + 1

    def zmien_cykl(self, wartosc):
        self.cykl_start_rok += wartosc
        self.lbl_rok.configure(text=self.get_cykl_text())
        self.odswiez_widok()

    def odswiez_widok(self):
        """Koloruje przyciski miesięcy w zależności od tego, czy są w bazie."""
        for num_miesiaca, btn in self.przycisk_miesiaca:
            stan = self.stan_miesiaca(num_miesiaca)
            if stan == "naliczony":
                btn.configure(fg_color=GREEN, hover_color=GREEN_HOVER, text_color="white")
            elif stan == "do naliczenia":
                btn.configure(fg_color="#C98A2B", hover_color="#A87120", text_color="white")
            else:
                btn.configure(fg_color=NEUTRAL, hover_color=NEUTRAL_HOVER, text_color=MUTED)

        self.wybierz_miesiac(self.wybrany_miesiac)

    def wybierz_miesiac(self, miesiac_num):
        self.wybrany_miesiac = miesiac_num

        # Szukamy nazwy wybranego miesiąca
        nazwa = next(n for m, n in self.miesiace_cyklu if m == miesiac_num)
        rok_dla_bazy = self.get_kalendarzowy_rok(miesiac_num)
        stan = self.stan_miesiaca(miesiac_num)
        czy_zielony = stan == "naliczony"

        # Efekt wciśnięcia / obramowania
        for m_num, btn in self.przycisk_miesiaca:
            if m_num == miesiac_num:
                btn.configure(border_width=3, border_color=INK)
            else:
                btn.configure(border_width=0)

        self.lbl_wybrany.configure(text=f"Wybrany okres: {nazwa} {rok_dla_bazy} — {stan}")

        if czy_zielony:
            self.btn_akcja.configure(
                text=f"Cofnij naliczenie: {nazwa.lower()}",
                fg_color=RED, hover_color="#8A3F36", state="normal",
                command=self.akcja_zdejmij
            )
        else:
            self.btn_akcja.configure(
                text=f"Nalicz składki: {nazwa.lower()}",
                fg_color=GREEN, hover_color=GREEN_HOVER, state="normal",
                command=self.akcja_dodaj
            )

    def akcja_dodaj(self):
        self.attributes("-topmost", False)
        rok_dla_bazy = self.get_kalendarzowy_rok(self.wybrany_miesiac)
        nazwa = next(n for m, n in self.miesiace_cyklu if m == self.wybrany_miesiac)

        pytanie = f"Naliczyć składki wszystkim klientom za {nazwa.lower()} {rok_dla_bazy}?"
        if self.stan_miesiaca(self.wybrany_miesiac) == "przyszły":
            pytanie = f"UWAGA: {nazwa} {rok_dla_bazy} jeszcze się nie zaczął.\n\n" + pytanie
        if messagebox.askyesno("Potwierdzenie", pytanie, parent=self):
            sukces, msg = self.kalkulator.dodaj_naleznosc(rok_dla_bazy, self.wybrany_miesiac)
            messagebox.showinfo("Informacja", msg, parent=self) if sukces else messagebox.showerror("Błąd", msg,
                                                                                                    parent=self)
            self.odswiez_widok()
            if self.on_close_callback: self.on_close_callback()
        self.lift()

    def akcja_zdejmij(self):
        self.attributes("-topmost", False)
        rok_dla_bazy = self.get_kalendarzowy_rok(self.wybrany_miesiac)
        nazwa = next(n for m, n in self.miesiace_cyklu if m == self.wybrany_miesiac)

        pytanie = (f"Cofnąć naliczenie za {nazwa.lower()} {rok_dla_bazy}?\n"
                   "Potrącone kwoty (z korektami) wrócą na salda klientów; historia zostanie zachowana.")
        if messagebox.askyesno("Ostrzeżenie", pytanie, parent=self):
            sukces, msg = self.kalkulator.zdejmij_naleznosc(rok_dla_bazy, self.wybrany_miesiac)
            messagebox.showinfo("Informacja", msg, parent=self) if sukces else messagebox.showerror("Błąd", msg,
                                                                                                    parent=self)
            self.odswiez_widok()
            if self.on_close_callback: self.on_close_callback()
        self.lift()