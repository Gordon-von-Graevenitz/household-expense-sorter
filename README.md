# Household Split

A private, local-first Django application for importing two partners' monthly bank exports,
reviewing shared expenses, saving exclusion rules, and recording settlement payments.

## Included in the first version

- Separate CSV/XLSX upload panels for Partner A and Partner B
- Safe controls to replace a validated import or clear one imported file and its transactions
- Automatic recognition of common date, merchant, amount, category, and currency columns
- Support for negative-amount and positive-amount bank export formats
- Household-scoped “always exclude this merchant” rules
- Configurable 50/50, 60/40, or other percentage split
- Integer-cent settlement calculations with deterministic rounding
- Separate settlement calculations when imports use different currencies
- Payment date and optional payment note
- PostgreSQL as the normal database
- A temporary SQLite preview mode for trying the interface without installing PostgreSQL

Uploaded files are processed in memory. The original files are not retained by the application.

## Try it now without PostgreSQL

The repository already contains a local Python environment. From PowerShell:

```powershell
.\scripts\start-preview.ps1
```

Open <http://127.0.0.1:8000> and upload the two files in `samples/`. Preview data is stored in
the ignored `data/` directory and is never committed to Git.

## Normal PostgreSQL setup

PostgreSQL can run through Docker Compose or through a normal local PostgreSQL installation.
Docker is not currently installed on this computer, so the configuration is included but the
database container has not been started yet.

1. Copy `.env.example` to `.env` and replace the example password and Django secret.
2. Start PostgreSQL. With Docker installed, run:

   ```powershell
   docker compose up -d database
   ```

3. Start the application:

   ```powershell
   .\scripts\start.ps1
   ```

The application listens only on `127.0.0.1`, so it is not exposed to the home network or public
internet.

## Development

```powershell
$env:USE_SQLITE = "1"
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\python.exe manage.py check
```

PostgreSQL remains the default whenever `USE_SQLITE` is not explicitly set to `1`.

## Current import assumptions

The importer recognises common English and German column names. At minimum, the file needs a date,
description/merchant, and amount column. If a bank uses unusual headings, the application reports
the headings it found; a visual column-mapping step is a sensible next enhancement.

Exports containing `Booking Date`, `Partner Name`, `Payment Reference`, `Type`, and currency-bearing
amount headers such as `Amount (EUR)` are mapped explicitly. The stable partner name is used for
merchant exclusion rules, while the payment reference is retained as transaction detail.

When automatic expense-sign detection sees negative values, it treats negative values as expenses
and skips positive income. The upload panel lets the user override this for banks that export
expenses as positive values.
