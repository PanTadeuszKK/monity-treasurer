from ui import prepare_window, MonityToplevel
import customtkinter as ctk
from tkinter import ttk, messagebox
from models import Wplata


class DeletePaymentWindow(MonityToplevel):
    def __init__(self, master, session, czlonek, **kwargs):
        super().__init__(master, **kwargs)
        prepare_window(self, master)
        self.session = session
        self.czlonek = czlonek

        self.title(f"Zarządzaj wpłatami - {czlonek.imie_nazwisko}")
        self.geometry("650x450")
        self.lift()

        self.lbl_title = ctk.CTkLabel(self, text=f"Historia wpłat: {czlonek.imie_nazwisko}", font=("Segoe UI", 16, "bold"))
        self.lbl_title.pack(pady=(15, 5))

        self.lbl_saldo = ctk.CTkLabel(self, text=f"Obecne saldo: {czlonek.bilans_otwarcia:.2f} PLN", text_color="gray")
        self.lbl_saldo.pack(pady=(0, 15))

        style = ttk.Style()
        style.theme_use("default")
        style.configure("Treeview", background="#F9F9F9", foreground="black", rowheight=36, fieldbackground="#F9F9F9")
        style.map('Treeview', background=[('selected', '#B65348')])  # Czerwone zaznaczenie, bo będziemy usuwać!
        style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"))

        self.frame_table = ctk.CTkFrame(self)
        self.frame_table.pack(fill="both", expand=True, padx=20, pady=(0, 10))

        kolumny = ("db_id", "data", "kwota", "metoda")
        self.tree = ttk.Treeview(self.frame_table, columns=kolumny, show="headings", selectmode="browse")

        self.tree.heading("db_id", text="DB_ID")
        self.tree.heading("data", text="Data wpłaty")
        self.tree.heading("kwota", text="Kwota (PLN)")
        self.tree.heading("metoda", text="Tytuł / Metoda")

        self.tree.column("db_id", width=0, stretch=False)
        self.tree.column("data", width=120, anchor="center")
        self.tree.column("kwota", width=100, anchor="e")
        self.tree.column("metoda", width=350, anchor="w")

        scrollbar = ttk.Scrollbar(self.frame_table, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscroll=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)

        self.btn_usun = ctk.CTkButton(
            self, text="INFORMACJA O KOREKTACH WPŁAT", command=self.usun_wplate,
            fg_color="#B65348", hover_color="#b32d2d", font=("Segoe UI", 12, "bold"), height=40
        )
        self.btn_usun.pack(pady=(10, 20))

        self.zaladuj_wplaty()

    def zaladuj_wplaty(self):
        for row in self.tree.get_children():
            self.tree.delete(row)

        wplaty = self.session.query(Wplata).filter_by(czlonek_id=self.czlonek.id).order_by(
            Wplata.data_przelewu.desc()).all()

        for w in wplaty:
            data_str = w.data_przelewu.strftime('%Y-%m-%d')
            metoda = w.metoda_dopasowania if w.metoda_dopasowania else w.tytul_oryginalny

            self.tree.insert("", "end", values=(
                w.id,
                data_str,
                f"{w.kwota:.2f}",
                metoda
            ))

    def usun_wplate(self):
        messagebox.showwarning(
            "Historia finansowa",
            "Usuwanie wpłat zostało zablokowane, aby zachować historię finansową.\n"
            "Korekta wymaga ewidencji powiązanej z oryginalną wpłatą; ten etap nie jest jeszcze wdrożony.",
            parent=self,
        )
