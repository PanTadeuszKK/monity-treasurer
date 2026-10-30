"""Zgodnościowa nazwa starego importera; bez drugiej implementacji księgowania."""
from import_service import preview_import, commit_import


class ImporterSkladek:
    def __init__(self, session):
        self.session = session

    def importuj_plik(self, sciezka_pliku, **options):
        return preview_import(self.session, sciezka_pliku, **options)

    def zatwierdz(self, plan, selected_rows, **options):
        return commit_import(self.session, plan, selected_rows, **options)
