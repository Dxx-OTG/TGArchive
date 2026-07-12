$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$envPath = Join-Path $root ".env"
$envExamplePath = Join-Path $root ".env.example"
$pgRoot = "C:\Program Files\PostgreSQL\17"
$pgBin = Join-Path $pgRoot "bin"
$serviceName = "postgresql-x64-17"

Write-Output "=== Database setup for the OSINT Telegram bot + collector ==="

if (-not (Test-Path $envPath)) {
    Write-Output "WARNING: .env file not found at $envPath"
    if (Test-Path $envExamplePath) {
        Write-Output "Creating .env from template - this only writes DATABASE_URL_*; fill in the rest (README -> '.env configuration')."
        Copy-Item -Path $envExamplePath -Destination $envPath
    } else {
        Write-Output "ERROR: .env.example not found either - your copy looks incomplete, re-clone the project."
        exit 1
    }
}

$envLines = Get-Content $envPath
$existingCollectorUrl = ($envLines | Where-Object { $_ -match '^DATABASE_URL_COLLECTOR=' }) -replace '^DATABASE_URL_COLLECTOR=', ''

function New-AlnumPassword($length) {
    $chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789'
    $bytes = New-Object byte[] $length
    $rng = New-Object System.Security.Cryptography.RNGCryptoServiceProvider
    $rng.GetBytes($bytes)
    -join ($bytes | ForEach-Object { $chars[$_ % $chars.Length] })
}

function Wait-ServiceRunning($name, $maxTries = 20) {
    $tries = 0
    do {
        Start-Sleep -Seconds 3
        $svc = Get-Service -Name $name -ErrorAction SilentlyContinue
        $tries++
    } while (($null -eq $svc -or $svc.Status -ne "Running") -and $tries -lt $maxTries)
    return ($null -ne $svc -and $svc.Status -eq "Running")
}

function Wait-ServiceGone($name, $maxTries = 40) {
    $tries = 0
    do {
        Start-Sleep -Seconds 3
        $svc = Get-Service -Name $name -ErrorAction SilentlyContinue
        $tries++
    } while (($null -ne $svc) -and $tries -lt $maxTries)
    return ($null -eq $svc)
}

function Test-IsAdmin {
    return ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltinRole]::Administrator)
}

function Write-EnvUrls($botPw, $collectorPw) {
    $lines = Get-Content $envPath
    $lines = $lines `
        -replace '^DATABASE_URL_BOT=.*$', "DATABASE_URL_BOT=postgresql://app_bot:$botPw@localhost:5432/scraper" `
        -replace '^DATABASE_URL_COLLECTOR=.*$', "DATABASE_URL_COLLECTOR=postgresql://app_collector:$collectorPw@localhost:5432/scraper"
    $lines | Out-File -FilePath $envPath -Encoding utf8
}

function Apply-AppBotGrants($psqlArgs) {
    # $psqlArgs points psql at the 'scraper' db with enough rights (postgres superuser or collector URL).
    $sql = @"
GRANT CONNECT ON DATABASE scraper TO app_bot;
GRANT USAGE ON SCHEMA public TO app_bot;
ALTER DEFAULT PRIVILEGES FOR ROLE app_collector IN SCHEMA public GRANT SELECT, INSERT, UPDATE ON TABLES TO app_bot;
ALTER DEFAULT PRIVILEGES FOR ROLE app_collector IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO app_bot;
"@
    $path = Join-Path $env:TEMP "scraper_grants_$([guid]::NewGuid().ToString('N')).sql"
    $sql | Out-File -FilePath $path -Encoding ascii
    # Out-Null: keep psql's stdout out of this function's return value.
    & "$pgBin\psql.exe" @psqlArgs -f $path | Out-Null
    $code = $LASTEXITCODE
    Remove-Item $path -Force
    return $code
}

function Run-Migrations($collectorUrl) {
    # Whenever the database is (re)created, drop the CSV import cache (output\.import_manifest.json):
    # it maps CSV mtimes to "already imported", so a fresh DB plus existing/transferred CSVs would
    # otherwise stay UNIMPORTED. Clearing it makes the bot re-import every CSV on next start
    # (idempotent). The DB holds only CSV-derived data, so it is fully rebuilt from the output\ CSVs
    # on the next bot/CLI start - there is no separate DB backup to restore.
    $manifest = Join-Path $root "output\.import_manifest.json"
    if (Test-Path $manifest) {
        Write-Output "Clearing the CSV import cache (output\.import_manifest.json) so CSVs re-import..."
        Remove-Item $manifest -Force -ErrorAction SilentlyContinue
    }

    Write-Output "Creating an empty schema from db\migrations\..."
    $migrationsDir = Join-Path $root "db\migrations"
    if (-not (Test-Path $migrationsDir)) {
        Write-Output "ERROR: db\migrations folder not found at $migrationsDir."
        Write-Output "Your copy of the project looks incomplete - re-clone or re-download it."
        exit 1
    }
    $migrationFiles = Get-ChildItem $migrationsDir -Filter "*.sql" | Sort-Object Name
    if ($migrationFiles.Count -eq 0) {
        Write-Output "ERROR: no .sql files found in db\migrations."
        Write-Output "Your copy of the project looks incomplete - re-clone or re-download it."
        exit 1
    }
    foreach ($migration in $migrationFiles) {
        Write-Output "  - $($migration.Name)"
        & "$pgBin\psql.exe" $collectorUrl -v ON_ERROR_STOP=1 -f $migration.FullName
        if ($LASTEXITCODE -ne 0) {
            Write-Output "ERROR while running $($migration.Name). Check the output above."
            exit 1
        }
    }
}

