$ErrorActionPreference = "Stop"
$workspace = Split-Path -Parent $PSScriptRoot
$python = Join-Path $workspace ".venv\Scripts\python.exe"
$waitress = Join-Path $workspace ".venv\Scripts\waitress-serve.exe"

if (-not (Test-Path $python)) {
    throw "The local Python environment is missing. Follow the setup steps in README.md."
}

$env:USE_SQLITE = "1"
Push-Location $workspace
try {
    New-Item -ItemType Directory -Force "data" | Out-Null
    & $python manage.py migrate
    if ($LASTEXITCODE -ne 0) {
        throw "Preview database setup failed."
    }
    & $python manage.py collectstatic --noinput --verbosity 0
    if ($LASTEXITCODE -ne 0) {
        throw "Preview asset preparation failed."
    }
    Write-Host "Preview mode is available at http://127.0.0.1:8000"
    Write-Host "This preview uses a local SQLite file; the normal application configuration uses PostgreSQL."
    & $waitress --listen=127.0.0.1:8000 config.wsgi:application
} finally {
    Pop-Location
}
