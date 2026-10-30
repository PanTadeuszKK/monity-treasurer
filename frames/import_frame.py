import json
from decimal import Decimal
from tkinter import filedialog, messagebox
import customtkinter as ctk
from sqlalchemy.orm import Session
from models import Czlonek
from paths import data_path
from import_service import preview_import, commit_import, pending_imports, post_pending, DEFAULT_COLUMNS, transaction_details
from ui import prepare_window, MonityToplevel, data_table, TableChoice, set_text, MUTED, GREEN


def load_columns():
    try:
        config = json.loads(data_path('config_kolumn.json').read_text(encoding='utf-8'))
        if not isinstance(config, dict):
            return dict(DEFAULT_COLUMNS)
    except (OSError, ValueError):
        return dict(DEFAULT_COLUMNS)
    mapping = dict(DEFAULT_COLUMNS)
    for key, name in [('date', 'kol_data'), ('amount', 'kol_kwota'), ('title', 'kol_tytul'),
            ('currency', 'kol_waluta'), ('bank_id', 'kol_id'), ('sender', 'kol_nadawca')]:
        if name in config:
            mapping[key] = config[name]
    return mapping


class ImportConfirmation(MonityToplevel):
    """Jeden wspólny podgląd wszystkich przypisań, jeden zapis całej operacji."""
    def __init__(self, master, rows, on_confirm, omitted):
        super().__init__(master)
        prepare_window(self, master)
        self.title('Zatwierdź przypisania wpłat')
        self.geometry('1060x640')
        self.preferred_width = 1060
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)
        total = sum(row['cents'] for row in rows)
        ctk.CTkLabel(self, text=f'{len(rows)} wpłat · {Decimal(total) / 100:.2f} PLN',
            font=('Segoe UI', 22, 'bold')).grid(row=0, column=0, sticky='w', padx=20, pady=(16, 4))
        ctk.CTkLabel(self, text=f'Sprawdź opis po lewej i klienta po prawej. Pominięte pozycje: {omitted}.',
            text_color=MUTED, wraplength=950, anchor='w').grid(row=1, column=0, sticky='ew', padx=20, pady=4)
        frame = ctk.CTkFrame(self)
        frame.grid(row=2, column=0, sticky='nsew', padx=20, pady=6)
        self.tree = data_table(frame, [('description', 'Opis transakcji · data · kwota', 570),
            ('member', 'Przypisujesz do', 360)], selectmode='browse', height=5)
        self.rows = {str(r['key']): r for r in rows}
        for row in rows:
            self.tree.insert('', 'end', iid=str(row['key']), values=(
                f"{row['title']} · {row['date']} · {Decimal(row['cents']) / 100:.2f} PLN", row['member']),
                tags=('review',) if row['state'] == 'review' else ())
        self.tree.tag_configure('review', foreground='#925C13')
        self.tree.bind('<<TreeviewSelect>>', self.show_details)
        self.details = ctk.CTkTextbox(self, height=105)
        self.details.grid(row=3, column=0, sticky='ew', padx=20, pady=5)
        set_text(self.details, 'Wybierz pozycję, aby przeczytać pełny opis, nadawcę i uwagi.')
        reviews = sum(r['state'] == 'review' for r in rows)
        self.notice = ctk.CTkLabel(self, text=(f'Pozycji do ręcznego sprawdzenia: {reviews}. '
            'Zatwierdzasz, że każda pozycja jest odrębnym nowym wpływem PLN. '
            'Podobne przelewy bez ID bankowego sprawdź szczególnie uważnie.'),
            justify='left', anchor='w', wraplength=950, text_color='#925C13' if reviews else MUTED)
        self.notice.grid(row=4, column=0, sticky='ew', padx=20, pady=4)
        footer = ctk.CTkFrame(self, fg_color='transparent')
        footer.grid(row=5, column=0, sticky='ew', padx=20, pady=(4, 12))
        ctk.CTkButton(footer, text='Wróć do przypisań', command=self.destroy, fg_color=MUTED).pack(side='left')
        self.btn_save = ctk.CTkButton(footer, text=f'Zaksięguj {len(rows)} wpłat', fg_color=GREEN,
            command=lambda: on_confirm(self))
        self.btn_save.pack(side='right')
        self.grab_set()
        self._compact = None
        self.bind('<Configure>', self.layout_controls, add='+')

    def layout_controls(self, event=None):
        if event is not None and event.widget is not self:
            return
        compact = self.winfo_height() / self._get_window_scaling() < 520
        if compact != self._compact:
            self._compact = compact
            self.details.configure(height=40 if compact else 105)
            self.notice.configure(font=('Segoe UI', 11 if compact else 13))

    def show_details(self, event=None):
        selected = self.tree.selection()
        if selected:
            row = self.rows[selected[0]]
            set_text(self.details, transaction_details(row['title'], row['sender']) +
                f"\nPrzypisujesz do: {row['member']}\nData: {row['date']} · Kwota: {Decimal(row['cents']) / 100:.2f} PLN\n"
                + (row['issue'] or 'Poprawna pozycja, gotowa do zapisu.'))


