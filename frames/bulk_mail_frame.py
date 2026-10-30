import queue
import threading
from tkinter import messagebox, ttk
import customtkinter as ctk
from mailer import load_email_config
from mail_service import (DEFAULT_SUBJECT, DEFAULT_TEMPLATE, preview_batch, prepare_batch,
                          send_campaign, delivery_rows, retry_failed)
from ui import MonityToplevel, prepare_window, register_job

LABELS = {'pending': 'Oczekuje', 'sending': 'Sprawdź wynik próby', 'accepted': 'Przyjęta',
          'uncertain': 'Niepewny wynik', 'not_sent': 'Nie wysłano', 'cancelled': 'Anulowana'}


class BulkMailWindow(MonityToplevel):
    def __init__(self, master, session, **kwargs):
        super().__init__(master, **kwargs)
        prepare_window(self, master)
        self.title('Wiadomości zbiorcze i historia wysyłek')
        self.geometry('1000x720')
        self.session, self.engine = session, session.get_bind()
        self.config = load_email_config()
        self.plan = None
        self.busy = False
        self.results = queue.Queue()
        self.stop_event = threading.Event()
        self.worker = None
        self.closing = False
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(self, text='Wiadomości do klientów', font=('Segoe UI', 22, 'bold')).grid(row=0, column=0, sticky='w', padx=22, pady=(16,8))
        self.tabs = ctk.CTkTabview(self)
        self.tabs.grid(row=1, column=0, sticky='nsew', padx=16)
        compose, history = self.tabs.add('Nowa wysyłka'), self.tabs.add('Historia')
        compose.grid_columnconfigure(0, weight=1)
        compose.grid_columnconfigure(1, weight=1)
        compose.grid_rowconfigure(4, weight=1)
        self.scope = ctk.CTkOptionMenu(compose, values=['Zaległości — także archiwum', 'Wszyscy aktywni'])
        self.scope.grid(row=0, column=0, sticky='ew', padx=6, pady=5)
        self.btn_preview = ctk.CTkButton(compose, text='Wczytaj odbiorców i podgląd', command=self.preview)
        self.btn_preview.grid(row=0, column=1, sticky='ew', padx=6, pady=5)
        self.subject = ctk.CTkEntry(compose, placeholder_text='Temat')
        self.subject.insert(0, DEFAULT_SUBJECT)
        self.subject.grid(row=1, column=0, columnspan=2, sticky='ew', padx=6, pady=5)
        ctk.CTkLabel(compose, text='Szablon: {imie}, {id}, {saldo}, {zaleglosc}, {nadplata}, {rozliczenie_poczatkowe}, {dane_przelewu}, {kadencja}', anchor='w').grid(row=2, column=0, columnspan=2, sticky='ew', padx=6)
        self.body = ctk.CTkTextbox(compose, height=125)
        self.body.insert('1.0', DEFAULT_TEMPLATE)
        self.body.grid(row=3, column=0, columnspan=2, sticky='ew', padx=6, pady=5)
        table = ctk.CTkFrame(compose)
        table.grid(row=4, column=0, sticky='nsew', padx=6, pady=5)
        self.tree = ttk.Treeview(table, columns=('name','email','balance'), show='headings', selectmode='extended', height=5)
        for key, label, width in [('name','Klient',150), ('email','Odbiorca',180), ('balance','Saldo PLN',90)]:
            self.tree.heading(key, text=label)
            self.tree.column(key, width=width, minwidth=60)
        scroll = ttk.Scrollbar(table, command=self.tree.yview)
        scroll.pack(side='right', fill='y')
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(fill='both', expand=True)
        self.tree.bind('<<TreeviewSelect>>', self.show_message)
        self.message = ctk.CTkTextbox(compose, height=100)
        self.message.grid(row=4, column=1, sticky='nsew', padx=6, pady=5)
        self.message.configure(state='disabled')
        self.recipient_info = ctk.CTkLabel(compose, text='Wczytaj podgląd. Możesz zaznaczyć wybranych odbiorców (Ctrl / Shift).', wraplength=850)
        self.recipient_info.grid(row=5, column=0, columnspan=2, sticky='ew', padx=6)
        history.grid_columnconfigure(0, weight=1)
        history.grid_rowconfigure(1, weight=1)
        controls = ctk.CTkFrame(history, fg_color='transparent')
        controls.grid(row=0, column=0, sticky='ew', pady=5)
        ctk.CTkButton(controls, text='Odśwież historię', command=self.refresh_history).pack(side='left', padx=5)
        self.btn_resume = ctk.CTkButton(controls, text='Wznów oczekujące', command=self.resume)
        self.btn_resume.pack(side='left', padx=5)
        self.btn_retry = ctk.CTkButton(controls, text='Ponów pewny brak wysłania', command=self.retry)
        self.btn_retry.pack(side='left', padx=5)
        self.history = ttk.Treeview(history, columns=('date','email','mode','state'), show='headings', selectmode='browse', height=8)
        for key, label, width in [('date','Zapisano',150), ('email','Odbiorca',240), ('mode','Tryb',100), ('state','Wynik',200)]:
            self.history.heading(key, text=label)
            self.history.column(key, width=width, minwidth=70)
        self.history.grid(row=1, column=0, sticky='nsew', padx=(5,20))
        scrollbar = ttk.Scrollbar(history, command=self.history.yview)
        scrollbar.grid(row=1, column=0, sticky='nse')
        self.history.configure(yscrollcommand=scrollbar.set)
        self.history.bind('<<TreeviewSelect>>', self.show_history)
        self.history_info = ctk.CTkLabel(history, text='Wynik niepewny i przerwana próba nigdy nie są automatycznie ponawiane.', wraplength=850, justify='left')
        self.history_info.grid(row=2, column=0, sticky='ew', pady=8)
        footer = ctk.CTkFrame(self, fg_color='transparent')
        footer.grid(row=2, column=0, sticky='ew', padx=22, pady=12)
        self.btn_send = ctk.CTkButton(footer, text='Zatwierdź i wyślij zaznaczone', command=self.send, height=40)
        self.btn_send.pack(side='right')
        self.btn_stop = ctk.CTkButton(footer, text='Zatrzymaj po bieżącej', command=self.stop_event.set, state='disabled', fg_color='#A65045')
        self.btn_stop.pack(side='right', padx=10)
        self.status = ctk.CTkLabel(footer, text='Gotowe.', anchor='w', wraplength=390)
        self.status.pack(side='left', fill='x', expand=True)
        self.refresh_history()

    def preview(self):
        if self.busy:
            return
        try:
            self.plan = preview_batch(self.session, self.config.get('email',''),
                'debt' if self.scope.get().startswith('Zaległości') else 'active',
                self.subject.get().strip(), self.body.get('1.0','end').strip())
            self.tree.delete(*self.tree.get_children())
            for item in self.plan.items:
                self.tree.insert('', 'end', iid=str(item.member_id), values=(item.name,item.recipient,f'{item.balance_cents/100:.2f}'))
            if self.tree.get_children():
                self.tree.selection_set(self.tree.get_children())
                self.tree.focus(self.tree.get_children()[0])
            self.recipient_info.configure(text=f'Odbiorcy: {len(self.plan.items)}. Pominięto brak/błąd adresu: {len(self.plan.skipped)}. Każdy otrzyma osobną wiadomość. Zaznacz wiersz, aby sprawdzić treść.')
            self.show_message()
        except ValueError as exc:
            messagebox.showerror('Nie można przygotować wysyłki',str(exc),parent=self)

    def show_message(self, event=None):
        if not self.plan or not self.tree.selection():
            return
        selected = self.tree.focus() or self.tree.selection()[0]
        item = next((item for item in self.plan.items if str(item.member_id)==selected), None)
        if item:
            self.message.configure(state='normal')
            self.message.delete('1.0','end')
            self.message.insert('1.0',f'Do: {item.recipient}\nTemat: {item.subject}\nNota WAŻNE będzie wyróżniona na czerwono.\n\n{item.body}')
            self.message.configure(state='disabled')

    def send(self):
        if self.busy:
            return
        if not self.plan:
            messagebox.showinfo('Podgląd', 'Najpierw wczytaj odbiorców i treść.', parent=self)
            return
        if self.subject.get().strip()!=self.plan.subject_template or self.body.get('1.0','end').strip()!=self.plan.body_template or (
                ('debt' if self.scope.get().startswith('Zaległości') else 'active') != self.plan.scope):
            messagebox.showinfo('Odśwież podgląd','Zmieniono szablon lub grupę. Wczytaj nowy podgląd.',parent=self)
            return
        selected = [int(row) for row in self.tree.selection()]
        if not selected:
            messagebox.showinfo('Odbiorcy','Zaznacz odbiorców.',parent=self)
            return
        if not messagebox.askyesno('Zatwierdź wysyłkę',
            f'Wybrano {len(selected)} odbiorców. Nadawca: {self.plan.sender}.\n'
            'Każdy otrzyma wyłącznie własną wiadomość z pokazanego podglądu.\n'
            'Czy zapisać kolejkę i rozpocząć wysyłkę?',parent=self):
            return
        try:
            campaign, count, duplicates = prepare_batch(self.session, self.plan, selected)
            self.status.configure(text=f'W kolejce: {count}; istniejące duplikaty pominięto: {duplicates}.')
            self.start(campaign)
        except ValueError as exc:
            messagebox.showerror('Nie rozpoczęto wysyłki',str(exc),parent=self)

    def refresh_history(self):
        self.history_rows = {str(row['id']): row for row in delivery_rows(self.engine)}
        self.history.delete(*self.history.get_children())
        for key, row in self.history_rows.items():
            self.history.insert('', 'end', iid=key, values=(row['created'],row['recipient'],
                'Symulacja' if row['mode']=='simulation' else 'Gmail',LABELS[row['state']]))

    def show_history(self,event=None):
        if self.history.selection():
            row = self.history_rows[self.history.selection()[0]]
            self.history_info.configure(text=f"{row['subject']}\n{row['info']}")

    def selected_campaign(self):
        if not self.history.selection():
            messagebox.showinfo('Historia','Wybierz wiadomość z kampanii w historii.',parent=self)
            return None
        return self.history_rows[self.history.selection()[0]]['campaign']

    def resume(self):
        campaign = self.selected_campaign()
        if campaign and not self.busy and messagebox.askyesno('Wznów kolejkę','Wysłać tylko oczekujące wiadomości wybranej kampanii? Wysłane i niepewne zostaną pominięte.',parent=self):
            self.start(campaign)

    def retry(self):
        campaign = self.selected_campaign()
        if campaign and not self.busy and messagebox.askyesno('Ponów niewysłane','Ponowić tylko wiadomości, których serwer na pewno nie przyjął? Wyniki niepewne nie będą ponawiane.',parent=self):
            count = retry_failed(self.engine,campaign)
            self.status.configure(text=f'Jawnie ponowiono: {count}.')
            self.start(campaign)

    def start(self,campaign):
        if not self.config.get('haslo'):
            messagebox.showerror('Gmail','Brakuje hasła aplikacji w konfiguracji poczty.',parent=self)
            return
        self.busy = True
        self.stop_event.clear()
        for button in (self.btn_send,self.btn_preview,self.btn_resume,self.btn_retry):
            button.configure(state='disabled')
        self.btn_stop.configure(state='normal')
        config = dict(self.config)
        def work():
            try:
                send_campaign(self.engine,campaign,config,self.stop_event,
                    lambda *result:self.results.put(('progress',result)),interval=1.0)
                self.results.put(('done',None))
            except Exception:
                self.results.put(('error','Nie udało się zakończyć operacji. Sprawdź historię przed wznowieniem.'))
        self.worker = threading.Thread(target=work,daemon=True)
        register_job(self, self.worker, self.stop_event)
        self.worker.start()
        self.after(100,self.poll)

    def poll(self):
        finished = False
        while True:
            try:
                kind, result = self.results.get_nowait()
            except queue.Empty:
                break
            if kind=='progress':
                self.status.configure(text=f'Wiadomość {result[0]}: {LABELS[result[1]]}.')
            else:
                finished = True
                self.status.configure(text=result or 'Zakończono. Sprawdź wyniki w historii.')
        if not finished:
            self.after(100,self.poll)
            return
        self.busy = False
        self.btn_stop.configure(state='disabled')
        for button in (self.btn_send,self.btn_preview,self.btn_resume,self.btn_retry):
            button.configure(state='normal')
        self.refresh_history()
        if self.closing:
            self.destroy()

    def destroy(self):
        if self.busy:
            self.closing = True
            self.stop_event.set()
            self.status.configure(text='Zatrzymywanie po bieżącej wiadomości…')
            return
        super().destroy()
