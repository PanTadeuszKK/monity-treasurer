from ui import pack_footer, prepare_window, MonityToplevel
import customtkinter as ctk
from tkinter import messagebox
from models import Czlonek, Status
from datetime import date
from sqlalchemy import text, inspect
from sqlalchemy.orm import Session
from member_status import change_status
from annual_fees import cadence_year
from opening_balance import opening_balances, record_opening
from decimal import Decimal


class EditMemberWindow(MonityToplevel):
    def __init__(self, master, session, czlonek, on_success_callback=None, **kwargs):
        super().__init__(master, **kwargs)
        prepare_window(self, master)
        self.session = session
        self.czlonek = czlonek
        self.statusy_map = {}
        self.on_success_callback = on_success_callback

        self.title(f"Edycja klienta - {czlonek.imie_nazwisko}")
        self.geometry("500x760")  # Zwiększono wysokość, aby pomieścić nowe pola
        self.lift()

        self.lbl_title = ctk.CTkLabel(self, text=f"Zmień dane: {czlonek.imie_nazwisko}", font=("Segoe UI", 16, "bold"))
        self.lbl_title.pack(pady=(20, 5))

        self.frame_edit = ctk.CTkScrollableFrame(self, fg_color="#F9F9F9", border_width=1, border_color="#DDDDDD")
        self.frame_edit.pack(fill="both", expand=True, padx=30, pady=10)

        self.lbl_nowe_id = ctk.CTkLabel(self.frame_edit, text="Nowe ID A!:", text_color="black",
                                        font=("Segoe UI", 12, "bold"))
        self.lbl_nowe_id.pack(anchor="w", padx=20, pady=(5, 0))
        self.entry_nowe_id = ctk.CTkEntry(self.frame_edit, width=300, text_color="black", fg_color="white")
        self.entry_nowe_id.insert(0, str(czlonek.numer_identyfikacyjny))
        self.entry_nowe_id.pack(padx=20, pady=(0, 5))

        self.lbl_imie = ctk.CTkLabel(self.frame_edit, text="Imię i Nazwisko:", text_color="black",
                                     font=("Segoe UI", 12, "bold"))
        self.lbl_imie.pack(anchor="w", padx=20)
        self.entry_imie = ctk.CTkEntry(self.frame_edit, width=300, text_color="black", fg_color="white")
        self.entry_imie.insert(0, czlonek.imie_nazwisko)
        self.entry_imie.pack(padx=20, pady=(0, 5))

        self.lbl_email = ctk.CTkLabel(self.frame_edit, text="Email:", text_color="black", font=("Segoe UI", 12, "bold"))
        self.lbl_email.pack(anchor="w", padx=20)
        self.entry_email = ctk.CTkEntry(self.frame_edit, width=300, text_color="black", fg_color="white")
        if czlonek.email:
            self.entry_email.insert(0, czlonek.email)
        self.entry_email.pack(padx=20, pady=(0, 5))

        self.lbl_status = ctk.CTkLabel(self.frame_edit, text="Status:", text_color="black", font=("Segoe UI", 12, "bold"))
        self.lbl_status.pack(anchor="w", padx=20)

        # Pobieranie statusów z bazy do Dropdowna
        self.pobierz_statusy()
        opcje_statusow = list(self.statusy_map.keys()) if self.statusy_map else ["Brak statusów w bazie"]

        self.dropdown_status = ctk.CTkOptionMenu(
            self.frame_edit, values=opcje_statusow, width=300,
            text_color="black", fg_color="white", button_color="#E0E0E0", button_hover_color="#D0D0D0"
        )
        self.dropdown_status.pack(padx=20, pady=(0, 10))

        # Ustawianie obecnego statusu w Dropdownie
        status_obj = self.session.query(Status).filter_by(id=self.czlonek.status_id).first()
        if status_obj and status_obj.nazwa in self.statusy_map:
            self.dropdown_status.set(status_obj.nazwa)

        ctk.CTkLabel(self.frame_edit, text="Nowy status obowiązuje od (miesiąc / rok):",
                     text_color="black").pack(anchor="w", padx=20)
        status_date = ctk.CTkFrame(self.frame_edit, fg_color="transparent")
        status_date.pack(padx=20, pady=(0, 8))
        today = date.today()
        self.entry_status_month = ctk.CTkEntry(status_date, width=140)
        self.entry_status_month.insert(0, '6')
        self.entry_status_month.pack(side="left", padx=(0, 10))
        self.entry_status_year = ctk.CTkEntry(status_date, width=140)
        self.entry_status_year.insert(0, str(today.year if today.month >= 6 else today.year - 1))
        self.entry_status_year.pack(side="left")
        ctk.CTkLabel(self.frame_edit, text="Przy zmianie statusu system skoryguje zapisane należności\nod tego miesiąca; wpłaty pozostaną bez zmian.", wraplength=370).pack(pady=3)

        self.opening_year = cadence_year(today.year,today.month)
        ctk.CTkLabel(self.frame_edit,text=f"Saldo początkowe kadencji {self.opening_year}/{self.opening_year+1} (PLN):").pack(padx=20)
        self.entry_opening = ctk.CTkEntry(self.frame_edit,width=300,placeholder_text="Nieuzupełnione; minus = zaległość, plus = nadpłata")
        saved_opening = opening_balances(self.session,self.opening_year).get(czlonek.id)
        if saved_opening is not None:
            self.entry_opening.insert(0,format(Decimal(saved_opening)/100,".2f"))
        self.entry_opening.pack(padx=20,pady=5)
        ctk.CTkLabel(self.frame_edit,text="Informacja o kwocie przeniesionej na 1 czerwca do maila.\nUzupełnienie nie nalicza jej drugi raz i nie zmienia bieżącego salda.",wraplength=370).pack(padx=20,pady=3)

        ctk.CTkFrame(self.frame_edit, height=1, fg_color="#DDDDDD").pack(fill="x", padx=20, pady=5)

        # Dołączenie
        self.lbl_daty_dolaczenia = ctk.CTkLabel(self.frame_edit, text="Data dołączenia (Miesiąc / Rok):",
                                                text_color="black", font=("Segoe UI", 11, "bold"))
        self.lbl_daty_dolaczenia.pack(anchor="w", padx=20)
        self.frame_dol = ctk.CTkFrame(self.frame_edit, fg_color="transparent")
        self.frame_dol.pack(fill="x", padx=20, pady=(0, 5))

        self.entry_m_dol = ctk.CTkEntry(self.frame_dol, width=140, placeholder_text="M-c (1-12)", text_color="black",
                                        fg_color="white")
        self.entry_m_dol.pack(side="left", padx=(0, 10))
        if czlonek.miesiac_dolaczenia: self.entry_m_dol.insert(0, str(czlonek.miesiac_dolaczenia))

        self.entry_r_dol = ctk.CTkEntry(self.frame_dol, width=140, placeholder_text="Rok (np. 2024)",
                                        text_color="black", fg_color="white")
        self.entry_r_dol.pack(side="left")
        if czlonek.rok_dolaczenia: self.entry_r_dol.insert(0, str(czlonek.rok_dolaczenia))

        # Odejście
        self.lbl_daty_odejscia = ctk.CTkLabel(self.frame_edit, text="Data odejścia (tylko zarchiwizowani):",
                                              text_color="gray", font=("Segoe UI", 11, "bold"))
        self.lbl_daty_odejscia.pack(anchor="w", padx=20)
        self.frame_od = ctk.CTkFrame(self.frame_edit, fg_color="transparent")
        self.frame_od.pack(fill="x", padx=20, pady=(0, 10))

        self.entry_m_od = ctk.CTkEntry(self.frame_od, width=140, placeholder_text="M-c (1-12)", text_color="black",
                                       fg_color="white")
        self.entry_m_od.pack(side="left", padx=(0, 10))
        if czlonek.miesiac_odejscia: self.entry_m_od.insert(0, str(czlonek.miesiac_odejscia))

        self.entry_r_od = ctk.CTkEntry(self.frame_od, width=140, placeholder_text="Rok (np. 2026)", text_color="black",
                                       fg_color="white")
        self.entry_r_od.pack(side="left")
        if czlonek.rok_odejscia: self.entry_r_od.insert(0, str(czlonek.rok_odejscia))

        # Switch do aktywacji / dezaktywacji
        self.switch_aktywny = ctk.CTkSwitch(
            self.frame_edit, text="Konto aktywne",
            progress_color="#18735D", text_color="black"
        )
        self.switch_aktywny.pack(pady=10)

        # Ustawienie pozycji switcha zgodnie z bazą
        if self.czlonek.aktywny:
            self.switch_aktywny.select()
        else:
            self.switch_aktywny.deselect()

        # Przycisk Zapisz
        self.btn_zapisz = ctk.CTkButton(
            self, text="ZAPISZ ZMIANY", command=self.zapisz_zmiany,
            fg_color="#18735D", hover_color="#105B49", font=("Segoe UI", 13, "bold"),
            text_color="white"
        )
        pack_footer(self.btn_zapisz)

    def pobierz_statusy(self):
        statusy = self.session.query(Status).all()
        self.statusy_map = {s.nazwa: s.id for s in statusy}

    def zapisz_zmiany(self):
        self.attributes("-topmost", False)

        try:
            nowe_id = int(self.entry_nowe_id.get().strip())
        except ValueError:
            messagebox.showerror("Błąd", "Nowe ID musi być liczbą!", parent=self)
            self.lift()
            return

        nowe_imie = self.entry_imie.get().strip()
        if not nowe_imie:
            messagebox.showerror("Błąd", "Imię i nazwisko nie mogą być puste!", parent=self)
            self.lift()
            return

        # Walidacja dat (dołączenie)
        try:
            m_dol = int(self.entry_m_dol.get().strip())
            r_dol = int(self.entry_r_dol.get().strip())
            if not (1 <= m_dol <= 12):
                raise ValueError("Miesiąc dołączenia musi wynosić od 1 do 12.")
        except ValueError as e:
            messagebox.showerror("Błąd", f"Daty dołączenia muszą być poprawnymi liczbami.\n{e}", parent=self)
            self.lift()
            return

        # Walidacja dat (odejście - dopuszczamy puste pola)
        m_od_str = self.entry_m_od.get().strip()
        r_od_str = self.entry_r_od.get().strip()
        m_od = None
        r_od = None

        if m_od_str or r_od_str:
            try:
                m_od = int(m_od_str)
                r_od = int(r_od_str)
                if not (1 <= m_od <= 12):
                    raise ValueError("Miesiąc odejścia musi wynosić od 1 do 12.")
            except ValueError as e:
                messagebox.showerror("Błąd", f"Daty odejścia muszą być poprawnymi liczbami (lub pozostać puste).\n{e}",
                                     parent=self)
                self.lift()
                return

        wybrany_status_nazwa = self.dropdown_status.get()
        nowy_status_id = self.statusy_map.get(wybrany_status_nazwa)

        try:
            if nowy_status_id is None:
                raise ValueError("Wybierz status klienta.")
            effective = date(int(self.entry_status_year.get()), int(self.entry_status_month.get()), 1)
            date(r_dol, m_dol, 1)
            if r_od and date(r_od, m_od, 1) < date(r_dol, m_dol, 1):
                raise ValueError("Odejście nie może poprzedzać dołączenia.")
            if not self.switch_aktywny.get() and not (r_od and m_od):
                raise ValueError("Dla osoby zarchiwizowanej podaj miesiąc i rok odejścia.")
            member_id = inspect(self.czlonek).identity[0]
            with Session(bind=self.session.get_bind()) as operation:
                operation.execute(text('BEGIN IMMEDIATE'))
                member = operation.get(Czlonek, member_id)
                member.rok_dolaczenia, member.miesiac_dolaczenia = r_dol, m_dol
                member.rok_odejscia, member.miesiac_odejscia = r_od, m_od
                member.numer_identyfikacyjny = nowe_id
                member.imie_nazwisko = nowe_imie
                member.email = self.entry_email.get().strip()
                member.aktywny = bool(self.switch_aktywny.get())
                change_status(operation, member, nowy_status_id, effective)
                if self.entry_opening.get().strip():
                    record_opening(operation,member_id,self.opening_year,self.entry_opening.get().strip(),"Edycja kartoteki — potwierdzenie administratora")
                operation.commit()
            self.session.expire(self.czlonek)
            messagebox.showinfo("Sukces", "Dane klienta zostały zaktualizowane!", parent=self)
            if self.on_success_callback:
                self.on_success_callback()
            self.destroy()
        except ValueError as exc:
            messagebox.showerror("Błąd zapisu", str(exc), parent=self)
            self.lift()
        except Exception:
            messagebox.showerror("Błąd zapisu",
                                 "Nie udało się zapisać zmian. Sprawdź, czy ID nie jest zajęte. Nie zapisano części zmian.",
                                 parent=self)
            self.lift()