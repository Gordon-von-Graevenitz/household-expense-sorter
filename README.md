# Household Split

A private, local-first Django application for importing two partners' monthly bank exports,
reviewing shared expenses, saving exclusion rules, and recording settlement payments.

## Included in the first version

- Separate CSV/XLSX upload panels for Partner A and Partner B
- Safe controls to replace a validated import or clear one imported file and its transactions
- Automatic recognition of common date, merchant, amount, category, and currency columns
- Support for negative-amount and positive-amount bank export formats
- Household-scoped “always exclude this merchant” rules
- A configurable split for each month, starting from the household default until you save a split
- Saved settlements keep their original split, expense totals, and payment history
- Integer-cent settlement calculations with deterministic rounding
- Separate settlement calculations when imports use different currencies
- Payment date and optional payment note
- PostgreSQL as the normal database
- A SQLite preview mode that stores data locally between runs

Uploaded files are processed in memory. The original files are not retained by the application.

## Try it now without PostgreSQL

The repository already contains a local Python environment. From PowerShell:

```powershell
.\scripts\start-preview.ps1
```

Open <http://127.0.0.1:8000> and upload the two files in `samples/`. Preview data is stored in
the ignored `data/` directory and is never committed to Git.

## Normal PostgreSQL setup

Docker is required only if you choose to run PostgreSQL through Docker Compose. You can also
use a local PostgreSQL installation. In either case, the Django app runs directly on your computer.

1. Copy `.env.example` to `.env` and replace the example password and Django secret.
2. Start your local PostgreSQL service and configure its connection in `.env`, or start the
   PostgreSQL container with:

   ```powershell
   docker compose up -d database
   ```

3. Start the application:

   ```powershell
   .\scripts\start.ps1
   ```

The application listens only on `127.0.0.1`, so it is not exposed to the home network or public
internet.

## Data storage and backups

| Database mode | Where data is stored | What can remove it |
| --- | --- | --- |
| SQLite preview | `data/test.sqlite3` in the project folder | Deleting the file or project folder. Git ignores the database, so a fresh checkout cannot recover it. |
| PostgreSQL through Compose | The named volume defined as `household_split_postgres` in `compose.yaml` | Running `docker compose down -v` or explicitly deleting the database volume. Plain `docker compose down` keeps the volume. |
| Local PostgreSQL | The database configured in `.env` | Dropping the database or deleting the PostgreSQL data directory. |

Both modes keep their data across normal restarts. SQLite and PostgreSQL have separate data,
so switching modes can make the app look empty. Switching back opens the original database
if it still exists.

To back up SQLite, stop the app and copy `data/test.sqlite3` outside the project folder.
For either PostgreSQL setup, use `pg_dump` to make a database backup and store it separately.

Clearing an import deletes its transactions. Replacing an import removes the old batch and
its transactions once the replacement succeeds. Keep your original bank exports if you
want to re-import them later.

## Database migrations

Both startup scripts run `manage.py migrate` before starting the app. Django checks which
migrations have already been applied to the selected database and runs any pending migrations
in dependency order. When none are pending, startup continues without applying any migrations.
SQLite preview and PostgreSQL track their migration history separately.

If you start Django directly, run the following command first with the same database settings
you use to start the app. Set `USE_SQLITE=1` in PowerShell with `$env:USE_SQLITE = "1"` for
the SQLite preview database.

```powershell
.\.venv\Scripts\python.exe manage.py migrate
```

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
