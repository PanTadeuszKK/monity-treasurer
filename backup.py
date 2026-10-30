"""Spójna kopia SQLite bez nadpisywania pliku docelowego."""
from contextlib import closing
import argparse
from datetime import datetime
import json
from pathlib import Path
import sqlite3

from paths import data_path


def backup_database(source, destination):
    source = Path(source).resolve()
    destination = Path(destination).resolve()
    if not source.is_file():
        raise FileNotFoundError("Nie znaleziono bazy źródłowej.")
    # Wyłączny zapis: także wyklucza nadpisanie źródła i istniejącej kopii.
    with destination.open("xb"):
        pass
    try:
        with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as src:
            with closing(sqlite3.connect(destination)) as dst:
                src.backup(dst)
                if dst.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                    raise RuntimeError("Kontrola integralności kopii nie powiodła się.")
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    return destination


AUTO_PREFIX = "auto-"


def timestamped_backup(source, folder, prefix=AUTO_PREFIX):
    """Kopia o nazwie z datą i godziną; nie nadpisuje istniejących plików."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = folder / f"{prefix}monity-{stamp}.db"
    counter = 1
    while target.exists():
        target = folder / f"{prefix}monity-{stamp}-{counter}.db"
        counter += 1
    return backup_database(source, target)


def prune_auto_backups(folder, keep=30):
    """Usuwa wyłącznie najstarsze kopie automatyczne; ręcznych kopii nie rusza."""
    copies = sorted(Path(folder).glob(f"{AUTO_PREFIX}monity-*.db"), key=lambda p: p.name, reverse=True)
    for old in copies[keep:]:
        old.unlink(missing_ok=True)


def backup_settings(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def automatic_backup(source, folder, settings_path, keep=30):
    """Kopia przy zamknięciu: zawsze do folderu kopii, opcjonalnie także do folderu dodatkowego.

    Zwraca listę błędów (puste = sukces), aby zamknięcie aplikacji nie zostało zablokowane.
    """
    errors = []
    if not Path(source).is_file():
        return errors
    targets = [Path(folder)]
    extra = backup_settings(settings_path).get("dodatkowy_katalog")
    if extra:
        targets.append(Path(extra))
    for target in targets:
        try:
            timestamped_backup(source, target)
            prune_auto_backups(target, keep)
        except Exception as exc:
            errors.append(f"{target}: {exc}")
    return errors


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--source", type=Path, default=data_path("monity.db"))
    args = parser.parse_args()
    backup_database(args.source, args.destination)
    print("Utworzono i sprawdzono kopię SQLite.")
