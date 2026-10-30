"""Wspólny katalog danych.

Kolejność: zmienna MONITY_DATA_DIR, plik katalog_danych.txt obok kodu
(zapisuje go tools/przenies_dane.py), w ostatniej kolejności katalog kodu.
"""
import os
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
POINTER_FILE = PROJECT_DIR / "katalog_danych.txt"


def default_data_dir():
    """Proponowany katalog danych: w profilu użytkownika, poza kodem i poza OneDrive."""
    return Path.home() / "MonityDane"


def data_dir():
    configured = os.environ.get("MONITY_DATA_DIR")
    if configured:
        path = Path(configured).expanduser()
        if not path.is_absolute():
            raise ValueError("MONITY_DATA_DIR musi być ścieżką bezwzględną.")
        return path.resolve()
    if POINTER_FILE.is_file():
        path = Path(POINTER_FILE.read_text(encoding="utf-8").strip()).expanduser()
        if not path.is_absolute():
            raise ValueError(f"{POINTER_FILE.name} musi zawierać ścieżkę bezwzględną.")
        if not path.is_dir():
            # Bez tej kontroli aplikacja założyłaby nową, pustą bazę.
            raise FileNotFoundError(f"Katalog danych wskazany w {POINTER_FILE.name} nie istnieje: {path}. "
                                    "Podłącz dysk lub popraw wskazanie.")
        return path.resolve()
    return PROJECT_DIR


def data_path(name):
    return data_dir() / name


def backup_dir():
    return data_dir() / "kopie"
