from ui import prepare_window, MonityToplevel
import customtkinter as ctk
from tkinter import ttk
from models import Status


class StatusListWindow(MonityToplevel):
    def __init__(self, master, session, **kwargs):
        super().__init__(master, **kwargs)
        prepare_window(self, master)
        self.session = session

        self.title("Lista Statusów w systemie")
        self.geometry("600x400")
        self.lift()

        self.frame_search = ctk.CTkFrame(self, fg_color="transparent")
        self.frame_search.pack(fill="x", padx=20, pady=10)

        self.lbl_szukaj = ctk.CTkLabel(self.frame_search, text="Szukaj po nazwie:")
        self.lbl_szukaj.pack(side="left", padx=(0, 10))

        self.entry_szukaj = ctk.CTkEntry(self.frame_search, width=200, placeholder_text="Wpisz status...")
        self.entry_szukaj.pack(side="left", padx=(0, 10))

        self.btn_szukaj = ctk.CTkButton(
            self.frame_search, text="Szukaj", command=self.zaladuj_dane, width=80, fg_color="#203B5D"
        )
        self.btn_szukaj.pack(side="left", padx=(0, 10))

        self.btn_reset = ctk.CTkButton(
            self.frame_search, text="Reset", command=self.resetuj_szukanie, width=80, fg_color="#B65348"
        )
        self.btn_reset.pack(side="left")

        style = ttk.Style()
        style.theme_use("default")
        style.configure("Treeview",
                        background="#F9F9F9", foreground="black", rowheight=36,
                        fieldbackground="#F9F9F9", bordercolor="#DDDDDD", borderwidth=1)
        style.map('Treeview', background=[('selected', '#18735D')])
        style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"), background="#E0E0E0", foreground="black")

        self.frame_table = ctk.CTkFrame(self)
        self.frame_table.pack(fill="both", expand=True, padx=20, pady=(0, 20))

        kolumny = ("id", "nazwa", "kwota")
        self.tree = ttk.Treeview(self.frame_table, columns=kolumny, show="headings", selectmode="browse")

        self.tree.heading("id", text="ID w bazie")
        self.tree.heading("nazwa", text="Nazwa Statusu")
        self.tree.heading("kwota", text="Stawka bazowa (PLN)")

        self.tree.column("id", width=80, anchor="center")
        self.tree.column("nazwa", width=250, anchor="w")
        self.tree.column("kwota", width=150, anchor="e")

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

        fraza = self.entry_szukaj.get().strip().lower()

        # Pobieramy wszystkie statusy z bazy
        statusy = self.session.query(Status).all()

        for s in statusy:
            # Proste filtrowanie po nazwie statusu
            if fraza and fraza not in s.nazwa.lower():
                continue

            # Wrzucamy wiersz do tabeli
            self.tree.insert("", "end", values=(
                s.id,
                s.nazwa,
                f"{s.kwota:.2f}"
            ))