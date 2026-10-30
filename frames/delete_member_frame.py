from ui import prepare_window, MonityToplevel
import customtkinter as ctk
from tkinter import messagebox
from datetime import datetime


class DeleteMemberWindow(MonityToplevel):
    def __init__(self, master, session, czlonek, on_success_callback=None, **kwargs):
        super().__init__(master, **kwargs)
        prepare_window(self, master)
        self.session = session
        self.czlonek = czlonek
        self.on_success_callback = on_success_callback

        self.title(f"Archiwizuj klienta - {czlonek.imie_nazwisko}")
        self.geometry("450x350")
        self.lift()

        self.lbl_title = ctk.CTkLabel(self, text="Archiwizacja klienta", font=("Segoe UI", 16, "bold"), text_color="#B65348")
        self.lbl_title.pack(pady=(20, 5))

        info_text = f"Klient: {czlonek.imie_nazwisko}\nID A!: {czlonek.numer_identyfikacyjny}\nObecne saldo: {czlonek.bilans_otwarcia:.2f} PLN"
        self.lbl_info = ctk.CTkLabel(self, text=info_text, text_color="black", font=("Segoe UI", 13))
        self.lbl_info.pack(pady=10)

        warning_text = (
            "Kartoteka i cała historia finansowa zostaną zachowane.\n"
            "Archiwizacja zapisuje bieżący miesiąc jako miesiąc odejścia."
        )
        btn_text = "ZARCHIWIZUJ CZŁONKA"

        self.lbl_warning = ctk.CTkLabel(self, text=warning_text, text_color="gray", justify="center")
        self.lbl_warning.pack(pady=(10, 20))

        self.btn_usun = ctk.CTkButton(
            self, text=btn_text, command=self.usun_czlonka,
            fg_color="#B65348", hover_color="#b32d2d", font=("Segoe UI", 13, "bold"), height=40
        )
        self.btn_usun.pack(pady=10)

    def usun_czlonka(self):
        self.attributes("-topmost", False)
        if not self.czlonek.aktywny:
            messagebox.showinfo("Archiwum", "Klient jest już zarchiwizowany. Data odejścia pozostaje bez zmian.", parent=self)
            self.lift()
            return
        if messagebox.askyesno("Archiwizacja", "Czy zarchiwizować klienta z bieżącym miesiącem odejścia?", parent=self):
            try:
                self.czlonek.aktywny = False
                today = datetime.now()
                self.czlonek.rok_odejscia = today.year
                self.czlonek.miesiac_odejscia = today.month
                self.session.commit()
            except Exception:
                self.session.rollback()
                messagebox.showerror("Błąd bazy", "Nie udało się zarchiwizować klienta.", parent=self)
            else:
                messagebox.showinfo("Sukces", "Kartoteka została zarchiwizowana. Saldo i historia są zachowane.", parent=self)
                if self.on_success_callback:
                    self.on_success_callback()
                self.destroy()
                return
        self.lift()
