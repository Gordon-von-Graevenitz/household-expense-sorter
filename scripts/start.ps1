$ErrorActionPreference = "Stop"
$workspace = Split-Path -Parent $PSScriptRoot
$python = Join-Path $workspace ".venv\Scripts\python.exe"
$waitress = Join-Path $workspace ".venv\Scripts\waitress-serve.exe"

if (-not (Test-Path $python)) {
    throw "The local Python environment is missing. Follow the setup steps in README.md."
}

Push-Location $workspace
try {
    & $python manage.py migrate
    if ($LASTEXITCODE -ne 0) {
        throw "Database migration failed. Check that PostgreSQL is running and the .env settings are correct."
    }
    & $python manage.py collectstatic --noinput --verbosity 0
    if ($LASTEXITCODE -ne 0) {
        throw "Static asset preparation failed."
    }
    Write-Host "Household Split is available at http://127.0.0.1:8000"
    & $waitress --listen=127.0.0.1:8000 config.wsgi:application
} finally {
    Pop-Location
}
