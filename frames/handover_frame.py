"""Kopie zapasowe i coroczne przekazanie aplikacji następcy."""
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from backup import AUTO_PREFIX, backup_settings, timestamped_backup
from mailer import email_config_path, load_email_config
from paths import backup_dir, data_dir, data_path
from ui import MonityToplevel, prepare_window, secondary_button, BORDER, INK, MUTED, RED

SUCCESSOR_STEPS = (
    "1. Zainstaluj Pythona i zależności według README (nowe środowisko, nie kopiuj .venv).",
    "2. Skopiuj kod aplikacji oraz plik bazy z kopii przekazania do własnego katalogu danych.",
    "3. Uruchom tools/przenies_dane.py lub ustaw MONITY_DATA_DIR na ten katalog.",
    "4. Wygeneruj WŁASNE hasło aplikacji Google i wpisz je w Ustawienia → Poczta Gmail.",
    "5. Porównaj salda w aplikacji z zestawieniem kadencji i stanem konta bankowego.",
)


class HandoverWindow(MonityToplevel):
    def __init__(self, master, session, **kwargs):
        super().__init__(master, **kwargs)
        prepare_window(self, master)
        self.app, self.session = master, session
        self.title('Kopie zapasowe i przekazanie kadencji')
        self.geometry('720x640')
        body = ctk.CTkScrollableFrame(self, fg_color='transparent')
        body.pack(fill='both', expand=True, padx=8, pady=8)

        card = self._card(body, 'Kopie zapasowe',
            'Przy każdym zamknięciu aplikacji powstaje sprawdzona kopia bazy; przechowywane jest 30 najnowszych '
            'kopii automatycznych. Ustaw dodatkowy folder na innym nośniku (pendrive, dysk zewnętrzny), '
            'aby awaria laptopa nie oznaczała utraty danych. Nie wybieraj folderu synchronizowanego (OneDrive).')
        self.lbl_kopie = ctk.CTkLabel(card, text='', anchor='w', justify='left', text_color=INK)
        self.lbl_kopie.pack(fill='x', padx=18, pady=(0, 8))
        row = ctk.CTkFrame(card, fg_color='transparent')
        row.pack(fill='x', padx=18, pady=(0, 14))
        ctk.CTkButton(row, text='Utwórz kopię teraz', command=self.backup_now, width=170).pack(side='left', padx=(0, 8))
        secondary_button(row, text='Otwórz folder kopii', command=self.open_backup_folder, width=160).pack(side='left', padx=(0, 8))
        secondary_button(row, text='Dodatkowy folder…', command=self.choose_extra, width=150).pack(side='left')

        card = self._card(body, 'Przekazanie kadencji (czerwiec)',
            'Wykonaj po zamknięciu maja, przed oddaniem aplikacji następcy.')
        for label, command in (('1. Zestawienie kadencji — Excel', self.app.open_yearly_stats),
                               ('2. Bieżące salda i zaległości', self.app.open_monthly_stats),
                               ('3. Kopia bazy dla następcy…', self.handover_copy)):
            ctk.CTkButton(card, text=label, command=command, anchor='w', height=36).pack(fill='x', padx=18, pady=(0, 8))
        self.btn_odlacz = ctk.CTkButton(card, text='4. Odłącz moją pocztę Gmail', command=self.disconnect_mail,
            anchor='w', height=36, fg_color=RED, hover_color='#8A3F36')
        self.btn_odlacz.pack(fill='x', padx=18, pady=(0, 6))
        ctk.CTkLabel(card, text='Po odłączeniu unieważnij hasło aplikacji w ustawieniach konta Google '
            '(Bezpieczeństwo → Hasła aplikacji). Kopia bazy nie zawiera hasła poczty.',
            text_color=MUTED, anchor='w', justify='left').pack(fill='x', padx=18, pady=(0, 14))

        card = self._card(body, 'Co robi następca', '')
        ctk.CTkLabel(card, text='\n'.join(SUCCESSOR_STEPS), anchor='w', justify='left',
                     text_color=INK).pack(fill='x', padx=18, pady=(0, 14))
        self.refresh()

    def _card(self, parent, title, description):
        frame = ctk.CTkFrame(parent, fg_color='white', corner_radius=14, border_width=1, border_color=BORDER)
        frame.pack(fill='x', padx=8, pady=8)
        ctk.CTkLabel(frame, text=title, font=('Segoe UI', 17, 'bold'), text_color=INK,
                     anchor='w').pack(fill='x', padx=18, pady=(14, 4))
        if description:
            ctk.CTkLabel(frame, text=description, text_color=MUTED, anchor='w',
                         justify='left').pack(fill='x', padx=18, pady=(0, 8))
        return frame

    def settings_path(self):
        return data_path('config_kopie.json')

    def refresh(self):
        copies = sorted(backup_dir().glob('*.db'), key=lambda p: p.stat().st_mtime, reverse=True) if backup_dir().is_dir() else []
        last = f'{datetime.fromtimestamp(copies[0].stat().st_mtime):%d.%m.%Y %H:%M}' if copies else 'jeszcze brak'
        extra = backup_settings(self.settings_path()).get('dodatkowy_katalog') or 'nie ustawiono'
        self.lbl_kopie.configure(text=f'Katalog danych: {data_dir()}\nFolder kopii: {backup_dir()}\n'
            f'Ostatnia kopia: {last} · kopii: {len(copies)}\nDodatkowy folder: {extra}')
        configured = bool(load_email_config())
        self.btn_odlacz.configure(state='normal' if configured else 'disabled',
            text='4. Odłącz moją pocztę Gmail' if configured else '4. Poczta Gmail odłączona')

    def backup_now(self):
        try:
            target = timestamped_backup(data_path('monity.db'), backup_dir(), prefix='reczna-')
        except Exception as exc:
            messagebox.showerror('Kopia zapasowa', f'Nie udało się utworzyć kopii: {exc}', parent=self)
            return
        messagebox.showinfo('Kopia zapasowa', f'Utworzono i sprawdzono kopię:\n{target}', parent=self)
        self.refresh()

    def open_backup_folder(self):
        folder = backup_dir()
        folder.mkdir(parents=True, exist_ok=True)
        if sys.platform.startswith('win'):
            os.startfile(folder)
        else:
            subprocess.Popen(['open' if sys.platform == 'darwin' else 'xdg-open', str(folder)])

    def choose_extra(self):
        current = backup_settings(self.settings_path())
        folder = filedialog.askdirectory(parent=self, title='Dodatkowy folder kopii (np. pendrive)')
        if not folder:
            if current.get('dodatkowy_katalog') and messagebox.askyesno(
                    'Dodatkowy folder', 'Wyłączyć kopie do dodatkowego folderu?', parent=self):
                current.pop('dodatkowy_katalog')
                self.settings_path().write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding='utf-8')
                self.refresh()
            return
        if 'onedrive' in folder.lower() and not messagebox.askyesno('Dodatkowy folder',
                'Ten folder leży w OneDrive. Kopie (zamknięte pliki) mogą tam trafić, ale nigdy nie przenoś tam '
                'pracującej bazy. Kontynuować?', parent=self):
            return
        current['dodatkowy_katalog'] = folder
        self.settings_path().write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding='utf-8')
        self.refresh()

    def handover_copy(self):
        folder = filedialog.askdirectory(parent=self, title='Folder kopii dla następcy (np. pendrive)')
        if not folder:
            return
        try:
            target = timestamped_backup(data_path('monity.db'), Path(folder), prefix='przekazanie-')
            columns = data_path('config_kolumn.json')
            if columns.is_file() and not (Path(folder) / columns.name).exists():
                shutil.copy2(columns, Path(folder) / columns.name)
        except Exception as exc:
            messagebox.showerror('Kopia dla następcy', f'Nie udało się utworzyć kopii: {exc}', parent=self)
            return
        messagebox.showinfo('Kopia dla następcy', f'Utworzono kopię bazy:\n{target}\n\nHasło poczty NIE zostało '
            'skopiowane. Kopia zawiera dane osobowe klientów — przekaż ją osobiście, nie mailem.', parent=self)

    def disconnect_mail(self):
        path = email_config_path()
        if not messagebox.askyesno('Odłącz pocztę Gmail',
                f'Usunąć zapisane dane logowania Gmail?\n{path}\n\nWysyłka wiadomości przestanie działać do czasu, '
                'aż następca wpisze własne hasło aplikacji. Historia wysyłek zostaje w bazie.', parent=self):
            return
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            messagebox.showerror('Odłącz pocztę Gmail', f'Nie udało się usunąć pliku: {exc}', parent=self)
            return
        messagebox.showinfo('Odłącz pocztę Gmail', 'Dane logowania usunięte. Unieważnij teraz hasło aplikacji '
            'w koncie Google.', parent=self)
        self.refresh()
