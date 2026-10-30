from ui import prepare_window, MonityToplevel
import customtkinter as ctk
from tkinter import messagebox, filedialog
import pandas as pd
from models import Czlonek, Status, Wplata
from datetime import datetime
from decimal import Decimal


class MonthlyStatsWindow(MonityToplevel):
    def __init__(self, master, session, **kwargs):
        super().__init__(master, **kwargs)
        prepare_window(self, master)
        self.session = session

        self.title("Bieżące salda i zaległości")
        self.geometry("900x700")
        self.lift()

        self.header = ctk.CTkFrame(self, fg_color="transparent")
        self.header.pack(fill="x", padx=20, pady=20)

        self.lbl_title = ctk.CTkLabel(self.header, text="Bieżące salda", font=("Segoe UI", 20, "bold"))
        self.lbl_title.pack(side="left", padx=10)

        ctk.CTkLabel(self.header,text="Stan na dziś",text_color="#65758A").pack(side="left",padx=10)

        # Przycisk Generuj
        self.btn_gen = ctk.CTkButton(self.header, text="Odśwież zestawienie", command=self.generuj_raport,
                                     fg_color="#203B5D")
        self.btn_gen.pack(side="left", padx=10)

        # Przycisk Eksport
        self.btn_export = ctk.CTkButton(self.header, text="Eksportuj do Excela", command=self.export_to_excel,
                                        fg_color="#18735D", state="disabled")
        self.btn_export.pack(side="left", padx=10)

        self.info_frame = ctk.CTkFrame(self, fg_color="#F9F9F9")
        self.info_frame.pack(fill="x", padx=20, pady=10)

        self.lbl_total_balance = ctk.CTkLabel(self.info_frame, text="Łączne saldo: --- PLN", font=("Segoe UI", 16, "bold"),
                                              text_color="black")
        self.lbl_total_balance.pack(pady=10)

        self.charts_frame = ctk.CTkFrame(self, fg_color="white")
        self.charts_frame.pack(fill="both", expand=True, padx=20, pady=10)

        self.canvas_plot = None  # Tu będziemy trzymać obiekt wykresu

    def generuj_raport(self):
        # 1. Pobieranie danych z bazy
        czlonkowie = self.session.query(Czlonek).all()

        if not czlonkowie:
            messagebox.showwarning("Brak danych", "Baza klientów jest pusta.", parent=self)
            return

        total_balance = sum((Decimal(str(c.bilans_otwarcia or 0)) for c in czlonkowie),Decimal(0))
        self.lbl_total_balance.configure(text=f"Łączne saldo kartotek, także archiwum: {total_balance:.2f} PLN")

        # 2. Przygotowanie danych pod wykresy
        # Struktura: { 'StatusName': {'Ok': 0, 'Debt': 0} }
        stats = {}
        statusy = self.session.query(Status).all()
        for s in statusy:
            stats[s.nazwa] = {'Ok': 0, 'Debt': 0}

        for c in czlonkowie:
            # Pomijamy klientów bez przypisanego statusu (uniknięcie awarii)
            if not c.status or c.status.nazwa not in stats:
                continue
            status_name = c.status.nazwa
            if c.bilans_otwarcia >= 0:
                stats[status_name]['Ok'] += 1
            else:
                stats[status_name]['Debt'] += 1

        self.rysuj_wykresy(stats)
        self.btn_export.configure(state="normal")
        self.aktualne_stats = stats  # Zapamiętujemy do eksportu

    def rysuj_wykresy(self, stats):
        for widget in self.charts_frame.winfo_children():
            widget.destroy()
        for col, (name, values) in enumerate(stats.items()):
            self.charts_frame.grid_columnconfigure(col, weight=1, uniform='status_charts')
            card=ctk.CTkFrame(self.charts_frame, fg_color='#F3F6FA', corner_radius=14)
            card.grid(row=0,column=col,sticky='nsew',padx=15,pady=25)
            total=values['Ok']+values['Debt']
            ctk.CTkLabel(card,text=name,font=('Segoe UI',21,'bold')).pack(anchor='w',padx=20,pady=(22,5))
            ctk.CTkLabel(card,text=f'{total} klientów',text_color='#65758A').pack(anchor='w',padx=20,pady=(0,20))
            for label,key,color in [('Bez zaległości','Ok','#18735D'),('Z zaległościami','Debt','#B65348')]:
                count=values[key]
                ctk.CTkLabel(card,text=f'{label}   {count}',text_color=color,font=('Segoe UI',14,'bold')).pack(anchor='w',padx=20,pady=(12,8))
                bar=ctk.CTkProgressBar(card,fg_color='#DFE6EE',progress_color=color,height=10)
                bar.set(count/total if total else 0)
                bar.pack(fill='x',padx=20,pady=(0,18))
            if not total:
                ctk.CTkLabel(card,text='Brak osób z tym statusem.',text_color='#65758A').pack(padx=20,pady=15)

    def export_to_excel(self):
        miesiac = datetime.now().strftime("%Y-%m-%d")

        # 1. Zdejmujemy "topmost" na czas wyboru pliku
        self.attributes("-topmost", False)

        path = filedialog.asksaveasfilename(
            parent=self,  # Wymuszamy przypisanie okienka do naszej aplikacji
            defaultextension=".xlsx",
            filetypes=[("Excel files", "*.xlsx")],
            initialfile=f"Raport_{miesiac}_{datetime.now().year}.xlsx"
        )

        if not path:
            # Jeśli użytkownik anulował zapis, przywracamy topmost i wychodzimy
            self.lift()
            return

        try:
            if not hasattr(self, "aktualne_stats"):
                self.generuj_raport()
            # Pobieramy dłużników
            dluznicy = self.session.query(Czlonek).filter(Czlonek.bilans_otwarcia < 0).all()

            data = []
            for d in dluznicy:
                data.append({
                    "Imię i Nazwisko": d.imie_nazwisko,
                    "ID A!": d.numer_identyfikacyjny,
                    "Status": d.status.nazwa if d.status else "Brak",
                    "Saldo (Dług)": d.bilans_otwarcia,
                    "Email": d.email,
                    "Archiwum": "Nie" if d.aktywny else "Tak"
                })

            df = pd.DataFrame(data)

            # Zapis do Excela z użyciem XlsxWriter (pozwala na lepsze formatowanie)
            with pd.ExcelWriter(path, engine='xlsxwriter', engine_kwargs={'options':{'strings_to_formulas':False,'strings_to_urls':False}}) as writer:
                df.to_excel(writer, sheet_name='Lista Dłużników', index=False)

                # Dodatkowe podsumowanie
                summary_data = []
                for s_name, s_val in self.aktualne_stats.items():
                    summary_data.append({"Status": s_name, "Na czysto": s_val['Ok'], "Zadłużeni": s_val['Debt']})

                df_sum = pd.DataFrame(summary_data)
                df_sum.to_excel(writer, sheet_name='Podsumowanie', index=False)

            messagebox.showinfo("Eksport", f"Raport został zapisany w:\n{path}", parent=self)

        except Exception as e:
            messagebox.showerror("Błąd eksportu", f"Nie udało się zapisać pliku: {e}", parent=self)
        finally:
            # 2. Niezależnie od tego, czy wystąpił błąd, czy sukces - przywracamy topmost
            self.lift()