function Find-DataDir {
    $candidate = Join-Path $pgRoot "data"
    if (Test-Path (Join-Path $candidate "pg_hba.conf")) { return $candidate }
    return $null
}

function Try-RecoverViaTrust {
    # Lost-password recovery: temporarily set local auth to 'trust', reset the app roles and
    # recreate the DB as the postgres superuser, then always restore the original auth config.
    # Uses Write-Host throughout, not Write-Output (avoids polluting the return value).
    if (-not (Test-IsAdmin)) {
        Write-Host "Cannot attempt in-place recovery without administrator rights."
        return $false
    }
    $dataDir = Find-DataDir
    if (-not $dataDir) {
        Write-Host "Cannot find the PostgreSQL data directory ($pgRoot\data) - skipping in-place recovery."
        return $false
    }

    $hba = Join-Path $dataDir "pg_hba.conf"
    $hbaBak = Join-Path $dataDir "pg_hba.conf.tgarchive.bak"
    $botPw = New-AlnumPassword 24
    $collectorPw = New-AlnumPassword 24

    Copy-Item $hba $hbaBak -Force
    try {
        Write-Host "Temporarily allowing local trust auth to regain access..."
        "host all all 127.0.0.1/32 trust`r`nhost all all ::1/128 trust`r`n" | Out-File -FilePath $hba -Encoding ascii

        Restart-Service $serviceName -Force
        if (-not (Wait-ServiceRunning $serviceName)) {
            Write-Host "ERROR: PostgreSQL did not come back up after the auth change."
            return $false
        }

        $env:PGPASSWORD = ""
        $recoverSql = @"
DROP DATABASE IF EXISTS scraper WITH (FORCE);
CREATE ROLE app_collector WITH LOGIN CREATEDB PASSWORD '$collectorPw';
ALTER ROLE app_collector WITH LOGIN CREATEDB PASSWORD '$collectorPw';
CREATE ROLE app_bot WITH LOGIN PASSWORD '$botPw';
ALTER ROLE app_bot WITH LOGIN PASSWORD '$botPw';
CREATE DATABASE scraper OWNER app_collector;
"@
        $recoverPath = Join-Path $env:TEMP "scraper_recover_$([guid]::NewGuid().ToString('N')).sql"
        $recoverSql | Out-File -FilePath $recoverPath -Encoding ascii
        # ON_ERROR_STOP off: CREATE ROLE may fail if the role exists; the ALTER right after fixes it.
        & "$pgBin\psql.exe" -U postgres -h 127.0.0.1 -f $recoverPath | Out-Null
        Remove-Item $recoverPath -Force

        Apply-AppBotGrants @("-U", "postgres", "-h", "127.0.0.1", "-d", "scraper") | Out-Null
    }
    finally {
        Write-Host "Restoring the original authentication config..."
        Copy-Item $hbaBak $hba -Force
        Remove-Item $hbaBak -Force -ErrorAction SilentlyContinue
        Restart-Service $serviceName -Force -ErrorAction SilentlyContinue
        Wait-ServiceRunning $serviceName | Out-Null
        $env:PGPASSWORD = ""
    }

    $newCollectorUrl = "postgresql://app_collector:$collectorPw@localhost:5432/scraper"
    & "$pgBin\psql.exe" $newCollectorUrl -c "SELECT 1" >$null 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "In-place recovery did not result in working credentials."
        return $false
    }

    Run-Migrations $newCollectorUrl
    Write-EnvUrls $botPw $collectorPw
    return $true
}

# ---------------------------------------------------------------------------------------------
# Decide which path applies, from least to most invasive.
# ---------------------------------------------------------------------------------------------

$service = Get-Service -Name $serviceName -ErrorAction SilentlyContinue

