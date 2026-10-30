import json
from tkinter import messagebox
import customtkinter as ctk
from paths import data_path
from frames.import_frame import load_columns
from ui import pack_footer, MonityToplevel, prepare_window


class ChangeColumnsWindow(MonityToplevel):
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        prepare_window(self,master)
        self.title('Kolumny wyciągu XLSX')
        self.geometry('500x580')
        ctk.CTkLabel(self,text='Dopasuj nazwy kolumn wyciągu',font=('Segoe UI',19,'bold')).pack(pady=15)
        ctk.CTkLabel(self,text='Wpisz nazwy dokładnie tak, jak w pliku XLSX.\nID bankowe jest opcjonalne; bez niego podobne operacje wymagają sprawdzenia.',wraplength=440).pack(padx=20,pady=5)
        self.form = ctk.CTkScrollableFrame(self)
        self.form.pack(fill='both',expand=True,padx=20,pady=10)
        self.entries = {}
        config = load_columns()
        for key,label in [('date','Data'),('amount','Kwota'),('title','Tytuł'),('sender','Nazwa nadawcy (opcjonalnie)'),('currency','Waluta (opcjonalnie)'),('bank_id','Unikalne ID transakcji bankowej (opcjonalnie)')]:
            ctk.CTkLabel(self.form,text=label).pack(anchor='w',padx=10)
            entry = ctk.CTkEntry(self.form)
            entry.insert(0,config[key])
            entry.pack(fill='x',padx=10,pady=(0,10))
            self.entries[key] = entry
        self.btn_save = ctk.CTkButton(self,text='Zapisz konfigurację',command=self.zapisz_konfiguracje,height=38)
        pack_footer(self.btn_save)

    def zapisz_konfiguracje(self):
        values = {key:entry.get().strip() for key,entry in self.entries.items()}
        if not all(values[key] for key in ('date','amount','title')):
            messagebox.showerror('Nie zapisano','Data, kwota i tytuł wymagają nazw kolumn.',parent=self)
            return
        nonempty = [value for value in values.values() if value]
        if len(nonempty)!=len(set(nonempty)):
            messagebox.showerror('Nie zapisano','Każde pole musi wskazywać inną kolumnę.',parent=self)
            return
        mapping = {'date':'kol_data','amount':'kol_kwota','title':'kol_tytul','currency':'kol_waluta','bank_id':'kol_id','sender':'kol_nadawca'}
        target = data_path('config_kolumn.json')
        temp = target.with_suffix('.tmp')
        try:
            target.parent.mkdir(parents=True,exist_ok=True)
            temp.write_text(json.dumps({mapping[key]:value for key,value in values.items()},ensure_ascii=False,indent=2),encoding='utf-8')
            temp.replace(target)
            messagebox.showinfo('Zapisano','Konfiguracja będzie użyta przy następnym podglądzie importu.',parent=self)
            self.destroy()
        except OSError:
            messagebox.showerror('Nie zapisano','Nie można zapisać konfiguracji. Sprawdź dostęp do katalogu danych.',parent=self)
