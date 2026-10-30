"""Nowe widoki finansowe: syntetyczna baza, bez poczty i danych użytkownika."""
import unittest
from pathlib import Path
from unittest.mock import patch
import pandas as pd
import customtkinter as ctk
import gui_smoke as fixtures
from member_ledger import member_ledger
from models import Czlonek, Wplata, KorektaStawki, NaliczenieCzlonka, NaliczenieMiesiaca, StatusNaliczenia, HistoriaNaliczen
from ui import fit_window


class FinancialReviewGuiTests(unittest.TestCase):
    setUp = fixtures.GuiSmokeTests.setUp
    tearDown = fixtures.GuiSmokeTests.tearDown
    windows = fixtures.GuiSmokeTests.windows
    open = fixtures.GuiSmokeTests.open
    close_windows = fixtures.GuiSmokeTests.close_windows

    def imported(self, rows=None):
        path = Path(self.tmp.name) / 'review.xlsx'
        pd.DataFrame(rows or [
            ['2026-06-15', '35', 'A!12 pełny opis', 'PLN', 'Nadawca Jeden'],
            ['2026-06-16', '40', 'Bez ID — składka', 'PLN', 'Nadawca Dwa']],
            columns=['Data operacji', 'Kwota', 'Opis transakcji', 'Waluta', 'Nazwa nadawcy']).to_excel(path, index=False)
        window = self.open('import_excel')
        with patch('tkinter.filedialog.askopenfilename', return_value=str(path)):
            window.process_file()
        self.app.update()
        return window

    def test_all_import_assignments_one_table_one_save_and_source_visible(self):
        window = self.imported()
        self.assertEqual(window.included, {2})
        member = self.app.session.query(Czlonek).one()
        window.tree.selection_set('3')
        window.assign()
        self.app.update()
        editor = window.choice.editor
        self.assertIsNotNone(editor)
        editor.set(window.members[member.id])
        editor.event_generate('<<ComboboxSelected>>')
        self.app.update()
        self.assertEqual(window.included, {2, 3})
        self.assertEqual(self.app.session.query(Wplata).count(), 1)
        window.commit()
        self.app.update()
        dialog = window.confirmation
        self.assertEqual(len(dialog.tree.get_children()), 2)
        self.assertEqual(dialog.tree['columns'], ('description', 'member'))
        self.assertIn('Jan Przykładowy', dialog.tree.item('3', 'values')[1])
        dialog.btn_save.invoke()
        self.app.update()
        self.assertEqual(self.app.session.query(Wplata).count(), 3)
        self.assertEqual(self.app.session.query(Czlonek).one().bilans_otwarcia, 40)
        ledger = member_ledger(self.app.session, member.id)
        row = next(r for r in ledger['rows'] if r.description == 'Bez ID — składka')
        self.assertIn('Nadawca Dwa', row.details)
        self.assertEqual(len(window.pending), 0)

    def test_import_preview_cancel_and_details_selection_do_not_change_included(self):
        window = self.imported()
        window.tree.selection_set('3')
        window.show_details()
        self.assertEqual(window.included, {2})
        window.commit()
        self.app.update()
        window.confirmation.destroy()
        self.assertEqual(self.app.session.query(Wplata).count(), 1)
        self.assertIn('Nadawca Dwa', window.details.get('1.0', 'end'))

    def test_same_names_require_specific_choice_and_archived_member_can_receive_payment(self):
        original = self.app.session.query(Czlonek).one()
        archived = Czlonek(numer_identyfikacyjny=13, imie_nazwisko=original.imie_nazwisko,
            status_id=original.status_id, aktywny=False, bilans_otwarcia=0,
            rok_dolaczenia=2026, miesiac_dolaczenia=6, rok_odejscia=2026, miesiac_odejscia=6)
        self.app.session.add(archived)
        self.app.session.commit()
        window = self.imported()
        window.tree.selection_set('3')
        window.assign()
        editor = window.choice.editor
        editor.set(original.imie_nazwisko)
        editor.event_generate('<<ComboboxSelected>>')
        self.assertNotIn(3, window.assignments)
        editor.set(window.members[archived.id])
        editor.event_generate('<<ComboboxSelected>>')
        self.assertEqual(window.assignments[3], archived.id)
        window.commit()
        self.app.update()
        window.confirmation.btn_save.invoke()
        self.app.update()
        self.app.session.expire_all()
        self.assertEqual(archived.bilans_otwarcia, 40)
        self.assertEqual(original.bilans_otwarcia, 0)

    def test_all_known_rows_default_included_invalid_and_unmatched_not_posted(self):
        window = self.imported([
            ['2026-06-15', '35', 'A!12 czerwiec', 'PLN', 'Nadawca'],
            ['2026-07-15', '35', 'A!12 lipiec', 'PLN', 'Nadawca'],
            ['bad', '35', 'A!12 błędny', 'PLN', 'Nadawca'],
            ['2026-08-15', '35', 'Brak ID', 'PLN', 'Nadawca']])
        self.assertEqual(window.included, {2, 3})
        window.commit()
        self.app.update()
        window.confirmation.btn_save.invoke()
        self.app.update()
        self.assertEqual(self.app.session.query(Wplata).count(), 3)
        self.assertEqual(len(window.pending), 2)
        window.include_assigned()
        self.assertEqual(window.included, set())

    def test_unknown_target_blocks_whole_preview_and_stale_assignments_do_not_save(self):
        window = self.imported()
        window.included.add(3)
        with patch('tkinter.messagebox.showerror') as error:
            window.commit()
            self.assertTrue(error.called)
        self.assertEqual(self.app.session.query(Wplata).count(), 1)
        member = self.app.session.query(Czlonek).one()
        window.set_assignment('3', member.id)
        window.commit()
        self.app.update()
        window.included.remove(2)
        with patch('tkinter.messagebox.showerror') as error:
            window.confirmation.btn_save.invoke()
            self.assertTrue(error.called)
        self.assertEqual(self.app.session.query(Wplata).count(), 1)

    def test_fee_preview_has_person_month_before_after_and_no_write_until_confirm(self):
        window = self.open('open_change_fees')
        for entry in window.entry_dict.values():
            entry.delete(0, 'end')
            entry.insert(0, '40')
        window.zapisz_zmiany()
        self.app.update()
        self.assertEqual(window.tabs.get(), 'Podgląd zmian')
        self.assertEqual(len(window.preview_tree.get_children()), 4)
        self.assertEqual(self.app.session.query(KorektaStawki).count(), 0)
        first = window.preview_tree.item(window.preview_tree.get_children()[0], 'values')
        self.assertIn('Jan Przykładowy', first[0])
        self.assertEqual(first[1], f'{self.year}-06')
        self.assertEqual(first[-3:], ('35.00', '40.00', '+5.00'))
        self.assertEqual(first[2], 'Standard')
        with patch('tkinter.messagebox.showinfo'):
            window.confirm()
        self.assertEqual(self.app.session.query(KorektaStawki).count(), 4)

    def test_fee_preview_stale_input_cannot_commit(self):
        window = self.open('open_change_fees')
        window.zapisz_zmiany()
        entry = next(iter(window.entry_dict.values()))
        entry.delete(0, 'end')
        entry.insert(0, '60')
        with patch('tkinter.messagebox.showerror') as error:
            window.confirm()
            self.assertTrue(error.called)
        self.assertEqual(self.app.session.query(KorektaStawki).count(), 0)
        self.assertEqual(window.btn_confirm.cget('state'), 'disabled')

    def test_legacy_fee_preview_periods_and_no_current_status_guess(self):
        session = self.app.session
        session.query(StatusNaliczenia).delete()
        session.query(NaliczenieCzlonka).delete()
        session.query(NaliczenieMiesiaca).delete()
        session.add_all(HistoriaNaliczen(rok=self.year, miesiac=m) for m in (6, 7, 8, 9))
        session.commit()
        window = self.open('open_change_fees')
        self.assertEqual(len(window.original_status_entries), 1)
        self.assertTrue(all(v.get() == 'Wybierz status' for v in window.original_status_entries.values()))
        with patch('tkinter.messagebox.showerror'):
            window.zapisz_zmiany()
        self.assertEqual(window.tabs.get(), 'Dawna historia')
        for value in window.original_status_entries.values():
            value.set('Standard')
        window.zapisz_zmiany()
        self.assertEqual(len(window.preview_tree.get_children()), 4)
        self.assertEqual({window.preview_tree.item(k, 'values')[1] for k in window.preview_tree.get_children()},
            {f'{self.year}-{m:02}' for m in (6, 7, 8, 9)})
        self.assertEqual(session.query(NaliczenieCzlonka).count(), 0)

    def test_member_list_opens_combined_ledger_and_filters(self):
        window = self.open('open_list_all')
        key = window.tree.get_children()[0]
        window.tree.selection_set(key)
        window.open_finances()
        self.app.update()
        card = next(w for w in window.winfo_children() if isinstance(w, ctk.CTkToplevel))
        kinds = {card.tree.item(k, 'values')[2] for k in card.tree.get_children()}
        self.assertEqual(kinds, {'Wpłata', 'Składka miesięczna'})
        card.kind.set('Należności')
        card.pokaz_wplaty()
        self.assertEqual(len(card.tree.get_children()), 4)
        card.kind.set('Wpłaty')
        card.pokaz_wplaty()
        self.assertEqual(len(card.tree.get_children()), 1)

    def test_all_payments_show_and_search_original_description(self):
        payment = self.app.session.query(Wplata).one()
        payment.tytul_oryginalny = 'Oryginalny tytuł\nDruga linia'
        self.app.session.commit()
        window = self.open('open_payment_list')
        window.dropdown_kryterium.set('Opis transakcji')
        window.entry_szukaj.insert(0, 'druga linia')
        window.zaladuj_dane()
        self.assertEqual(len(window.tree.get_children()), 1)
        window.tree.selection_set(window.tree.get_children()[0])
        window.show_details()
        self.assertIn('Oryginalny tytuł\nDruga linia', window.details.get('1.0', 'end'))

    def test_financial_windows_fit_at_scaling_with_accessible_controls(self):
        import time
        member = self.app.session.query(Czlonek).one()
        from frames.member_stats_frame import MemberStatsWindow
        try:
            for scale in (1.0, 1.25, 1.5):
                ctk.set_widget_scaling(scale)
                ctk.set_window_scaling(scale)
                for method in ('open_change_fees', 'import_excel', 'ledger'):
                    if method == 'ledger':
                        window = MemberStatsWindow(self.app, self.app.session, member)
                        controls = [window.kind, window.dropdown_okres, window.btn_filtruj]
                        tree = window.tree
                    else:
                        getattr(self.app, method)()
                        window = self.windows()[0]
                        controls = ([window.btn_load, window.btn_preview, window.btn_confirm, window.entry_date]
                            if method == 'open_change_fees' else [window.btn_select, window.currency, window.btn_pending, window.btn_commit])
                        tree = window.preview_tree if method == 'open_change_fees' else window.tree
                        if method == 'open_change_fees':
                            window.zapisz_zmiany()
                    fit_window(window, self.app)
                    deadline = time.monotonic() + .3
                    while time.monotonic() < deadline:
                        self.app.update()
                        time.sleep(.01)
                    for control in controls:
                        self.assertTrue(control.winfo_viewable(), (scale, method, 'hidden'))
                        self.assertGreaterEqual(control.winfo_rootx(), window.winfo_rootx(), (scale, method, 'left'))
                        self.assertLessEqual(control.winfo_rootx() + control.winfo_width(), window.winfo_rootx() + window.winfo_width(), (scale, method, 'right'))
                        self.assertLessEqual(control.winfo_rooty() + control.winfo_height(), window.winfo_rooty() + window.winfo_height(), (scale, method, 'bottom'))
                    self.assertGreater(tree.winfo_height(), 70, (scale, method, 'table too short'))
                    window.destroy()
                    self.app.update()
        finally:
            ctk.set_widget_scaling(1.0)
            ctk.set_window_scaling(1.0)

    def test_500_import_rows_reviewed_and_posted_as_one_batch(self):
        window = self.imported([['2026-06-15', '1', f'A!12 składka testowa {index}', 'PLN', 'Nadawca Testowy']
            for index in range(500)])
        self.assertEqual(len(window.included), 500)
        window.commit()
        self.app.update()
        self.assertEqual(len(window.confirmation.tree.get_children()), 500)
        window.confirmation.btn_save.invoke()
        self.app.update()
        self.assertEqual(self.app.session.query(Wplata).count(), 501)
        self.assertEqual(self.app.session.query(Czlonek).one().bilans_otwarcia, 465)