class ImportWindow(MonityToplevel):
    def __init__(self, master, session, **kwargs):
        super().__init__(master, **kwargs)
        prepare_window(self, master)
        self.title('Import wyciągu — przypisanie wpłat')
        self.geometry('1150x730')
        self.preferred_width = 1150
        self.session, self.plan = session, None
        self.assignments, self.pending, self.rows, self.included = {}, {}, {}, set()
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)
        ctk.CTkLabel(self, text='Wyciąg → przypisania → jeden zapis', font=('Segoe UI', 20, 'bold'), height=28).grid(
            row=0, column=0, sticky='w', padx=20, pady=(8, 2))
        controls = ctk.CTkFrame(self, fg_color='transparent')
        self.controls = controls
        controls.grid(row=1, column=0, sticky='ew', padx=20, pady=2)
        self.btn_select = ctk.CTkButton(controls, text='Wybierz XLSX', command=self.process_file, width=100)
        self.btn_select.grid(row=0, column=0, padx=(0, 6), pady=3)
        self.currency = ctk.CTkOptionMenu(controls, values=['Waluta z kolumny', 'PLN — cały wyciąg'], width=125)
        self.currency.grid(row=0, column=1, padx=6, pady=3)
        self.date_format = ctk.CTkOptionMenu(controls, values=['RRRR-MM-DD', 'DD.MM.RRRR'], width=110)
        self.date_format.grid(row=0, column=2, padx=6, pady=3)
        self.btn_pending = ctk.CTkButton(controls, text='Niezaksięgowane', command=self.load_pending, width=125)
        self.btn_pending.grid(row=0, column=3, padx=6, pady=3)
        self.hint = ctk.CTkLabel(controls, text='Kliknij „Przypisujesz do” i wybierz osobę. ✓ określa zapis.',
            text_color=MUTED, anchor='w', wraplength=1000, height=18, font=('Segoe UI', 11))
        self.hint.grid(row=1, column=0, columnspan=4, sticky='ew', pady=(4, 0))
        table = ctk.CTkFrame(self)
        table.grid(row=2, column=0, sticky='nsew', padx=20, pady=3)
        self.tree = data_table(table, [('include', '✓', 40), ('date', 'Data', 95), ('amount', 'PLN', 85),
            ('description', 'Opis transakcji', 400), ('member', 'Przypisujesz do — kliknij', 280),
            ('state', 'Stan', 135)], selectmode='extended', height=5)
        self.tree.tag_configure('blocked', foreground='#B65348')
        self.tree.tag_configure('review', foreground='#925C13')
        self.tree.bind('<<TreeviewSelect>>', self.show_details)
        self.tree.bind('<ButtonRelease-1>', self.click_row)
        self.tree.bind('<Return>', self.assign)
        self.choice = TableChoice(self.tree)
        self.details = ctk.CTkTextbox(self, height=100)
        self.details.grid(row=3, column=0, sticky='ew', padx=20, pady=2)
        set_text(self.details, 'Opis transakcji i nazwa nadawcy pojawią się po wybraniu wiersza.')
        actions = ctk.CTkFrame(self, fg_color='transparent')
        actions.grid(row=4, column=0, sticky='ew', padx=20, pady=2)
        ctk.CTkButton(actions, text='Uwzględnij przypisane', command=self.include_assigned, width=175).pack(side='left', padx=(0, 8))
        ctk.CTkButton(actions, text='Pomiń zaznaczone', command=self.exclude_selected, width=155, fg_color=MUTED).pack(side='left')
        self.status = ctk.CTkLabel(self, text='Wczytaj wyciąg. Przed zapisem sprawdzisz wspólny podgląd.',
            wraplength=1050, justify='left', anchor='w')
        self.status.grid(row=5, column=0, sticky='ew', padx=20, pady=2)
        footer = ctk.CTkFrame(self, fg_color='transparent')
        footer.grid(row=6, column=0, sticky='ew', padx=20, pady=(2, 6))
        ctk.CTkButton(footer, text='Zamknij', command=self.destroy, width=100, fg_color=MUTED).pack(side='left')
        self.btn_commit = ctk.CTkButton(footer, text='Podgląd wszystkich przypisań', command=self.commit, height=38)
        self.btn_commit.pack(side='right')
        self.load_members()
        self._compact = None
        self.bind('<Configure>', self.layout_controls, add='+')

    def layout_controls(self, event=None):
        if event is not None and event.widget is not self:
            return
        compact = self.winfo_width() / self._get_window_scaling() < 540
        if compact != self._compact:
            self._compact = compact
            self.date_format.grid(row=1 if compact else 0, column=0 if compact else 2, padx=6, pady=3)
            self.btn_pending.grid(row=1 if compact else 0, column=1 if compact else 3, padx=6, pady=3)
            self.hint.grid(row=2 if compact else 1, column=0, columnspan=2 if compact else 4, sticky='ew', pady=(4, 0))
        small_height = self.winfo_height() / self._get_window_scaling() < 550
        self.details.configure(height=30 if small_height else 100)
        self.status.configure(font=('Segoe UI', 11 if small_height else 13), height=18 if small_height else 28)

    def load_members(self):
        with Session(bind=self.session.get_bind()) as operation:
            members = operation.query(Czlonek).order_by(Czlonek.imie_nazwisko, Czlonek.id).all()
            self.members = {m.id: f'{m.imie_nazwisko} · A!{m.numer_identyfikacyjny}' + (' · archiwum' if not m.aktywny else '') for m in members}
            self.public_ids = {m.numer_identyfikacyjny: m.id for m in members}
            self.names = {self.members[m.id]: m.imie_nazwisko for m in members}

    def process_file(self):
        path = filedialog.askopenfilename(parent=self, filetypes=[('Excel', '*.xlsx')])
        if not path:
            return
        try:
            plan = preview_import(self.session, path, load_columns(),
                'PLN' if self.currency.get().startswith('PLN') else None,
                '%Y-%m-%d' if self.date_format.get() == 'RRRR-MM-DD' else '%d.%m.%Y')
            self.choice.close()
            self.plan, self.pending, self.assignments = plan, {}, {}
            self.rows = {str(r.number): dict(key=r.number, title=r.title, sender=r.sender,
                date=r.paid_on.strftime('%Y-%m-%d') if r.paid_on else '—', cents=r.cents,
                public_id=r.public_id, member_id=r.member_id, state=r.state, issue=r.issue) for r in plan.rows}
            self.included = {r.number for r in plan.rows if r.state == 'ready'}
            self.load_members()
            self.render()
        except ValueError as exc:
            messagebox.showerror('Nie można wczytać', str(exc), parent=self)
        except Exception:
            messagebox.showerror('Nie można wczytać', 'Plik XLSX jest nieczytelny lub ma nieobsługiwany format. Nie zapisano danych.', parent=self)

    def target(self, key):
        row = self.rows[str(key)]
        return self.assignments.get(int(key), row.get('member_id') or self.public_ids.get(row['public_id']))

    def values(self, key):
        row = self.rows[str(key)]
        state = {'ready': 'Gotowe', 'review': 'Do sprawdzenia', 'invalid': 'Błędne dane', 'duplicate': 'Duplikat'}[row['state']]
        return ('✓' if int(key) in self.included else '—', row['date'],
            f"{Decimal(row['cents']) / 100:.2f}" if row['cents'] is not None else '—',
            row['title'].replace('\n', ' '), self.members.get(self.target(key), 'Wybierz klienta…'), state)

    def render(self):
        self.choice.close()
        self.tree.delete(*self.tree.get_children())
        for key, row in self.rows.items():
            tag = 'blocked' if row['state'] in ('invalid', 'duplicate') else ('review' if row['state'] == 'review' else '')
            self.tree.insert('', 'end', iid=key, values=self.values(key), tags=(tag,))
        self.update_summary()
        set_text(self.details, 'Wybierz wiersz, aby przeczytać pełny opis transakcji, nadawcę i uwagi.')

    def update_summary(self):
        total = sum(self.rows[str(key)]['cents'] or 0 for key in self.included)
        self.status.configure(text=f'Do zapisu: {len(self.included)} · '
            f'Suma: {Decimal(total) / 100:.2f} PLN · Pominięte: {len(self.rows) - len(self.included)}')

    def show_details(self, event=None):
        selected = self.tree.selection()
        if selected and selected[0] in self.rows:
            row = self.rows[selected[0]]
            set_text(self.details, transaction_details(row['title'], row['sender']) +
                f"\nPrzypisujesz do: {self.members.get(self.target(selected[0]), 'nie wybrano')}\n"
                + (row['issue'] or 'Poprawna pozycja, gotowa do wspólnego zatwierdzenia.'))

    def click_row(self, event):
        key = self.tree.identify_row(event.y)
        column = self.tree.identify_column(event.x)
        if not key:
            return
        self.choice.close()
        if column == '#1':
            if int(key) in self.included:
                self.included.remove(int(key))
            elif self.rows[key]['state'] not in ('invalid', 'duplicate'):
                self.included.add(int(key))
            self.tree.item(key, values=self.values(key))
            self.update_summary()
        elif column == '#5':
            self.tree.selection_set(key)
            self.assign()

    def assign(self, event=None):
        selected = self.tree.selection()
        if not selected:
            return
        key = selected[0]
        if self.rows[key]['state'] in ('invalid', 'duplicate'):
            return
        self.choice.open(key, 'member', {label: member_id for member_id, label in self.members.items()},
            lambda member_id: self.set_assignment(key, member_id), self.names)

    def set_assignment(self, key, member_id):
        if member_id not in self.members or self.rows[str(key)]['state'] in ('invalid', 'duplicate'):
            raise ValueError('Wybierz poprawną pozycję i konkretną kartotekę klienta.')
        self.assignments[int(key)] = member_id
        self.included.add(int(key))
        self.tree.item(str(key), values=self.values(key))
        self.update_summary()
        self.show_details()

    def include_assigned(self):
        self.included = {int(key) for key, row in self.rows.items()
            if row['state'] not in ('invalid', 'duplicate') and self.target(key) in self.members}
        for key in self.rows:
            self.tree.item(key, values=self.values(key))
        self.update_summary()

    def exclude_selected(self):
        self.included.difference_update(int(key) for key in self.tree.selection())
        for key in self.tree.selection():
            self.tree.item(key, values=self.values(key))
        self.update_summary()

    def load_pending(self):
        self.choice.close()
        self.plan, self.assignments = None, {}
        self.pending = {str(row['id']): row for row in pending_imports(self.session.get_bind())}
        self.load_members()
        self.rows = {key: dict(key=int(key), title=row['title'], sender=row.get('sender', ''),
            date=(row['date'] or '—')[:10], cents=row['cents'], public_id=row['public_id'],
            member_id=None, state=row['source_state'], issue=row['issue']) for key, row in self.pending.items()}
        # Kolejka wymaga ponownego przeglądu; żaden wiersz nie jest zatwierdzany w tle.
        self.included = set()
        self.render()

    def snapshot(self):
        return (self.plan, tuple(sorted(self.included)), tuple(sorted(self.assignments.items())),
            tuple(sorted((key, self.target(key), self.members.get(self.target(key))) for key in self.rows)))

    def commit(self):
        self.choice.close()
        try:
            if not self.included:
                raise ValueError('Uwzględnij wpłaty do zapisu (✓). Przypisane pozycje można uwzględnić wspólnie.')
            rows = []
            for key, row in self.rows.items():
                if int(key) not in self.included:
                    continue
                if row['state'] in ('invalid', 'duplicate') or row['cents'] is None:
                    raise ValueError('Błędne pozycje i duplikaty nie mogą być zaksięgowane.')
                if self.target(key) not in self.members:
                    raise ValueError(f'Wiersz {key}: wybierz klienta w prawej kolumnie.')
                rows.append(dict(row, member=self.members[self.target(key)]))
            snapshot = self.snapshot()
            self.confirmation = ImportConfirmation(self, rows, lambda dialog: self.save(snapshot, dialog), len(self.rows) - len(rows))
        except ValueError as exc:
            messagebox.showerror('Sprawdź przypisania', str(exc), parent=self)

    def save(self, snapshot, dialog):
        try:
            if self.snapshot() != snapshot:
                raise ValueError('Przypisania zmieniły się. Otwórz ponownie wspólny podgląd.')
            selected = sorted(self.included)
            if self.plan is None:
                count = post_pending(self.session, selected, self.assignments)
            else:
                count = commit_import(self.session, self.plan, selected, self.assignments,
                    confirmed_new=[r.number for r in self.plan.rows if r.state == 'review' and r.number in self.included])
            dialog.destroy()
            self.load_pending()
            self.status.configure(text=f'Zaksięgowano razem {count} wpłat. Niezaksięgowane pozycje: {len(self.rows)}. '
                'Opis każdej transakcji jest dostępny w karcie finansowej i rejestrze wpłat.')
        except ValueError as exc:
            dialog.destroy()
            messagebox.showerror('Nie zapisano', str(exc), parent=self)
        except Exception:
            dialog.destroy()
            messagebox.showerror('Nie zapisano', 'Cała operacja została wycofana. Odśwież podgląd.', parent=self)
