"""Przeniesienie bazy i konfiguracji z katalogu kodu do osobnego katalogu danych.

Bez --wykonaj tylko pokazuje plan. Z --wykonaj: spójna kopia SQLite (mechanizm backup),
kopie plików konfiguracji, a na końcu zapis wskazania katalog_danych.txt.
Oryginałów nie usuwa — zrób to ręcznie po sprawdzeniu, że aplikacja działa z nowego miejsca.
Uruchamiaj przy ZAMKNIĘTEJ aplikacji.
"""
import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backup import backup_database  # noqa: E402
from paths import POINTER_FILE, data_dir, default_data_dir  # noqa: E402

CONFIG_FILES = ("config_email.json", "config_kolumn.json", "config_kopie.json")
# Pozostałości nieużywanej integracji OAuth — nie kopiujemy sekretów, których aplikacja nie potrzebuje.
UNUSED_SECRETS = ("credentials.json", "token.json")


def plan(source, target):
    steps, problems = [], []
    if source.resolve() == target.resolve():
        problems.append("Katalog docelowy jest tym samym katalogiem co obecny.")
    if "onedrive" in str(target).lower():
        problems.append("Katalog docelowy leży w OneDrive. Synchronizacja otwartej bazy SQLite grozi jej uszkodzeniem.")
    database = source / "monity.db"
    if database.is_file():
        steps.append(("baza", database, target / "monity.db"))
    for name in CONFIG_FILES:
        if (source / name).is_file():
            steps.append(("plik", source / name, target / name))
    for _, _, destination in steps:
        if destination.exists():
            problems.append(f"Plik już istnieje w katalogu docelowym: {destination.name}")
    return steps, problems


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cel", type=Path, default=default_data_dir(), help="katalog danych (domyślnie %(default)s)")
    parser.add_argument("--wykonaj", action="store_true", help="wykonaj przeniesienie (bez tego: tylko podgląd)")
    args = parser.parse_args(argv)
    source, target = data_dir(), args.cel.expanduser().resolve()
    steps, problems = plan(source, target)
    print(f"Obecny katalog danych: {source}")
    print(f"Nowy katalog danych:   {target}")
    for kind, src, dst in steps:
        print(f"  {kind}: {src.name} -> {dst}")
    if not any(kind == "baza" for kind, _, _ in steps):
        print("  (brak monity.db w obecnym katalogu — aplikacja utworzy nową bazę w nowym miejscu)")
    leftovers = [name for name in UNUSED_SECRETS if (source / name).exists()]
    if leftovers:
        print("  Nie kopiuję nieużywanych sekretów: " + ", ".join(leftovers)
              + ". Usuń je i unieważnij dostęp w koncie Google.")
    for problem in problems:
        print("BŁĄD: " + problem)
    if problems:
        return 1
    if not args.wykonaj:
        print("Podgląd. Aby przenieść, zamknij aplikację i uruchom ponownie z --wykonaj.")
        return 0
    target.mkdir(parents=True, exist_ok=True)
    for kind, src, dst in steps:
        if kind == "baza":
            backup_database(src, dst)
        else:
            shutil.copy2(src, dst)
    POINTER_FILE.write_text(str(target), encoding="utf-8")
    print(f"Gotowe. Wskazanie zapisano w {POINTER_FILE.name}.")
    print("Uruchom aplikację i sprawdź dane. Dopiero potem usuń stare pliki z katalogu kodu:")
    for _, src, _ in steps:
        print(f"  {src}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
