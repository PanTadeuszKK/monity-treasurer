import json
import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))

import paths
from backup import automatic_backup, prune_auto_backups, timestamped_backup
from models import init_db


def make_db(path):
    init_db(path).dispose()
    return path


class DataLocationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.pointer = self.root / 'katalog_danych.txt'
        self.env = patch.dict(os.environ, {}, clear=False)
        self.env.start()
        os.environ.pop('MONITY_DATA_DIR', None)
        self.patches = [patch.object(paths, 'POINTER_FILE', self.pointer),
                        patch.object(paths, 'PROJECT_DIR', self.root / 'kod')]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in self.patches:
            item.stop()
        self.env.stop()
        self.tmp.cleanup()

    def test_pointer_is_used_and_missing_directory_is_an_error(self):
        self.assertEqual(paths.data_dir(), self.root / 'kod')
        target = self.root / 'dane'
        target.mkdir()
        self.pointer.write_text(str(target), encoding='utf-8')
        self.assertEqual(paths.data_dir(), target.resolve())
        target.rmdir()
        with self.assertRaises(FileNotFoundError):
            paths.data_dir()

    def test_environment_variable_wins_over_pointer(self):
        self.pointer.write_text(str(self.root / 'brak'), encoding='utf-8')
        os.environ['MONITY_DATA_DIR'] = str(self.root)
        self.assertEqual(paths.data_dir(), self.root.resolve())

    def test_move_tool_copies_database_and_config_but_not_unused_secrets(self):
        import przenies_dane
        source = self.root / 'kod'
        source.mkdir()
        make_db(source / 'monity.db')
        (source / 'config_kolumn.json').write_text('{}', encoding='utf-8')
        (source / 'token.json').write_text('{}', encoding='utf-8')
        target = self.root / 'MonityDane'
        with patch.object(przenies_dane, 'POINTER_FILE', self.pointer):
            self.assertEqual(przenies_dane.main(['--cel', str(target)]), 0)
            self.assertFalse(target.exists())  # podgląd niczego nie zapisuje
            self.assertEqual(przenies_dane.main(['--cel', str(target), '--wykonaj']), 0)
        self.assertTrue((target / 'monity.db').is_file())
        self.assertTrue((target / 'config_kolumn.json').is_file())
        self.assertFalse((target / 'token.json').exists())
        self.assertTrue((source / 'monity.db').is_file())  # oryginał zostaje
        self.assertEqual(paths.data_dir(), target.resolve())
        with patch.object(przenies_dane, 'POINTER_FILE', self.pointer):
            # Ponowne uruchomienie nie nadpisuje danych w nowym miejscu.
            self.assertEqual(przenies_dane.main(['--cel', str(self.root / 'MonityDane')]), 1)

    def test_move_tool_refuses_onedrive(self):
        import przenies_dane
        (self.root / 'kod').mkdir()
        self.assertEqual(przenies_dane.main(['--cel', str(self.root / 'OneDrive' / 'Dane')]), 1)


class AutomaticBackupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = make_db(self.root / 'monity.db')

    def tearDown(self):
        self.tmp.cleanup()

    def test_backup_to_main_and_extra_folder_with_integrity(self):
        extra = self.root / 'pendrive'
        settings = self.root / 'config_kopie.json'
        settings.write_text(json.dumps({'dodatkowy_katalog': str(extra)}), encoding='utf-8')
        self.assertEqual(automatic_backup(self.db, self.root / 'kopie', settings), [])
        for folder in (self.root / 'kopie', extra):
            copies = list(folder.glob('auto-monity-*.db'))
            self.assertEqual(len(copies), 1)
            with closing(sqlite3.connect(copies[0])) as connection:
                self.assertEqual(connection.execute('PRAGMA integrity_check').fetchone(), ('ok',))

    def test_missing_database_and_unavailable_extra_folder(self):
        self.assertEqual(automatic_backup(self.root / 'brak.db', self.root / 'kopie', self.root / 'x.json'), [])
        blocker = self.root / 'plik'
        blocker.write_text('x', encoding='utf-8')
        settings = self.root / 'config_kopie.json'
        settings.write_text(json.dumps({'dodatkowy_katalog': str(blocker)}), encoding='utf-8')
        errors = automatic_backup(self.db, self.root / 'kopie', settings)
        self.assertEqual(len(errors), 1)
        self.assertEqual(len(list((self.root / 'kopie').glob('*.db'))), 1)

    def test_prune_keeps_newest_auto_copies_and_manual_ones(self):
        folder = self.root / 'kopie'
        folder.mkdir()
        for day in range(1, 6):
            (folder / f'auto-monity-2026100{day}-120000.db').write_bytes(b'')
        manual = timestamped_backup(self.db, folder, prefix='reczna-')
        prune_auto_backups(folder, keep=2)
        self.assertEqual(sorted(p.name for p in folder.glob('auto-*.db')),
                         ['auto-monity-20261004-120000.db', 'auto-monity-20261005-120000.db'])
        self.assertTrue(manual.exists())


if __name__ == '__main__':
    unittest.main()
