# Monity — Small Business Payment Management

A local desktop application for managing customers, recurring charges, payments, and email reminders. Built as a Python portfolio project with CustomTkinter, SQLAlchemy, and SQLite, it provides a starting point for small businesses that manage subscriptions.

## Features

- Customer records, name search, and archiving with financial history preserved.
- Two alternative pricing plans: Standard and Premium.
- Monthly charges, effective-dated plan changes, rate adjustments, and charge reversals.
- Manual payments and XLSX imports with previews, validation, and duplicate checks.
- Customer account history, summaries, and Excel report exports.
- Gmail reminders with previews, confirmation, and a persistent sending queue.
- SQLite backups, schema migrations, and data handover tools.

## Getting Started

Requires Python 3.12 or later and Tkinter. Example for Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
New-Item -ItemType Directory -Force "$HOME\MonityDemo"
$env:MONITY_DATA_DIR = "$HOME\MonityDemo"
.\.venv\Scripts\python.exe main.py
```

A new data directory creates a new database. For an existing installation, point to the directory containing the correct database. The path must be absolute. Alternatively, save it in a local `katalog_danych.txt` file next to the source code. Without configuration, the application uses the project directory. Linux/macOS require separate GUI verification and a working Tkinter installation.

To preview the application with fictional data and simulated email:

```text
python tools/gui_demo.py
```

The application interface is currently in Polish.

## Billing Rules

Add a customer, select a plan, and choose the contract start month. The initial Standard/Premium rates are example values of PLN 35/65; configure your own rates before use. Both the start and end months are charged in full.

The current model uses a fixed June–May annual billing period, with approved rates taking effect from June. Adjustments preserve the original charges. A different subscription calendar requires changes to the billing logic. The optional setup fee equals three times the base Standard rate.

A positive balance indicates credit; a negative balance indicates an outstanding amount. Editing the opening balance records an amount already included in the account and does not change the current balance. The oldest-first settlement view does not persist payment allocations against individual charges.

## Imports

Configure bank statement column mappings in the application. Imports require a positive PLN amount and a valid date. A reference such as `A!12` in the transfer description is a technical customer identifier; ambiguous entries require manual selection. Each bank's export format should be verified using an anonymized sample.

To import customer records from XLSX:

```text
python import_czlonkow.py customers.xlsx
python import_czlonkow.py customers.xlsx --zapisz
```

The first command only validates the file. Close the application before saving; a database backup is created before the import. Required column headers retain their Polish names: `Imie`, `Nazwisko`, `Numer Konta`, `Mail`, `Saldo`, `Data dołączenia`, `Status`. The status must be `Standard` or `Premium`. A balance is required. This import uses **positive = outstanding amount, negative = credit**. Store bank account numbers as text. The import creates new records and does not update existing customers.

## Email

Configure the sender in the Gmail settings window. SMTP uses an app password stored outside the repository in the data directory. Before sending reminders, set your own payment recipient and bank account in `mail_content.py`; the demo contains placeholders.

Each send requires a preview and confirmation. Uncertain sending results require manual review before retrying. Set `MONITY_MAIL_DRY_RUN=1` to simulate email without network access. OAuth integration is not implemented.

## Backups and Data

A SQLite backup is created when the application closes; the 30 most recent automatic backups are retained. Settings also provide manual backups and an optional additional backup directory.

```text
python backup.py backup.db
python backup.py restored.db --source backup.db
```

The tool uses SQLite's backup mechanism and refuses to overwrite an existing destination. Test restoration in a separate directory. Do not synchronize an open database between computers. The application does not encrypt the database or its backups. Customer data, configuration, exports, and local development instructions are excluded from Git.

## Architecture

`main.py` starts the GUI, `frames/` contains views, and `ui.py` provides shared interface components. `models.py` defines the schema and migrations. Billing and workflow rules live in service modules, including `annual_fees.py`, `finance_service.py`, `import_service.py`, `report_service.py`, and `mail_service.py`. `paths.py` handles data locations, while `backup.py` manages backups. Some module and table names retain their historical naming for schema compatibility.

## Tests

Tests use synthetic data and do not send real email:

```text
python -m unittest discover -s tests -p "test_*.py"
python -m unittest discover -s tests -p gui_smoke.py
python -m unittest discover -s tests -p gui_system.py
python -m unittest discover -s tests -p gui_financial_review.py
```

GUI suites require a working graphical environment and Tkinter.

## Limitations

This project does not replace accounting or invoicing software. Some legacy monetary values remain in FLOAT columns; new charges and adjustments are stored as integer grosz amounts (1/100 PLN). Persistent payment allocations and automatic period closing are not implemented. Reports flag missing historical data rather than reconstructing it from current balances. Actual Gmail delivery and operation on other systems require separate verification.
