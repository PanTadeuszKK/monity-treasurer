from mail_content import payment_details, text_to_html
from member_search import name_matches
from frames.member_selector import MemberSelectorWindow
from ui import pack_footer, prepare_window, MonityToplevel, register_job
import customtkinter as ctk
from tkinter import messagebox
import json
import os
from datetime import datetime
from models import Czlonek, Wplata
from mailer import Mailer, load_email_config
from mail_service import prepare_single, send_campaign, delivery_rows
import html
import queue
import threading
from decimal import Decimal

from opening_balance import opening_balances, opening_description



class SendReminderWindow(MonityToplevel):
    def __init__(self, master, session, **kwargs):
        super().__init__(master, **kwargs)
        prepare_window(self, master)
        self.session = session
        self.czlonek = None
        self.tabela_html = ""
        self.mail_results = queue.Queue()
        self.poll_id = None
        self.bind("<Destroy>", self._on_destroy, add="+")

        self.title("Wyślij monit do klienta")
        self.geometry("600x750")
        self.lift()

        self.config_email = self.load_config()
        self.mail_ready = bool(self.config_email.get("email") and self.config_email.get("haslo"))

        self.lbl_title = ctk.CTkLabel(self, text="Indywidualne powiadomienie (HTML)", font=("Segoe UI", 16, "bold"))
        self.lbl_title.pack(pady=(20, 10))

        self.frame_search = ctk.CTkFrame(self, fg_color="transparent")
        self.frame_search.pack(fill="x", padx=40, pady=5)

        self.lbl_id = ctk.CTkLabel(self.frame_search, text="Klient:")
        self.lbl_id.pack(side="left")

        self.entry_id = ctk.CTkEntry(self.frame_search, width=220, placeholder_text="Imię lub nazwisko")
        self.entry_id.pack(side="left", padx=10, fill="x", expand=True)
        self.entry_name = self.entry_id
        self.entry_name.bind("<Return>",lambda event:self.szukaj_czlonka())

        self.btn_szukaj = ctk.CTkButton(
            self.frame_search, text="Szukaj", width=80,
            command=self.szukaj_czlonka, fg_color="#203B5D"
        )
        self.btn_szukaj.pack(side="left")

        self.frame_info = ctk.CTkFrame(self, fg_color="#F9F9F9", border_width=1, border_color="#DDDDDD")
        self.frame_info.pack(fill="x", padx=40, pady=15)

        self.lbl_imie = ctk.CTkLabel(self.frame_info, text="Wyszukaj klienta...", font=("Segoe UI", 14, "bold"),
                                     text_color="black")
        self.lbl_imie.pack(pady=(10, 2))

        self.lbl_email = ctk.CTkLabel(self.frame_info, text="Email: ---", text_color="gray")
        self.lbl_email.pack()

        self.lbl_saldo = ctk.CTkLabel(self.frame_info, text="Saldo: --- PLN", font=("Segoe UI", 16, "bold"),
                                      text_color="black")
        self.lbl_saldo.pack(pady=(5, 10))

        self.frame_msg = ctk.CTkFrame(self, fg_color="transparent")
        self.frame_msg.pack(fill="both", expand=True, padx=40, pady=5)

        self.lbl_temat = ctk.CTkLabel(self.frame_msg, text="Temat wiadomości:", font=("Segoe UI", 12, "bold"))
        self.lbl_temat.pack(anchor="w")

        self.entry_temat = ctk.CTkEntry(self.frame_msg, width=520)
        self.entry_temat.insert(0, "Zestawienie opłat abonamentowych")
        self.entry_temat.pack(fill="x", pady=(0, 10))

        self.lbl_tresc = ctk.CTkLabel(self.frame_msg,
                                      text="Treść wiadomości (w miejscu [TABELA_WPLAT] wstawiona zostanie profesjonalna ramka):",
                                      font=("Segoe UI", 11, "bold"))
        self.lbl_tresc.pack(anchor="w")

        self.txt_tresc = ctk.CTkTextbox(self.frame_msg, width=520, height=280, font=("Segoe UI", 12))
        self.txt_tresc.pack(fill="both", expand=True, pady=(0, 10))
        self.txt_tresc.configure(state="disabled")

        self.btn_wyslij = ctk.CTkButton(
            self, text="WYŚLIJ WIADOMOŚĆ (HTML)", command=self.wyslij_monit,
            fg_color="#18735D", hover_color="#105B49", font=("Segoe UI", 13, "bold"), height=40, state="disabled"
        )
        pack_footer(self.btn_wyslij)

    def load_config(self):
        return load_email_config()

    def _on_destroy(self, event):
        if event.widget is self and self.poll_id:
            self.after_cancel(self.poll_id)
            self.poll_id = None

    def szukaj_czlonka(self):
        query = self.entry_name.get().strip()
        matches = [m for m in self.session.query(Czlonek).order_by(Czlonek.imie_nazwisko)
                   if name_matches(m.imie_nazwisko,query)]
        if query and len(matches)==1:
            self.wczytaj_czlonka(matches[0])
            return
        self.wczytaj_czlonka(None)
        MemberSelectorWindow(self,self.session,'Wybierz klienta', 'WYBIERZ CZŁONKA',
                             self.wczytaj_czlonka,include_archived=True,initial_query=query)

    def wczytaj_czlonka(self, member):
        self.czlonek = member
        if member is not None:
            self.entry_name.delete(0,'end')
            self.entry_name.insert(0,member.imie_nazwisko)

        if not self.czlonek:
            self.lbl_imie.configure(text="Nie znaleziono w bazie!", text_color="red")
            self.lbl_email.configure(text="Email: ---")
            self.lbl_saldo.configure(text="Saldo: --- PLN", text_color="black")
            self.btn_wyslij.configure(state="disabled")
            self.txt_tresc.configure(state="normal")
            self.txt_tresc.delete("1.0","end")
            self.txt_tresc.configure(state="disabled")
            self.tabela_html = ""
            return

        self.lbl_imie.configure(text=self.czlonek.imie_nazwisko, text_color="black")
        email_str = self.czlonek.email if self.czlonek.email else "BRAK ADRESU W BAZIE!"
        kolor_email = "red" if not self.czlonek.email else "gray"
        self.lbl_email.configure(text=f"Email: {email_str}", text_color=kolor_email)

        saldo = Decimal(str(self.czlonek.bilans_otwarcia or 0))
        if saldo >= 0:
            self.lbl_saldo.configure(text=f"Saldo: +{saldo:.2f} PLN", text_color="#18735D")
        else:
            self.lbl_saldo.configure(text=f"Saldo: {saldo:.2f} PLN", text_color="#B65348")

        now = datetime.now()
        if now.month >= 6:
            rok_start = now.year
        else:
            rok_start = now.year - 1
        rok_koniec = rok_start + 1

        data_od = datetime(rok_start, 6, 1)
        data_do = datetime(rok_koniec, 5, 31, 23, 59, 59)

        wplaty = self.session.query(Wplata).filter(
            Wplata.czlonek_id == self.czlonek.id,
            Wplata.data_przelewu >= data_od,
            Wplata.data_przelewu <= data_do
        ).all()

        miesiace = [
            (6, "Czerwiec"), (7, "Lipiec"), (8, "Sierpień"), (9, "Wrzesień"),
            (10, "Październik"), (11, "Listopad"), (12, "Grudzień"),
            (1, "Styczeń"), (2, "Luty"), (3, "Marzec"), (4, "Kwiecień"), (5, "Maj")
        ]

        wplaty_mc = {m_num: Decimal(0) for m_num, m_nazwa in miesiace}
        for w in wplaty:
            if w.data_przelewu.month in wplaty_mc:
                wplaty_mc[w.data_przelewu.month] += Decimal(str(w.kwota))

        suma_okresu = sum(wplaty_mc.values())
        opening = opening_description(opening_balances(self.session,rok_start).get(self.czlonek.id),rok_start)

        self.tabela_html = f"""
        <table style="border-collapse: collapse; width: 100%; max-width: 480px; margin: 20px 0; font-family: 'Segoe UI', Arial, sans-serif; box-shadow: 0 2px 5px rgba(0,0,0,0.1);">
            <thead>
                <tr style="background-color: #203B5D; color: white;">
                    <th style="padding: 12px; border: 1px solid #203B5D; text-align: left;">Tytuł / Miesiąc</th>
                    <th style="padding: 12px; border: 1px solid #203B5D; text-align: right;">Kwota</th>
                </tr>
            </thead>
            <tbody>
        """

        for i, (m_num, m_nazwa) in enumerate(miesiace):
            bg_color = "#ffffff" if i % 2 == 0 else "#fafafa"
            kwota = wplaty_mc[m_num]

            # Nowa logika kolorowania: wpłaty ujemne na czerwono
            if kwota > 0:
                kolor_kwoty = "#18735D"
            elif kwota < 0:
                kolor_kwoty = "#B65348"
            else:
                kolor_kwoty = "#888888"

            self.tabela_html += f"""
                <tr style="background-color: {bg_color};">
                    <td style="padding: 10px; border: 1px solid #dddddd;">Wpłaty: {m_nazwa}</td>
                    <td style="padding: 10px; border: 1px solid #dddddd; text-align: right; color: {kolor_kwoty};"><b>{kwota:.2f} PLN</b></td>
                </tr>
            """

        self.tabela_html += f"""
            </tbody>
            <tfoot>
                <tr style="background-color: #E8EAF6; color: #203B5D;">
                    <td style="padding: 12px; border: 1px solid #dddddd;"><b>SUMA WPŁAT W OKRESIE</b></td>
                    <td style="padding: 12px; border: 1px solid #dddddd; text-align: right;"><b>{suma_okresu:.2f} PLN</b></td>
                </tr>
                <tr style="background-color: #203B5D; color: white;">
                    <td style="padding: 12px; border: 1px solid #203B5D; font-size: 16px;"><b>AKTUALNE SALDO</b></td>
                    <td style="padding: 12px; border: 1px solid #203B5D; text-align: right; font-size: 16px;"><b>{saldo:.2f} PLN</b></td>
                </tr>
            </tfoot>
        </table>
        """

        rozliczenie = (f"Do zapłaty na dziś: {max(-saldo, Decimal(0)):.2f} PLN. "
                       f"Nadpłata na dziś: {max(saldo, Decimal(0)):.2f} PLN "
                       "(względem dotychczas naliczonych składek).")

        if saldo < 0:
            tresc_wezwania = (
                "Prosimy o uregulowanie należności na rachunek podany poniżej."
            )
        elif saldo > 0:
            tresc_wezwania = (
                "Kolejne naliczenia mogą wykorzystać wykazaną wyżej nadpłatę."
            )
        else:
            tresc_wezwania = "Saldo jest rozliczone. Dziękuję za wpłaty."

        szablon = (
            f"Dzień dobry,\n\n"
            f"Przesyłamy informację o aktualnym\n"
            f"stanie rozliczeń z tytułu opłat abonamentowych.\n\n"
            f"Poniżej przedstawiam szczegółowe zestawienie zaksięgowanych operacji\n"
            f"w trwającym okresie rozliczeniowym ({rok_start}/{rok_koniec}):\n\n"
            f"{opening}\n{rozliczenie}\n\n"
            f"[TABELA_WPLAT]\n\n"
            f"{tresc_wezwania}\n\n"
            f"{payment_details(self.czlonek.imie_nazwisko,self.czlonek.numer_identyfikacyjny)}\n\n"
            f"Z poważaniem,\n"
            f"Obsługa rozliczeń"
        )

        self.txt_tresc.configure(state="normal")
        self.txt_tresc.delete("1.0", "end")
        self.txt_tresc.insert("1.0", szablon)

        if self.czlonek.email and self.mail_ready:
            self.btn_wyslij.configure(state="normal")
        else:
            self.btn_wyslij.configure(state="disabled")

    def wyslij_monit(self):
        if not self.czlonek or not self.czlonek.email or not self.mail_ready:
            return

        adres = self.czlonek.email
        temat = self.entry_temat.get().strip()
        tresc_z_okna = self.txt_tresc.get("1.0", "end").strip()

        tresc_html = text_to_html(tresc_z_okna)
        tresc_html = tresc_html.replace("[TABELA_WPLAT]", self.tabela_html)

        pelny_html = f"""
        <html>
            <body style="font-family: 'Segoe UI', Arial, sans-serif; color: #333333; line-height: 1.6; padding: 20px;">
                {tresc_html}
            </body>
        </html>
        """

        if not messagebox.askyesno("Potwierdź wysyłkę",
            f"Odbiorca: {adres}\nTemat: {temat}\n\n"
            "Treść widoczna jest w edytorze. Tabela zawiera wpłaty i aktualne saldo.\n"
            "Czy wysłać jedną wiadomość do tego odbiorcy?", parent=self):
            return
        try:
            campaign = prepare_single(self.session, self.czlonek.id, self.config_email['email'],
                                      adres, temat, pelny_html, is_html=True)
        except ValueError as exc:
            messagebox.showerror('Nie rozpoczęto wysyłki',str(exc),parent=self)
            return
        self.btn_wyslij.configure(text="Wysyłanie…", state="disabled")
        self.btn_szukaj.configure(state="disabled")
        self.entry_id.configure(state="disabled")
        self.entry_temat.configure(state="disabled")
        self.txt_tresc.configure(state="disabled")
        config, engine = dict(self.config_email), self.session.get_bind()
        stop = threading.Event()
        def work():
            try:
                send_campaign(engine,campaign,config,stop,interval=0)
                row = delivery_rows(engine,campaign)[0]
                self.mail_results.put(((row['state']=='accepted',row['info']),row['state']))
            except Exception:
                self.mail_results.put(((False,'Sprawdź trwały rejestr wysyłek przed ponowieniem.'),'uncertain'))
        worker=threading.Thread(target=work,daemon=True)
        register_job(self,worker,stop)
        worker.start()
        self.poll_id=self.after(100,self._poll_mail)

    def _poll_mail(self):
        self.poll_id=None
        try:
            (success,info),state=self.mail_results.get_nowait()
        except queue.Empty:
            self.poll_id=self.after(100,self._poll_mail)
            return
        if success:
            messagebox.showinfo('Wynik wysyłki',info,parent=self)
            self.destroy()
            return
        messagebox.showerror('Wynik wysyłki',info,parent=self)
        if state in ('uncertain','sending'):
            self.btn_wyslij.configure(text='Sprawdź folder Wysłane przed ponowieniem',state='disabled')
        else:
            self.btn_wyslij.configure(text='WYŚLIJ WIADOMOŚĆ (HTML)',state='normal')
            self.btn_szukaj.configure(state='normal')
            self.entry_id.configure(state='normal')
            self.entry_temat.configure(state='normal')
            self.txt_tresc.configure(state='normal')
