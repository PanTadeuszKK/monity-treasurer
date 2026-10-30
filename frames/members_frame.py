from ui import pack_footer, prepare_window, MonityToplevel
import customtkinter as ctk
from tkinter import messagebox
from models import Czlonek, Status, KontoBankowe
from sqlalchemy import func
from datetime import date
from finance_service import add_member


class AddMemberWindow(MonityToplevel):
    def __init__(self, master, session, on_save_callback, **kwargs):
        super().__init__(master, **kwargs)
        prepare_window(self, master)

        self.session = session
        self.on_save_callback = on_save_callback

        self.title("Dodaj nowego klienta")
        self.geometry("500x650")  # Lekko powiększone okno, żeby zmieścić przełącznik
        self.lift()

        self.form = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.form.pack(fill="both", expand=True, padx=14, pady=8)

        ctk.CTkLabel(self.form, text="Dane nowego klienta", font=("Segoe UI", 16, "bold")).pack(pady=20)

        self.entry_name = ctk.CTkEntry(self.form, placeholder_text="Imię i Nazwisko", width=300)
        self.entry_name.pack(pady=10)

        self.entry_email = ctk.CTkEntry(self.form, placeholder_text="Adres Email", width=300)
        self.entry_email.pack(pady=10)

        self.lbl_id_info = ctk.CTkLabel(
            self.form, text="Numer ID A! zostanie nadany automatycznie",
            text_color="gray", font=("Segoe UI", 11, "italic")
        )
        self.lbl_id_info.pack(pady=5)

        self.statusy_map = {status.nazwa: status.id for status in self.session.query(Status).order_by(Status.nazwa)}
        status_names = list(self.statusy_map) or ["Brak statusów w bazie"]
        ctk.CTkLabel(self.form, text="Status członkowski:").pack()
        self.status_var = ctk.StringVar(value="Premium" if "Premium" in self.statusy_map else status_names[0])
        self.status_dropdown = ctk.CTkOptionMenu(
            self.form,
            values=status_names,
            variable=self.status_var,
            width=300
        )
        self.status_dropdown.pack(pady=10)

        self.entry_bank = ctk.CTkEntry(self.form, placeholder_text="Numer konta bankowego (opcjonalnie)", width=300)
        self.entry_bank.pack(pady=10)

        self.entry_bilans = ctk.CTkEntry(self.form, placeholder_text="Saldo początkowe, np. -35 lub 0", width=300)
        self.entry_bilans.pack(pady=10)
        ctk.CTkLabel(self.form,text="Saldo przeniesione do bieżącej kadencji: minus = zaległość, plus = nadpłata.\nPuste pole oznacza 0 PLN; kwota zostanie zachowana w mailach.",wraplength=360).pack(padx=12)

        self.switch_wpisowe_var = ctk.BooleanVar(value=False)
        self.switch_wpisowe = ctk.CTkSwitch(
            self.form, text="Wpisowe: 3 × bazowa składka Standard",
            variable=self.switch_wpisowe_var,
            onvalue=True, offvalue=False,
            progress_color="#18735D"
        )
        self.switch_wpisowe.pack(pady=15)

        ctk.CTkLabel(self.form, text="Dołączenie (miesiąc / rok):").pack()
        joined_frame = ctk.CTkFrame(self.form, fg_color="transparent")
        joined_frame.pack(pady=5)
        self.entry_join_month = ctk.CTkEntry(joined_frame, width=140)
        self.entry_join_month.insert(0,str(date.today().month))
        self.entry_join_month.pack(side="left", padx=5)
        self.entry_join_year = ctk.CTkEntry(joined_frame, width=140)
        self.entry_join_year.insert(0,str(date.today().year))
        self.entry_join_year.pack(side="left", padx=5)
        ctk.CTkLabel(self.form, text="Zapis doliczy składki od miesiąca dołączenia za miesiące już naliczone w aplikacji.", wraplength=360).pack(padx=12, pady=8)
        self.btn_save = ctk.CTkButton(
            self,
            text="Zapisz w bazie",
            fg_color="#18735D",
            hover_color="#105B49",
            command=self.save_member,
            state="normal" if self.statusy_map else "disabled"
        )
        pack_footer(self.btn_save)

    def save_member(self):
        try:
            public_id, balance = add_member(self.session,self.entry_name.get(),self.entry_email.get(),
                self.statusy_map.get(self.status_var.get()),self.entry_bilans.get(),self.entry_bank.get(),
                date(int(self.entry_join_year.get()),int(self.entry_join_month.get()),1),
                bool(self.switch_wpisowe_var.get()))
            messagebox.showinfo("Zapisano",f"Dodano klienta A!{public_id}. Saldo: {balance:.2f} PLN.",parent=self)
            if self.on_save_callback:
                self.on_save_callback()
            self.destroy()
        except ValueError as exc:
            messagebox.showerror("Nie zapisano",str(exc),parent=self)
        except Exception:
            messagebox.showerror("Nie zapisano","Operacja nie powiodła się. Nie zapisano części danych.",parent=self)


class MembersFrame(ctk.CTkFrame):
    def __init__(self, master, session, mailer, kalkulator, **kwargs):
        super().__init__(master, **kwargs)

        self.session = session
        self.mailer = mailer
        self.kalkulator = kalkulator

        # UI górne
        self.header = ctk.CTkLabel(self, text="Zarządzanie Klientami", font=("Segoe UI", 20, "bold"))
        self.header.pack(pady=10)

        self.btn_add = ctk.CTkButton(
            self,
            text="+ DODAJ NOWEGO CZŁONKA",
            command=self.open_add_window,
            height=40,
            font=("Segoe UI", 13, "bold")
        )
        self.btn_add.pack(pady=10)

        self.label_lista = ctk.CTkLabel(self, text="(Tutaj pojawi się tabela po odświeżeniu)")
        self.label_lista.pack(pady=20)

    def open_add_window(self):
        AddMemberWindow(
            master=self,
            session=self.session,
            on_save_callback=self.refresh_data
        )

    def refresh_data(self):
        print("Dane w bazie zmienione - odświeżam widok...")
        self.label_lista.configure(text="Lista odświeżona! (Zaimplementuj pętlę wyświetlania)")
