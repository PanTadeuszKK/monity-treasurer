from datetime import date
from decimal import Decimal
import customtkinter as ctk
from tkinter import messagebox
from sqlalchemy.orm import Session
from models import Czlonek, Status, ZatwierdzenieStawek, StatusNaliczenia
from annual_fees import cadence_year, rate_cents, preview_fees, approve_fees, history_requirements, bulk_history
from ui import prepare_window, MonityToplevel, ReviewTabview, data_table, TableChoice, MUTED, GREEN


class ChangeFeesWindow(MonityToplevel):
    def __init__(self, master, session, **kwargs):
        super().__init__(master, **kwargs)
        prepare_window(self, master)
        self.session, self.loaded_year, self.preview = session, None, None
        self.title('Zatwierdź stawki kadencji')
        self.geometry('1040x720')
        self.preferred_width = 1040
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)
        header = ctk.CTkFrame(self, fg_color='transparent')
        header.grid(row=0, column=0, sticky='ew', padx=20, pady=(8, 2))
        ctk.CTkLabel(header, text='Stawki na kadencję', font=('Segoe UI', 20, 'bold'), height=26).pack(anchor='w')
        self.subtitle = ctk.CTkLabel(header, text='Stawki od czerwca · wspólny podgląd przed zapisem',
            text_color=MUTED, height=20, font=('Segoe UI', 12))
        self.subtitle.pack(anchor='w')
        controls = ctk.CTkFrame(self, fg_color='white')
        controls.grid(row=1, column=0, sticky='ew', padx=20, pady=2)
        controls.grid_columnconfigure(1, weight=1)
        controls.grid_columnconfigure(3, weight=1)
        today = date.today()
        ctk.CTkLabel(controls, text='Kadencja').grid(row=0, column=0, padx=8, pady=5)
        self.entry_year = ctk.CTkEntry(controls, width=85)
        self.entry_year.insert(0, str(cadence_year(today.year, today.month)))
        self.entry_year.grid(row=0, column=1, sticky='ew', padx=(0, 10))
        self.date_label = ctk.CTkLabel(controls, text='Data decyzji')
        self.date_label.grid(row=0, column=2, padx=8)
        self.entry_date = ctk.CTkEntry(controls, width=125)
        self.entry_date.insert(0, today.isoformat())
        self.entry_date.grid(row=0, column=3, sticky='ew', padx=(0, 10))
        self.btn_load = ctk.CTkButton(controls, text='Wczytaj', width=85, command=self.load_rates)
        self.btn_load.grid(row=0, column=4, padx=(0, 12))
        self.entry_year.bind('<Return>', lambda event: self.load_rates())
        self.entry_year.bind('<KeyRelease>', self.invalidate)
        self.entry_date.bind('<KeyRelease>', self.invalidate)
        self.tabs = ReviewTabview(self, height=100, corner_radius=0, border_width=0)
        self.tabs.grid(row=2, column=0, sticky='nsew', padx=20, pady=2)
        self.form = ctk.CTkScrollableFrame(self.tabs.add('Stawki'), fg_color='transparent')
        self.form.pack(fill='both', expand=True)
        self.history_tab = self.tabs.add('Dawna historia')
        self.history_tab.grid_columnconfigure(0, weight=1)
        self.history_tab.grid_rowconfigure(2, weight=1)
        self.preview_tab = self.tabs.add('Podgląd zmian')
        self.preview_tab.grid_columnconfigure(0, weight=1)
        self.preview_tab.grid_rowconfigure(1, weight=1)
        self.preview_summary = ctk.CTkLabel(self.preview_tab,
            text='Podgląd pokaże kwoty poszczególnych osób i miesięcy przed zapisem.',
            justify='left', anchor='w', wraplength=900)
        self.preview_summary.grid(row=0, column=0, sticky='ew', padx=8, pady=8)
        table = ctk.CTkFrame(self.preview_tab)
        table.grid(row=1, column=0, sticky='nsew', padx=4, pady=4)
        self.preview_tree = data_table(table, [('name', 'Klient', 240), ('period', 'Miesiąc', 85),
            ('original', 'Status pierwotny', 130), ('status', 'Status docelowy', 130), ('before', 'Przed PLN', 100),
            ('after', 'Po PLN', 100), ('delta', 'Różnica PLN', 105)], selectmode='browse', height=4)
        self.lbl_info = ctk.CTkLabel(self, text='', justify='left', anchor='w', wraplength=950, text_color=MUTED,
            height=18, font=('Segoe UI', 11))
        self.lbl_info.grid(row=3, column=0, sticky='ew', padx=24, pady=3)
        footer = ctk.CTkFrame(self, fg_color='transparent')
        footer.grid(row=4, column=0, sticky='ew', padx=20, pady=(2, 6))
        ctk.CTkButton(footer, text='Anuluj', width=90, fg_color='#65758A', command=self.destroy).pack(side='left')
        self.btn_confirm = ctk.CTkButton(footer, text='Zatwierdź stawki', command=self.confirm, state='disabled', fg_color=GREEN)
        self.btn_confirm.pack(side='right', padx=(8, 0))
        self.btn_preview = ctk.CTkButton(footer, text='Podgląd zmian', command=self.zapisz_zmiany)
        self.btn_preview.pack(side='right')
        self.entry_dict, self.previous_entries, self.original_status_entries = {}, {}, {}
        self.load_rates()
        self._compact = None
        self.bind('<Configure>', self.layout_controls, add='+')

    def layout_controls(self, event=None):
        if event is not None and event.widget is not self:
            return
        narrow = self.winfo_width() / self._get_window_scaling() < 540
        compact = self.winfo_height() / self._get_window_scaling() < 550
        if (compact, narrow) != self._compact:
            self._compact = (compact, narrow)
            self.date_label.grid(row=1 if narrow else 0, column=0 if narrow else 2, padx=8, pady=4)
            self.entry_date.grid(row=1 if narrow else 0, column=1 if narrow else 3, sticky='ew', padx=(0, 10), pady=4)
            self.btn_load.grid(row=0, column=2 if narrow else 4, padx=(0, 12))
            if compact:
                self.subtitle.pack_forget()
            else:
                self.subtitle.pack(anchor='w')
            self.preview_summary.configure(font=('Segoe UI', 11 if compact else 13))

    def invalidate(self, event=None):
        self.preview = None
        self.btn_confirm.configure(state='disabled')
        self.preview_tree.delete(*self.preview_tree.get_children())
        self.preview_summary.configure(text='Wygeneruj podgląd po uzupełnieniu lub zmianie danych.')

    def load_rates(self):
        self.invalidate()
        try:
            year = int(self.entry_year.get().strip())
            date(year + 1, 6, 1)
            with Session(bind=self.session.get_bind()) as operation:
                statuses = operation.query(Status).order_by(Status.id).all()
                rates = [(s.id, s.nazwa, rate_cents(operation, s, year, 6), s.kwota) for s in statuses]
                approval = operation.query(ZatwierdzenieStawek).filter_by(rok_kadencji=year).order_by(
                    ZatwierdzenieStawek.rewizja.desc()).first()
                info = (f'Decyzja {approval.data_decyzji} · rewizja {approval.rewizja}'
                    if approval else 'Stawki prowizoryczne')
            for widget in self.form.winfo_children():
                widget.destroy()
            for widget in self.history_tab.winfo_children():
                widget.destroy()
            self.entry_dict, self.previous_entries, self.original_status_entries = {}, {}, {}
            self.status_names = {key: name for key, name, _, _ in rates}
            self.form.grid_columnconfigure((0, 1), weight=1, uniform='rate')
            for index, (key, name, cents, _) in enumerate(rates):
                card = ctk.CTkFrame(self.form, fg_color='white', border_width=1, border_color='#DFE6EE')
                card.grid(row=index // 2, column=index % 2, sticky='nsew', padx=6, pady=8)
                ctk.CTkLabel(card, text=name, font=('Segoe UI', 20, 'bold')).pack(anchor='w', padx=18, pady=(14, 2))
                ctk.CTkLabel(card, text='Nowa składka miesięczna · PLN', text_color=MUTED).pack(anchor='w', padx=18)
                entry = ctk.CTkEntry(card, height=42, font=('Segoe UI', 22), width=160)
                entry.insert(0, f'{Decimal(cents) / 100:.2f}')
                entry.pack(fill='x', padx=18, pady=12)
                entry.bind('<KeyRelease>', self.invalidate)
                self.entry_dict[key] = entry
                ctk.CTkLabel(card, text=f'Dotychczas: {Decimal(cents) / 100:.2f} PLN', text_color=MUTED).pack(anchor='w', padx=18, pady=(0, 14))
            ctk.CTkLabel(self.form, text=f'Obowiązuje od 01.06.{year} do 31.05.{year + 1}.\n'
                'Wyrównanie obejmuje tylko miesiące już naliczone. Wpłaty pozostają bez zmian.',
                justify='left', anchor='w', wraplength=800).grid(row=(len(rates) + 1) // 2,
                    column=0, columnspan=2, sticky='ew', padx=12, pady=10)
            requirements = history_requirements(self.session, year)
            if requirements:
                ctk.CTkLabel(self.history_tab, text='Sprawdź proponowane stawki z konfiguracji i wybierz znane dawne statusy.\n'
                    'Jedna stawka i status muszą obowiązywać przez cały uzupełniany okres.',
                    wraplength=880, justify='left').grid(row=0, column=0, sticky='ew', padx=8, pady=6)
                previous = ctk.CTkFrame(self.history_tab, fg_color='transparent')
                previous.grid(row=1, column=0, sticky='ew', padx=8)
                for index, (key, name, _, base) in enumerate(rates):
                    ctk.CTkLabel(previous, text=f'Dawna stawka {name}:').grid(row=index // 2, column=2 * (index % 2), padx=6, pady=4)
                    entry = ctk.CTkEntry(previous, width=100)
                    entry.insert(0, f'{Decimal(str(base)):.2f}')
                    entry.grid(row=index // 2, column=2 * (index % 2) + 1, padx=6, pady=4)
                    entry.bind('<KeyRelease>', self.invalidate)
                    self.previous_entries[key] = entry
                table = ctk.CTkFrame(self.history_tab)
                table.grid(row=2, column=0, sticky='nsew', padx=8, pady=6)
                self.history_tree = data_table(table, [('name', 'Klient', 400), ('status', 'Dawny status — kliknij, aby wybrać', 300)], height=4)
                self.history_choice = TableChoice(self.history_tree)
                with Session(bind=self.session.get_bind()) as operation:
                    members = [operation.get(Czlonek, key) for key in {r[2] for r in requirements}]
                    for member in sorted(members, key=lambda m: (m.imie_nazwisko, m.id)):
                        variable = ctk.StringVar(value='Wybierz status')
                        self.original_status_entries[member.id] = variable
                        self.history_tree.insert('', 'end', iid=str(member.id), values=(
                            f'{member.imie_nazwisko} · A!{member.numer_identyfikacyjny}', variable.get()))
                        variable.trace_add('write', lambda *args, key=member.id: self.history_changed(key))
                self.history_tree.bind('<ButtonRelease-1>', self.edit_history)
                self.history_tree.bind('<Return>', self.edit_history)
            else:
                ctk.CTkLabel(self.history_tab, text='Nie ma dawnych naliczeń wymagających uzupełnienia.\n'
                    'Możesz przejść prosto do podglądu zmian.', text_color=MUTED).grid(row=0, column=0, padx=20, pady=20)
            self.loaded_year = year
            self.lbl_info.configure(text=f'Kadencja {year}/{year + 1} · {info}' +
                (f' · Do uzupełnienia: {len(self.original_status_entries)} osób' if requirements else ''))
            self.tabs.set('Stawki')
        except (ValueError, OverflowError) as exc:
            self.loaded_year = None
            messagebox.showerror('Nie można wczytać', str(exc), parent=self)

    def history_changed(self, key):
        self.history_tree.set(str(key), 'status', self.original_status_entries[key].get())
        self.invalidate()

    def edit_history(self, event):
        if getattr(event, 'keysym', '') == 'Return':
            selected = self.history_tree.selection()
            key = selected[0] if selected else ''
        else:
            key = self.history_tree.identify_row(event.y)
            if self.history_tree.identify_column(event.x) != '#2':
                return
        if key:
            self.history_choice.open(key, 'status', {name: name for name in self.status_names.values()},
                lambda value: self.original_status_entries[int(key)].set(value))

    def inputs(self):
        return (self.entry_year.get().strip(), self.entry_date.get().strip(),
            tuple((key, entry.get()) for key, entry in self.entry_dict.items()),
            tuple((key, entry.get()) for key, entry in self.previous_entries.items()),
            tuple((key, entry.get()) for key, entry in self.original_status_entries.items()))

    def zapisz_zmiany(self):
        self.invalidate()
        try:
            year = int(self.entry_year.get().strip())
            if year != self.loaded_year:
                raise ValueError('Po zmianie roku wczytaj stawki wybranej kadencji.')
            decision_date = date.fromisoformat(self.entry_date.get().strip())
            values = {key: entry.get() for key, entry in self.entry_dict.items()}
            history = None
            if self.previous_entries:
                ids = {name: key for key, name in self.status_names.items()}
                originals = {key: ids.get(choice.get()) for key, choice in self.original_status_entries.items()}
                if None in originals.values():
                    self.tabs.set('Dawna historia')
                    raise ValueError('Wybierz dawny status każdej osoby w zakładce „Dawna historia”.')
                history = bulk_history(self.session, year,
                    {key: entry.get() for key, entry in self.previous_entries.items()}, originals)
            plan = preview_fees(self.session, year, values, decision_date, history=history)
            with Session(bind=self.session.get_bind()) as operation:
                members = {m.id: f'{m.imie_nazwisko} · A!{m.numer_identyfikacyjny}' for m in operation.query(Czlonek)}
                snapshots = {s.naliczenie_czlonka_id: s.status_id for s in operation.query(StatusNaliczenia)}
            periods = {key: f'{y}-{m:02}' for key, y, m in plan.charge_periods}
            for charge_id, member_id, status_id, before, after in plan.charges:
                period = periods.get(charge_id, 'Uzgodnione')
                original = (self.status_names[snapshots[charge_id]] if charge_id in snapshots else
                    self.original_status_entries[member_id].get())
                self.preview_tree.insert('', 'end', values=(members[member_id], period,
                    original, self.status_names[status_id], f'{Decimal(before) / 100:.2f}',
                    f'{Decimal(after) / 100:.2f}', f'{Decimal(after - before) / 100:+.2f}'))
            self.preview_summary.configure(text=f'Decyzja {decision_date} · '
                + ' · '.join(f'{self.status_names[key]}: {Decimal(cents) / 100:.2f} PLN' for key, cents in plan.rates)
                + f'\nKorekty: {plan.correction_count} · Zmiana należności: {Decimal(plan.total_cents) / 100:+.2f} PLN '
                '(+ zwiększa zaległość).'
                + (' Te stawki są już zatwierdzone — brak zmian.' if plan.unchanged else '')
                + ('\nDawne stawki: ' + ' · '.join(f'{self.status_names[key]}: {entry.get()} PLN'
                    for key, entry in self.previous_entries.items()) if history else ''))
            self.preview = (self.inputs(), year, values, decision_date, history, plan)
            self.tabs.set('Podgląd zmian')
            self.btn_confirm.configure(state='disabled' if plan.unchanged else 'normal')
        except ValueError as exc:
            messagebox.showerror('Sprawdź dane', str(exc), parent=self)
        except Exception:
            messagebox.showerror('Brak podglądu', 'Nie udało się przygotować podglądu. Nie zapisano zmian.', parent=self)

    def confirm(self):
        try:
            if self.preview is None or self.preview[0] != self.inputs():
                self.invalidate()
                raise ValueError('Dane zmieniły się. Wygeneruj nowy podgląd przed zatwierdzeniem.')
            _, year, values, decision_date, history, plan = self.preview
            if plan.unchanged:
                return
            approve_fees(self.session, year, values, decision_date, expected_plan=plan, history=history)
            messagebox.showinfo('Zapisano', 'Zatwierdzono stawki i zapisano korekty.', parent=self)
            self.destroy()
        except ValueError as exc:
            self.invalidate()
            messagebox.showerror('Nie zapisano zmian', str(exc), parent=self)
        except Exception:
            self.invalidate()
            messagebox.showerror('Nie zapisano zmian', 'Operacja została wycofana. Odśwież podgląd.', parent=self)