if (-not $service) {
    # A different major version would use a different service name - check before assuming "not installed".
    $otherPgService = Get-Service -Name "postgresql*" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($otherPgService) {
        Write-Output "PostgreSQL: found a different installation ('$($otherPgService.Name)') - this project"
        Write-Output "manages PostgreSQL 17 specifically (expected service 'postgresql-x64-17')."
        Write-Output "ERROR: installing PostgreSQL 17 alongside it would likely conflict on port 5432."
        Write-Output "Uninstall the other PostgreSQL version manually first (Settings > Apps > search"
        Write-Output "'PostgreSQL'), then rerun Setup Database."
        exit 1
    }
}

if ($service) {
    Write-Output "PostgreSQL 17: installed (service '$serviceName', status: $($service.Status))."
} else {
    Write-Output "PostgreSQL 17: not installed."
}

if ($service -and $service.Status -ne "Running") {
    Write-Output "Starting PostgreSQL service..."
    Start-Service -Name $serviceName -ErrorAction SilentlyContinue
    Wait-ServiceRunning $serviceName | Out-Null
    $service = Get-Service -Name $serviceName -ErrorAction SilentlyContinue
}

$canReset = $false
if ($service -and $service.Status -eq "Running" -and $existingCollectorUrl) {
    & "$pgBin\psql.exe" $existingCollectorUrl -c "SELECT 1" >$null 2>$null
    $canReset = ($LASTEXITCODE -eq 0)
}

# --- Path 1: PostgreSQL up and .env credentials still work -> reset DB content in place. ------
if ($canReset) {
    Write-Output "Working PostgreSQL setup found. This wipes the current content of the 'scraper' database"
    Write-Output "and recreates it empty - keeping the same login. PostgreSQL itself is not touched. Your"
    Write-Output "scraped data lives in the output\ CSVs and is re-imported into the fresh database on the"
    Write-Output "next bot/CLI start."
    Write-Output ""

    $confirm = Read-Host "Proceed and reset 'scraper'? (y/n)"
    if ($confirm -notmatch '^[yY]') {
        Write-Output "Cancelled."
        exit 0
    }

    Write-Output "Resetting 'scraper'..."
    & "$pgBin\psql.exe" $existingCollectorUrl -v ON_ERROR_STOP=1 -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
    if ($LASTEXITCODE -ne 0) {
        Write-Output "ERROR while resetting the database. Check the output above."
        exit 1
    }

    if ((Apply-AppBotGrants @($existingCollectorUrl)) -ne 0) {
        Write-Output "ERROR while restoring app_bot's permissions on the fresh schema."
        exit 1
    }

    Run-Migrations $existingCollectorUrl

    Write-Output ""
    Write-Output "=== Reset complete ==="
    Write-Output "Database 'scraper' is now empty and ready (same login as before, nothing in .env changed)."
    Write-Output "Your output\ CSVs are re-imported into it on the next bot/CLI start."
    Write-Output "You can now start the bot or the CLI from TGArchive.bat."
    exit 0
}

