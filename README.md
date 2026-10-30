# Monity — rozliczenia małej firmy

Lokalna aplikacja desktopowa do ewidencji klientów, cyklicznych opłat, wpłat i przypomnień e-mail. Projekt portfolio w Pythonie: CustomTkinter, SQLAlchemy i SQLite. Punkt wyjścia dla małej firmy rozliczającej abonamenty.

## Funkcje

- Kartoteki klientów, wyszukiwanie po nazwie i archiwizacja z zachowaniem historii.
- Dwa alternatywne pakiety: Standard i Premium.
- Miesięczne naliczenia, datowane zmiany pakietu, korekty stawek i cofanie naliczeń.
- Wpłaty ręczne i import XLSX z podglądem, walidacją i kontrolą duplikatów.
- Karta finansowa klienta, zestawienia i eksport raportów do Excela.
- Przypomnienia Gmail z podglądem, potwierdzeniem i trwałą kolejką wysyłki.
- Kopie SQLite, migracje i przekazanie danych innemu operatorowi.

## Uruchomienie

Wymagany Python 3.12 lub nowszy i Tkinter. Przykład dla Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
New-Item -ItemType Directory -Force "$HOME\MonityDemo"
$env:MONITY_DATA_DIR = "$HOME\MonityDemo"
.\.venv\Scripts\python.exe main.py
```

Nowy katalog danych oznacza nową bazę. Dla istniejącej instalacji wskaż katalog właściwej bazy. Ścieżka musi być bezwzględna. Można ją też zapisać w lokalnym `katalog_danych.txt` obok kodu. Bez konfiguracji używany jest katalog projektu. Linux/macOS wymagają osobnej weryfikacji GUI i instalacji Tkintera.

Podgląd z fikcyjnymi danymi i symulowaną pocztą:

```text
python tools/gui_demo.py
```

## Zasady rozliczeń

Dodaj klienta, wybierz pakiet i miesiąc rozpoczęcia umowy. Stawki początkowe Standard/Premium to przykładowo 35/65 PLN; przed pracą ustaw własne. Miesiące rozpoczęcia i zakończenia umowy są naliczane w całości.

Obecny model ma stały okres roczny czerwiec–maj i zatwierdzanie stawek z mocą od czerwca. Korekty zachowują pierwotne naliczenia. Dowolny kalendarz abonamentowy wymaga dostosowania logiki. Opcjonalna opłata startowa wynosi trzy bazowe stawki Standard.

Dodatnie saldo oznacza nadpłatę, ujemne zaległość. Edycja salda początkowego okresu zapisuje informację o już uwzględnionej kwocie i nie zmienia salda bieżącego. Widok „najstarsze najpierw” nie zapisuje przydziałów wpłat do należności.

## Import

Mapowanie kolumn wyciągu ustaw w aplikacji. Import wymaga dodatniej kwoty PLN i prawidłowej daty. `A!12` w tytule przelewu jest technicznym identyfikatorem klienta; niejednoznaczne pozycje wymagają ręcznego wyboru. Format eksportu danego banku należy sprawdzić na zanonimizowanej próbce.

Import kartotek XLSX:

```text
python import_czlonkow.py klienci.xlsx
python import_czlonkow.py klienci.xlsx --zapisz
```

Pierwsze polecenie tylko sprawdza plik. Zapis wykonuj przy zamkniętej aplikacji; poprzedza go kopia bazy. Nagłówki: `Imie`, `Nazwisko`, `Numer Konta`, `Mail`, `Saldo`, `Data dołączenia`, `Status`. Status: `Standard` lub `Premium`. Saldo jest wymagane. Konwencja tego importu: **plus = zaległość, minus = nadpłata**. Rachunki zapisuj jako tekst. Import dodaje nowe kartoteki, nie aktualizuje istniejących.

## Poczta

Skonfiguruj nadawcę w oknie Gmail. SMTP używa hasła aplikacji, przechowywanego poza repozytorium w katalogu danych. Przed wysyłką ustaw własnego odbiorcę płatności i rachunek w `mail_content.py`: wersja demonstracyjna zawiera oznaczenia do uzupełnienia.

Każdą wysyłkę poprzedza podgląd i potwierdzenie. Niepewny wynik wymaga ręcznego sprawdzenia przed ponowieniem. `MONITY_MAIL_DRY_RUN=1` symuluje pocztę bez połączenia sieciowego. Integracja OAuth nie jest zaimplementowana.

## Kopie i dane

Przy zamknięciu powstaje kopia SQLite; przechowywanych jest 30 najnowszych kopii automatycznych. Ustawienia udostępniają też kopie ręczne i dodatkowy folder kopii.

```text
python backup.py kopia.db
python backup.py odtworzona.db --source kopia.db
```

Narzędzie korzysta z mechanizmu backup SQLite i nie nadpisuje istniejącego celu. Odtworzenie sprawdzaj w osobnym katalogu. Nie synchronizuj otwartej bazy między komputerami. Aplikacja nie szyfruje bazy ani kopii. Dane klientów, konfiguracja, eksporty i lokalne instrukcje są wykluczone z Git.

## Architektura

`main.py` uruchamia GUI, `frames/` zawiera widoki, a `ui.py` wspólne elementy interfejsu. `models.py` definiuje schemat i migracje. Reguły rozliczeń są w modułach usług, m.in. `annual_fees.py`, `finance_service.py`, `import_service.py`, `report_service.py` i `mail_service.py`. `paths.py` odpowiada za lokalizację danych, a `backup.py` za kopie. Historyczne nazwy części modułów i tabel pozostają dla zgodności schematu.

## Testy

Testy korzystają z danych syntetycznych i nie wysyłają rzeczywistej poczty:

```text
python -m unittest discover -s tests -p "test_*.py"
python -m unittest discover -s tests -p gui_smoke.py
python -m unittest discover -s tests -p gui_system.py
python -m unittest discover -s tests -p gui_financial_review.py
```

Zestawy GUI wymagają działającego środowiska graficznego i Tkintera.

## Ograniczenia

Projekt nie zastępuje systemu księgowego ani fakturowania. Część starszych kwot pozostaje w kolumnach FLOAT; nowe naliczenia i korekty są zapisywane w groszach. Brakuje trwałych przydziałów wpłat i automatycznego zamknięcia okresu. Raporty oznaczają braki historii zamiast odtwarzać ją z aktualnego salda. Rzeczywiste doręczenie Gmail i działanie na innych systemach wymagają osobnej weryfikacji.
