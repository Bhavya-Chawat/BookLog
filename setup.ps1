# BookLog one-time setup for Windows. Run via setup.bat (safe to re-run).
#   1. Python venv + pip packages, npm packages
#   2. PostgreSQL: restore the database snapshot, create the booklog_app role
#   3. Neo4j: (installed by you) rebuild the graph from PostgreSQL
#   4. Check MongoDB, Firebase key, OpenAI key and say what is still missing
$ErrorActionPreference = 'Continue'
$Root    = Split-Path -Parent $MyInvocation.MyCommand.Path
$Backend = Join-Path $Root 'backend'
$EnvFile = Join-Path $Backend '.env'
$Venv    = Join-Path $Backend 'venv\Scripts\python.exe'
$Todo    = New-Object System.Collections.ArrayList

function Step($m) { Write-Host "`n== $m" -ForegroundColor Cyan }
function Ok($m)   { Write-Host "   OK   $m" -ForegroundColor Green }
function Warn($m) { Write-Host "   TODO $m" -ForegroundColor Yellow; [void]$Todo.Add($m) }
function Fail($m) { Write-Host "   FAIL $m" -ForegroundColor Red }

function Get-EnvValue($name) {
    $line = Get-Content $EnvFile | ForEach-Object { $_.TrimStart([char]0xFEFF) } | Where-Object { $_ -match "^\s*$name=" } | Select-Object -First 1
    if ($line) { return ($line -replace "^\s*$name=", '').Trim() } else { return '' }
}
function Set-EnvValue($name, $value) {
    $lines = @(Get-Content $EnvFile)
    if ($lines | Where-Object { $_ -match "^\s*$name=" }) {
        $lines = $lines | ForEach-Object { if ($_ -match "^\s*$name=") { "$name=$value" } else { $_ } }
    } else { $lines += "$name=$value" }
    [IO.File]::WriteAllLines($EnvFile, [string[]]$lines, (New-Object Text.UTF8Encoding($false)))
}

# ---------------------------------------------------------------- env file
Step 'backend/.env'
if (-not (Test-Path $EnvFile)) {
    Copy-Item (Join-Path $Backend '.env.example') $EnvFile
    Warn 'backend/.env was missing; created from .env.example. Fill in NEO4J_PASSWORD / MONGO_URL / OPENAI_API_KEY and run setup again.'
} else { Ok 'exists' }

# ---------------------------------------------------------------- python + node
Step 'Python virtual environment'
if (-not (Test-Path $Venv)) { python -m venv (Join-Path $Backend 'venv') }
if (Test-Path $Venv) {
    & $Venv -m pip install -q -r (Join-Path $Backend 'requirements.txt')
    if ($LASTEXITCODE -eq 0) { Ok 'pip packages installed' } else { Fail 'pip install failed' }
} else { Fail 'could not create venv (is Python 3.10+ installed and on PATH?)' }

Step 'Frontend packages'
Push-Location (Join-Path $Root 'frontend')
npm install --no-audit --no-fund
if ($LASTEXITCODE -eq 0) { Ok 'npm packages installed' } else { Fail 'npm install failed' }
Pop-Location

# ---------------------------------------------------------------- postgres
Step 'PostgreSQL'
$pgBin = Get-ChildItem 'C:\Program Files\PostgreSQL\*\bin\psql.exe' -ErrorAction SilentlyContinue |
         Sort-Object FullName -Descending | Select-Object -First 1 | ForEach-Object { Split-Path $_.FullName }
