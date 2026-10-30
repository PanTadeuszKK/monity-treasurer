from datetime import datetime
from tkinter import messagebox, filedialog
import customtkinter as ctk
from annual_fees import cadence_year
from report_service import export_cadence
from ui import pack_footer, prepare_window, MonityToplevel


class YearlyStatsWindow(MonityToplevel):
    def __init__(self,master,session,**kwargs):
        super().__init__(master,**kwargs)
        prepare_window(self,master)
        self.session=session
        self.title('Zestawienie kadencji — zapisane operacje')
        self.geometry('560x390')
        ctk.CTkLabel(self,text='Raport kadencji',font=('Segoe UI',23,'bold')).pack(pady=(20,10))
        self.dropdown_okres=ctk.CTkOptionMenu(self,values=self.generuj_okresy(2024))
        self.dropdown_okres.pack(pady=10)
        self.lbl_info=ctk.CTkLabel(self,text='Eksport obejmuje klientów i archiwum, wpłaty oraz zapisane naliczenia i korekty.\n\nBieżące saldo jest opisane osobno. Braki dawnych danych są oznaczone; raport nie udaje historycznego salda końcowego.',wraplength=480,justify='left')
        self.lbl_info.pack(fill='x',padx=30,pady=15)
        self.btn_export=ctk.CTkButton(self,text='Eksportuj XLSX',command=self.eksportuj_raport_roczny,height=40)
        pack_footer(self.btn_export)

    def generuj_okresy(self,rok_startowy):
        now=datetime.now()
        current=cadence_year(now.year,now.month)
        return [f'{year}/{str(year+1)[-2:]}' for year in range(current,min(current,rok_startowy)-1,-1)]

    def eksportuj_raport_roczny(self):
        year=int(self.dropdown_okres.get().split('/')[0])
        path=filedialog.asksaveasfilename(parent=self,defaultextension='.xlsx',filetypes=[('Excel','*.xlsx')],initialfile=f'Kadencja-{year}-{year+1}.xlsx')
        if not path: return
        try:
            report=export_cadence(self.session,year,path)
            self.lbl_info.configure(text=f"Zapisano raport. Osoby: {len(report['members'])}.\n{report['warning']}")
            messagebox.showinfo('Zapisano','Raport XLSX jest gotowy.',parent=self)
        except Exception:
            messagebox.showerror('Nie zapisano','Nie można zapisać raportu. Sprawdź ścieżkę i zamknij plik w Excelu.',parent=self)
