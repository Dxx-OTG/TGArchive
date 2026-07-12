$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$envPath = Join-Path $root ".env"
$venvPath = Join-Path $root ".venv"

Write-Output "=== Prepare folder for transfer / clean reinstall ==="
Write-Output "Clears DATABASE_URL_* in .env, removes __pycache__, .venv and local log\*.log files."
Write-Output "Untouched: PostgreSQL, .env secrets, .session, output\ CSVs, Blacklist.py."
Write-Output "The scraped data travels as the output\ CSVs and is re-imported into a fresh DB on the new PC."
Write-Output "Details: README -> 'Transfer to another PC'. Close the bot/scraping windows first if open."
Write-Output ""

$confirm = Read-Host "Proceed? (y/n)"
if ($confirm -notmatch '^[yY]') {
    Write-Output "Cancelled."
    exit 0
}

if (-not (Test-Path $envPath)) {
    Write-Output "ERROR: .env file not found at $envPath"
    exit 1
}

$envLines = Get-Content $envPath

Write-Output ""
Write-Output "Clearing DATABASE_URL_BOT/DATABASE_URL_COLLECTOR in .env..."
$newLines = $envLines `
    -replace '^DATABASE_URL_BOT=.*$', 'DATABASE_URL_BOT=' `
    -replace '^DATABASE_URL_COLLECTOR=.*$', 'DATABASE_URL_COLLECTOR='
$newLines | Out-File -FilePath $envPath -Encoding utf8

if (Test-Path $venvPath) {
    Write-Output "Removing .venv..."
    try {
        Remove-Item $venvPath -Recurse -Force -ErrorAction Stop
    } catch {
        Write-Output "Could not delete .venv (a bot/scraping window is still open and using it). Close those"
        Write-Output "windows and delete the .venv folder by hand, or just leave it - it's rebuilt when missing."
    }
}

Write-Output "Removing __pycache__ folders..."
Get-ChildItem $root -Directory -Recurse -Filter "__pycache__" -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -notmatch '\\\.venv\\' } |
    ForEach-Object { Remove-Item $_.FullName -Recurse -Force -ErrorAction SilentlyContinue }

Write-Output "Removing local log files (log\*.log)..."
Get-ChildItem (Join-Path $root "log") -Filter "*.log" -ErrorAction SilentlyContinue |
    ForEach-Object { Remove-Item $_.FullName -Force -ErrorAction SilentlyContinue }

# Per-install CSV import cache: mustn't travel, or the new PC thinks the CSVs are already imported
# and leaves them out. (Setup Database also clears it, but keep the transferred folder clean.)
$manifest = Join-Path $root "output\.import_manifest.json"
if (Test-Path $manifest) {
    Write-Output "Removing CSV import cache (output\.import_manifest.json)..."
    Remove-Item $manifest -Force -ErrorAction SilentlyContinue
}

Write-Output ""
Write-Output "=== Folder ready ==="
Write-Output "Copy it to the new PC and run TGArchive.bat (rebuilds .venv, sets up the DB, starts the bot)."
Write-Output "Setup Database creates an empty 'scraper' database; your output\ CSVs are imported into it"
Write-Output "on the first bot/CLI start, so no separate DB dump is needed."