# --- Path 2: PostgreSQL installed but no working credentials -> recover in place (no reinstall).
if ($service) {
    Write-Output "PostgreSQL is installed but the .env credentials don't work. Trying in-place recovery"
    Write-Output "(no reinstall). WARNING: this resets the login for 'scraper' and empties it; its content is"
    Write-Output "rebuilt from the output\ CSVs on the next bot/CLI start. Close start_bot/start_menu first if open."
    Write-Output ""

    $confirm = Read-Host "Proceed with in-place recovery? (y/n)"
    if ($confirm -notmatch '^[yY]') {
        Write-Output "Cancelled."
        exit 0
    }

    if (Try-RecoverViaTrust) {
        Write-Output ""
        Write-Output "=== Recovery complete ==="
        Write-Output "Database 'scraper' is ready again, empty, with fresh credentials saved to .env."
        Write-Output "Your output\ CSVs are re-imported on the next bot/CLI start."
        Write-Output "You can now start the bot or the CLI from TGArchive.bat."
        exit 0
    }

    Write-Output ""
    Write-Output "In-place recovery failed. Falling back to a clean uninstall/reinstall of PostgreSQL."
    Write-Output ""

    if (-not (Test-IsAdmin)) {
        Write-Output "ERROR: administrator privileges are required to uninstall/reinstall PostgreSQL."
        Write-Output "Close this window and rerun Setup Database from TGArchive.bat (it elevates)."
        exit 1
    }

    $confirm = Read-Host "Proceed with a clean uninstall and reinstall? (y/n)"
    if ($confirm -notmatch '^[yY]') {
        Write-Output "Cancelled."
        exit 0
    }

    if ($service.Status -eq "Running") {
        Write-Output "Stopping service $serviceName..."
        Stop-Service -Name $serviceName -Force -ErrorAction SilentlyContinue
    }

    $uninstallExe = Join-Path $pgRoot "uninstall-postgresql.exe"
    if (-not (Test-Path $uninstallExe)) {
        Write-Output "ERROR: uninstaller not found at $uninstallExe (install not in the standard path?)."
        Write-Output "Uninstall PostgreSQL manually from Settings > Apps, delete $pgRoot, then rerun."
        exit 1
    }

    Write-Output "The PostgreSQL uninstaller window opens: follow it (Next/Uninstall/Finish)."
    Write-Output "The script waits until you close it."
    Start-Process -FilePath $uninstallExe -Wait

    if (-not (Wait-ServiceGone $serviceName)) {
        Write-Output "ERROR: the $serviceName service is still present after uninstall."
        Write-Output "Check manually (Settings > Apps, and Windows Services), then rerun."
        exit 1
    }

    $wingetListOutput = & winget list --id PostgreSQL.PostgreSQL.17 -e 2>&1 | Out-String
    if ($LASTEXITCODE -eq 0) {
        Write-Output "ERROR: winget still sees PostgreSQL.PostgreSQL.17 as installed after uninstall:"
        Write-Output $wingetListOutput
        Write-Output "Uninstall it manually from Settings > Apps (search 'PostgreSQL'), then rerun."
        exit 1
    }

    Write-Output "Cleaning up leftover files in $pgRoot..."
    $folderCleaned = $false
    for ($i = 0; $i -lt 5; $i++) {
        try {
            if (Test-Path $pgRoot) {
                Remove-Item -Path $pgRoot -Recurse -Force -ErrorAction Stop
            }
            $folderCleaned = $true
            break
        } catch {
            Start-Sleep -Seconds 3
        }
    }
    if (-not $folderCleaned -and (Test-Path $pgRoot)) {
        Write-Output "ERROR: cannot delete $pgRoot (files still in use by another program?)."
        Write-Output "Close any program that might use it (pgAdmin, other terminals) and rerun."
        exit 1
    }

    Write-Output "Uninstall and cleanup complete."
    Write-Output ""
}

# --- Path 3: PostgreSQL not installed -> fresh install. ---------------------------------------
Write-Output "Installing PostgreSQL 17 (this may take a few minutes)..."

$wingetCheck = Get-Command winget -ErrorAction SilentlyContinue
if (-not $wingetCheck) {
    Write-Output "ERROR: 'winget' is not available on this PC."
    Write-Output "Install 'App Installer' from the Microsoft Store, then rerun this script."
    exit 1
}

$superPw = New-AlnumPassword 24

winget install --id PostgreSQL.PostgreSQL.17 -e --silent --accept-package-agreements --accept-source-agreements --override "--mode unattended --unattendedmodeui minimal --superpassword $superPw --serverport 5432"

Write-Output "Waiting for the PostgreSQL service to be running..."
if (-not (Wait-ServiceRunning $serviceName)) {
    Write-Output "ERROR: the PostgreSQL service is not running after install."
    exit 1
}

Write-Output "PostgreSQL installed and running."
Write-Output "Creating roles and database..."

$collectorPw = New-AlnumPassword 24
$botPw = New-AlnumPassword 24

# app_collector gets CREATEDB so future resets/recoveries can drop/recreate on their own.
$sqlSetup = @"
CREATE ROLE app_collector WITH LOGIN CREATEDB PASSWORD '$collectorPw';
CREATE ROLE app_bot WITH LOGIN PASSWORD '$botPw';
CREATE DATABASE scraper OWNER app_collector;
"@
$sqlSetupPath = Join-Path $env:TEMP "scraper_setup_$([guid]::NewGuid().ToString('N')).sql"
$sqlSetup | Out-File -FilePath $sqlSetupPath -Encoding ascii

$env:PGPASSWORD = $superPw
& "$pgBin\psql.exe" -U postgres -h localhost -f $sqlSetupPath
$setupExitCode = $LASTEXITCODE
Remove-Item $sqlSetupPath -Force

if ($setupExitCode -ne 0) {
    Write-Output "ERROR while creating roles/database."
    exit 1
}

Write-Output "Configuring minimal permissions for app_bot..."
if ((Apply-AppBotGrants @("-U", "postgres", "-h", "localhost", "-d", "scraper")) -ne 0) {
    Write-Output "ERROR while configuring permissions."
    exit 1
}

$newCollectorUrl = "postgresql://app_collector:$collectorPw@localhost:5432/scraper"
Run-Migrations $newCollectorUrl
Write-EnvUrls $botPw $collectorPw

Write-Output ""
Write-Output "=== Setup complete ==="
Write-Output "Database 'scraper' created with an empty schema."
Write-Output "Your output\ CSVs (if any) are imported into it on the next bot/CLI start."
Write-Output "You can now start the bot or the CLI from TGArchive.bat."
