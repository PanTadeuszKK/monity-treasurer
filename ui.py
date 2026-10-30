"""Wspólna paleta, typografia i zachowanie okien."""
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from tkinter import ttk
import customtkinter as ctk

BG = "#F3F6FA"
INK = "#20334B"
MUTED = "#65758A"
GREEN = "#18735D"
GREEN_HOVER = "#105B49"
RED = "#A65045"
AMBER_BG = "#FFF4E1"
AMBER_INK = "#825C20"
NEUTRAL = "#EFF4F8"
NEUTRAL_HOVER = "#E2EBF3"
BORDER = "#DFE6EE"


def format_pln(value, sign=False):
    """Polski zapis kwoty: 1 234,56 zł. Wejście float/Decimal/int, bez obliczeń na float."""
    amount = Decimal(str(value or 0)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    text = f'{abs(amount):,.2f}'.replace(',', ' ').replace('.', ',')
    prefix = '-' if amount < 0 else ('+' if sign and amount > 0 else '')
    return f'{prefix}{text} zł'


def format_balance(value):
    """Saldo słowami (wewnętrznie minus = zaległość): „zaległość 35,00 zł”, „nadpłata 10,00 zł”."""
    amount = Decimal(str(value or 0))
    if amount < 0:
        return f'zaległość {format_pln(-amount)}'
    if amount > 0:
        return f'nadpłata {format_pln(amount)}'
    return 'rozliczone (0,00 zł)'


def balance_tags(tree):
    """Kolor salda w tabeli: zaległość na czerwono, nadpłata na zielono."""
    tree.tag_configure('debt', foreground=RED)
    tree.tag_configure('credit', foreground=GREEN)


def balance_tag(value):
    value = value or 0
    return ('debt',) if value < 0 else (('credit',) if value > 0 else ())


def secondary_button(parent, **kwargs):
    """Neutralny przycisk pomocniczy (np. wyczyść), bez koloru sugerującego usuwanie."""
    options = dict(fg_color=NEUTRAL, hover_color=NEUTRAL_HOVER, text_color=INK)
    options.update(kwargs)
    return ctk.CTkButton(parent, **options)


def live_search(entry, callback, delay=200):
    """Filtruj podczas pisania, z krótkim opóźnieniem; Enter nadal działa od razu."""
    def schedule(event=None):
        if event is not None and event.keysym in ('Return', 'Tab', 'Up', 'Down'):
            return
        pending = getattr(entry, '_search_after', None)
        if pending is not None:
            entry.after_cancel(pending)
        entry._search_after = entry.after(delay, run)
    def run():
        entry._search_after = None
        if entry.winfo_exists():
            callback()
    entry.bind('<KeyRelease>', schedule, add='+')


def configure_theme():
    ctk.set_appearance_mode("Light")
    ctk.set_default_color_theme(str(Path(__file__).resolve().parent / 'assets' / 'monity-theme.json'))


def table_style(window):
    style = ttk.Style(window)
    if style.theme_use() != 'clam':
        style.theme_use('clam')
    style.configure('Treeview', background='white', fieldbackground='white', foreground=INK,
                    rowheight=36, font=('Segoe UI', 11), borderwidth=0)
    style.configure('Treeview.Heading', background='#EAF0F6', foreground=INK,
                    font=('Segoe UI', 11, 'bold'), padding=(10, 10), relief='flat')
    style.map('Treeview', background=[('selected', '#DDEFE8')], foreground=[('selected', '#104D3D')])
    style.map('Treeview.Heading', background=[('active', '#DFE8F1')])


def window_geometry(screen_width, screen_height, requested_width, requested_height, scale=1.0, parent=None):
    """Wymiary logiczne CTk, współrzędne pulpitu w pikselach."""
    available_w = max(1, int((screen_width - 32) / scale))
    available_h = max(1, int((screen_height - 120) / scale))
    width = min(max(320, int(requested_width)), available_w)
    height = min(max(240, int(requested_height)), available_h)
    pixel_w, pixel_h = round(width * scale), round(height * scale)
    px, py, pw, ph = parent or (0, 0, screen_width, screen_height - 40)
    x = max(8, min(px + (pw - pixel_w)//2, screen_width-pixel_w-8))
    y = max(8, min(py + (ph - pixel_h)//2, screen_height-pixel_h-80))
    return width, height, x, y


def fit_window(window, master=None):
    if not window.winfo_exists():
        return
    window.update_idletasks()
    scale = window._get_window_scaling()
    width = max(window._current_width, window.winfo_reqwidth()/scale, getattr(window, 'preferred_width', 0))
    height = max(window._current_height, window.winfo_reqheight()/scale)
    parent = None
    if master is not None:
        parent = (master.winfo_rootx(), master.winfo_rooty(), master.winfo_width(), master.winfo_height())
    width, height, x, y = window_geometry(window.winfo_screenwidth(), window.winfo_screenheight(), width, height, scale, parent)
    window.minsize(min(420, width), min(300, height))
    window.geometry(f'{width}x{height}+{x}+{y}')
    window.after_idle(lambda: wrap_labels(window))


def wrap_labels(window):
    if not window.winfo_exists():
        return
    def walk(widget):
        for child in widget.winfo_children():
            if isinstance(child, ctk.CTkLabel) and not getattr(child, '_nowrap', False) and child.master.winfo_width()>50:
                if not hasattr(child, '_original_wraplength'):
                    child._original_wraplength = child.cget('wraplength') or 0
                parent_width = child.master.winfo_width()/child._get_widget_scaling()
                try:
                    layout = child.pack_info() if child.winfo_manager()=='pack' else child.grid_info()
                    padding = layout.get('padx',0)
                    if isinstance(padding,(tuple,list)):
                        padding = sum(float(value) for value in padding)
                    else:
                        padding = 2*float(padding)
                except (ValueError,TypeError):
                    padding = 20
                available = max(60,int(parent_width-padding-16))
                desired = min(available,child._original_wraplength) if child._original_wraplength else available
                if abs((child.cget('wraplength') or 0)-desired)>2:
                    child.configure(wraplength=desired)
            if isinstance(child, ctk.CTkButton) and getattr(child, '_text_label', None) is not None and child.winfo_width()>50:
                child._text_label.configure(wraplength=max(60,child.winfo_width()-20*child._get_widget_scaling()),
                                            justify='left' if child.cget('anchor')=='w' else 'center')
            walk(child)
    walk(window)


def prepare_window(window, master):
    window.transient(master)
    window.bind('<Escape>', lambda event: window.destroy())
    window.after_idle(lambda: (table_style(window), fit_window(window, master)))
    window.after(150, lambda: fit_window(window, master))
    def resized(event):
        if event.widget is window:
            pending = getattr(window, '_layout_after', None)
            if pending:
                try:
                    window.after_cancel(pending)
                except Exception:
                    pass
            window._layout_after = window.after(60, lambda: wrap_labels(window))
    window.bind('<Configure>', resized, add='+')


def register_job(window, thread, stop_event=None):
    root = window._root()
    if not hasattr(root, 'background_jobs'):
        root.background_jobs = []
    root.background_jobs = [(job, event) for job, event in root.background_jobs if job.is_alive()]
    root.background_jobs.append((thread, stop_event))


def cancel_callbacks(window, all_tasks=False):
    """Nie zostawiaj timerów odwołujących się do zniszczonych widgetów."""
    owners={}
    def collect(widget):
        for command in getattr(widget, '_tclCommands', None) or []:
            owners[command]=widget
        for child in widget.winfo_children():
            collect(child)
    try:
        collect(window)
        for task in window.tk.splitlist(window.tk.call('after','info')):
            script=window.tk.call('after','info',task)[0]
            command=window.tk.splitlist(script)[0]
            if all_tasks or command in owners:
                owner=owners.get(command)
                if owner is not None:
                    owner.after_cancel(task)
                else:
                    window.tk.call("after", "cancel", task)
    except Exception:
        # Okno może być już niszczone przez nadrzędny interpreter.
        pass


class MonityToplevel(ctk.CTkToplevel):
    def _set_scaling(self, *args, **kwargs):
        super()._set_scaling(*args, **kwargs)
        if hasattr(self, 'master'):
            self.after_idle(lambda: fit_window(self, self.master))

    def destroy(self):
        cancel_callbacks(self)
        super().destroy()


class ReviewTabview(ctk.CTkTabview):
    def _grid_forget_all_tabs(self, exclude_name=None):
        # CTk 5.2.2 chowa poprzednie zakładki po 100 ms. Przy szybkim
        # przejściu do podglądu stary timer nie może schować bieżącej zakładki.
        super()._grid_forget_all_tabs(exclude_name=self.get() if exclude_name is not None else None)


def pack_footer(widget, **kwargs):
    """Rezerwuj miejsce na akcję przed przydzieleniem miejsca elastycznej treści."""
    siblings=[child for child in widget.master.pack_slaves() if child is not widget]
    options=dict(side="bottom",pady=12,**kwargs)
    if siblings:
        options["before"]=siblings[0]
    widget.pack(**options)


def data_table(parent, columns, **kwargs):
    """Tabela z przewijaniem w obu kierunkach; columns: (klucz, etykieta, szerokość)."""
    parent.grid_rowconfigure(0, weight=1)
    parent.grid_columnconfigure(0, weight=1)
    tree = ttk.Treeview(parent, columns=[c[0] for c in columns], show='headings', **kwargs)
    for key, title, width in columns:
        tree.heading(key, text=title)
        tree.column(key, width=width, minwidth=min(width, 70), stretch=key in ('description', 'member', 'name'))
    yscroll = ttk.Scrollbar(parent, orient='vertical', command=tree.yview)
    xscroll = ttk.Scrollbar(parent, orient='horizontal', command=tree.xview)
    tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
    tree.grid(row=0, column=0, sticky='nsew')
    yscroll.grid(row=0, column=1, sticky='ns')
    xscroll.grid(row=1, column=0, sticky='ew')
    return tree


def set_text(widget, text):
    widget.configure(state='normal')
    widget.delete('1.0', 'end')
    widget.insert('1.0', text)
    widget.configure(state='disabled')


class TableChoice:
    """Wybór w komórce tabeli; wpisanie nazwiska filtruje, dopiero wybór zapisuje."""
    def __init__(self, tree):
        self.tree, self.editor = tree, None

    def close(self):
        if self.editor is not None:
            self.editor.destroy()
            self.editor = None

    def open(self, key, column, labels, callback, names=None):
        from member_search import name_matches
        self.close()
        self.tree.see(key)
        self.tree.update_idletasks()
        box = self.tree.bbox(key, column)
        if not box:
            return
        x, y, width, height = box
        editor = ttk.Combobox(self.tree, values=list(labels), state='normal')
        self.editor = editor
        editor.place(x=x, y=y, width=width, height=height)
        editor.focus_set()
        def choose(event=None):
            value = editor.get()
            if value in labels:
                callback(labels[value])
                self.close()
                self.tree.focus_set()
        def search(event):
            if event.keysym not in ('Return', 'Escape', 'Up', 'Down'):
                query = editor.get()
                editor.configure(values=[label for label in labels
                    if name_matches((names or {}).get(label, label), query)])
        editor.bind('<<ComboboxSelected>>', choose)
        editor.bind('<Return>', choose)
        editor.bind('<Escape>', lambda event: (self.close(), 'break')[-1])
        editor.bind('<KeyRelease>', search)
        return editor
