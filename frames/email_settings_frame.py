import queue
import threading
import customtkinter as ctk
from tkinter import messagebox

from mailer import Mailer, load_email_config, valid_address
from ui import prepare_window, MonityToplevel, register_job, INK, MUTED, GREEN


class EmailSettingsWindow(MonityToplevel):
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        prepare_window(self, master)
        self.title('Poczta Gmail — diagnostyka')
        self.geometry('600x540')
        self.config_email = load_email_config()
        self.results = queue.Queue()
        self.busy = False
        self.sent = False
        self.poll_id = None
        self.protocol('WM_DELETE_WINDOW', self.destroy)
        self.bind('<Destroy>', self._on_destroy, add='+')
        self.grid_columnconfigure(0,weight=1)
        self.grid_rowconfigure(2,weight=1)
        ctk.CTkLabel(self,text='Sprawdź pocztę Gmail',font=('Segoe UI',23,'bold')).grid(row=0,column=0,sticky='w',padx=24,pady=(18,6))
        ctk.CTkLabel(self,text='Test połączenia nie wysyła maila. Wiadomość testowa nie zawiera danych klientów.',
            text_color=MUTED,justify='left',wraplength=530).grid(row=1,column=0,sticky='ew',padx=24,pady=(0,8))
        form=ctk.CTkScrollableFrame(self,fg_color='white')
        form.grid(row=2,column=0,sticky='nsew',padx=24,pady=5)
        sender=self.config_email.get('email','')
        ctk.CTkLabel(form,text='NADAWCA',text_color=MUTED,font=('Segoe UI',10,'bold')).pack(anchor='w',padx=10,pady=(10,2))
        ctk.CTkLabel(form,text=sender or 'Brak konfiguracji nadawcy',font=('Segoe UI',15,'bold')).pack(anchor='w',padx=10,pady=(0,14))
        ctk.CTkLabel(form,text='Adres dla jednej wiadomości testowej:',text_color=INK).pack(anchor='w',padx=10)
        self.entry_recipient=ctk.CTkEntry(form,height=36)
        self.entry_recipient.insert(0,sender)
        self.entry_recipient.pack(fill='x',padx=10,pady=(5,12))
        self.lbl_status=ctk.CTkLabel(self,text='Gotowe do testu.',text_color=MUTED,wraplength=530,justify='left')
        self.lbl_status.grid(row=3,column=0,sticky='ew',padx=24,pady=8)
        footer=ctk.CTkFrame(self,fg_color='transparent')
        footer.grid(row=4,column=0,sticky='ew',padx=24,pady=(4,16))
        footer.grid_columnconfigure((0,1),weight=1)
        self.btn_check=ctk.CTkButton(footer,text='Sprawdź połączenie',command=self.check_connection,height=42)
        self.btn_check.grid(row=0,column=0,sticky='ew',padx=(0,6))
        self.btn_send=ctk.CTkButton(footer,text='Podgląd i wyślij test',command=self.send_test,
            fg_color='#203B5D',hover_color='#142C47',height=42)
        self.btn_send.grid(row=0,column=1,sticky='ew',padx=(6,0))
        if not sender or not self.config_email.get('haslo'):
            self.btn_check.configure(state='disabled')
            self.btn_send.configure(state='disabled')
            self.lbl_status.configure(text='Brakuje konfiguracji email/haslo w config_email.json. Użyj hasła aplikacji Google. Możesz wskazać plik poza projektem przez MONITY_EMAIL_CONFIG.')

    def _on_destroy(self,event):
        if event.widget is self and self.poll_id:
            self.after_cancel(self.poll_id)
            self.poll_id=None

    def _start(self,send=False,recipient=None):
        if self.busy:
            return
        self.busy=True
        self.btn_check.configure(state='disabled')
        self.btn_send.configure(state='disabled')
        self.lbl_status.configure(text='Łączenie z Gmail…',text_color=MUTED)
        config=dict(self.config_email)
        def work():
            mailer=Mailer(config.get('email',''),config.get('haslo',''))
            result=mailer.wyslij_test(recipient) if send else mailer.sprawdz_polaczenie()
            self.results.put((result,mailer.delivery_state,send))
        worker=threading.Thread(target=work,daemon=True)
        register_job(self,worker)
        worker.start()
        self.poll_id=self.after(100,self._poll)

    def _poll(self):
        self.poll_id=None
        try:
            (success,info),state,was_send=self.results.get_nowait()
        except queue.Empty:
            self.poll_id=self.after(100,self._poll)
            return
        self.busy=False
        if was_send and (success or state=='uncertain'):
            self.sent=True
        self.lbl_status.configure(text=info,text_color=GREEN if success else '#A34135')
        self.btn_check.configure(state='normal')
        self.btn_send.configure(state='disabled' if self.sent else 'normal')

    def check_connection(self):
        self._start()

    def send_test(self):
        recipient=self.entry_recipient.get().strip()
        if not valid_address(recipient):
            messagebox.showerror('Nieprawidłowy odbiorca','Podaj jeden prawidłowy adres e-mail.',parent=self)
            return
        if messagebox.askyesno('Podgląd wiadomości testowej',
            f'Odbiorca: {recipient}\nTemat: [Monity] Wiadomość testowa\n\n'
            'Treść: pojedynczy test aplikacji Monity, bez danych klientów.\n\nWyślij jedną wiadomość?',parent=self):
            self._start(send=True,recipient=recipient)