if (-not $pgBin) { Fail 'PostgreSQL not found under C:\Program Files\PostgreSQL'; $pgBin = $null }
else {
    $psql = Join-Path $pgBin 'psql.exe'
    $env:PGCONNECT_TIMEOUT = '5'
    $pwd1 = Read-Host -Prompt '   Enter the password of the PostgreSQL "postgres" user (the one you chose when installing PostgreSQL)' -AsSecureString
    $env:PGPASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($pwd1))
    $q = { param($sql) & $psql -h localhost -U postgres -d postgres -tAqc $sql }
    if ((& $q 'SELECT 1') -ne '1') { Fail 'could not log in as postgres. Wrong password? Run setup again.'; $pgBin = $null }
}
if ($pgBin) {
    Ok "connected as postgres ($pgBin)"
    $exists = (& $q "SELECT 1 FROM pg_database WHERE datname='booklog'")
    if ($exists -eq '1') {
        Ok 'database "booklog" already exists, skipping restore'
    } else {
        $dump = Join-Path $Root 'database\booklog.dump'
        if (-not (Test-Path $dump)) {
            Write-Host '   unzipping database snapshot...'
            Expand-Archive -Path (Join-Path $Root 'database\booklog-database.zip') -DestinationPath (Join-Path $Root 'database') -Force
        }
        & (Join-Path $pgBin 'createdb.exe') -h localhost -U postgres booklog
        Write-Host '   restoring 23,862 books and everything else (about a minute)...'
        & (Join-Path $pgBin 'pg_restore.exe') -h localhost -U postgres --no-owner --no-privileges -d booklog $dump
        foreach ($m in '003_app_role.sql', '004_report_role.sql') {
            & $psql -h localhost -U postgres -d booklog -q -v ON_ERROR_STOP=1 -f (Join-Path $Backend "db\migrations\$m")
        }
        $n = & $psql -h localhost -U postgres -d booklog -tAc 'SELECT count(*) FROM book'
        if ($n -gt 0) { Ok "restored: $n books" } else { Fail 'restore produced no books' }
    }
    # the app role needs a password because PostgreSQL on Windows uses password auth
    $url = Get-EnvValue 'DATABASE_URL'
    if ($url -notmatch 'booklog_app:[^@]+@') {
        $appPw = -join ((48..57) + (97..122) | Get-Random -Count 24 | ForEach-Object { [char]$_ })
        & $psql -h localhost -U postgres -d postgres -qc "ALTER ROLE booklog_app WITH LOGIN PASSWORD '$appPw'"
        Set-EnvValue 'DATABASE_URL' "postgresql://booklog_app:$appPw@localhost:5432/booklog"
        Ok 'booklog_app password set and written to backend/.env'
    } else { Ok 'DATABASE_URL already has a password' }
    Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
}

# ---------------------------------------------------------------- neo4j (local install)
Step 'Neo4j (local)'
$neoOk = $false
if (-not (Test-NetConnection localhost -Port 7687 -WarningAction SilentlyContinue).TcpTestSucceeded) {
    Warn 'Neo4j is not running on localhost:7687. Install Neo4j (Desktop or Community zip), create a DBMS with the password from backend/.env NEO4J_PASSWORD, start it, then run setup again.'
} else {
    $neoOk = $true; Ok 'Neo4j is listening on bolt://localhost:7687'
}
if ($neoOk -and $pgBin -and (Test-Path $Venv)) {
    Write-Host '   rebuilding the Neo4j graph from PostgreSQL...'
    & $Venv (Join-Path $Backend 'db\sync_neo4j.py')
    if ($LASTEXITCODE -eq 0) { Ok 'graph rebuilt' } else { Fail 'sync_neo4j.py failed (wrong NEO4J_PASSWORD in backend/.env?)' }
}

# ---------------------------------------------------------------- mongo, firebase, openai
Step 'MongoDB'
$mongo = Get-EnvValue 'MONGO_URL'
if ($mongo -match '^mongodb\+srv://') {
    if ($mongo -match '<|USER:PASSWORD') { Warn 'MONGO_URL still contains a placeholder.' } else { Ok 'using Atlas (make sure Atlas > Network Access allows your current IP)' }
} elseif ($mongo -match 'localhost|127\.0\.0\.1') {
    Warn 'MONGO_URL points at the local MongoDB on this PC. To use Atlas, paste your mongodb+srv:// URL into backend/.env.'
} else { Warn 'MONGO_URL is empty in backend/.env.' }

Step 'Firebase service account (Google sign-in on the API side)'
if (Test-Path (Join-Path $Root 'booklog-firebase-key.json')) { Ok 'found' }
else { Warn 'Missing booklog-firebase-key.json in the project root (Firebase console > Project settings > Service accounts > Generate new private key; rename the download). Without it nobody can sign in; browsing the catalogue still works.' }

Step 'OpenAI key (chatbot)'
if (Get-EnvValue 'OPENAI_API_KEY') { Ok 'set' } else { Warn 'OPENAI_API_KEY is empty in backend/.env (only the chatbot needs it).' }

Write-Host "`n=================================================" -ForegroundColor Cyan
if ($Todo.Count -eq 0) { Write-Host 'All set. Double-click run.bat to start BookLog.' -ForegroundColor Green }
else {
    Write-Host 'Setup finished. Still to do:' -ForegroundColor Yellow
    $i = 1; foreach ($t in $Todo) { Write-Host "  $i. $t"; $i++ }
    Write-Host "`nThen run run.bat." -ForegroundColor Yellow
}
