# BookLog setup for Windows. Run it through setup.bat. It is safe to run again.
#
#   1. Checks that Python, Node.js and PostgreSQL are installed
#   2. Creates backend/.env and asks for the Neo4j password, MongoDB URL and OpenAI key
#   3. Installs the Python and npm packages
#   4. PostgreSQL: if there is no "booklog" database yet, restores the catalogue
#      snapshot (books, authors, genres, publishers, mood tags; no users) and
#      creates the booklog_app / booklog_reports roles.
#      An existing "booklog" database is never changed, so its users and activity stay.
#   5. Neo4j: rebuilds the graph from PostgreSQL
#   6. Checks MongoDB, the Firebase key and the OpenAI key, and lists what is still missing
#
# Options (for setup.ps1 itself):
#   -DemoData    also add 16 demo readers with sample activity (otherwise you are asked)
#   -SkipNeo4j   don't rebuild the Neo4j graph
#   -PgPort 5433 PostgreSQL listens on another port
param([switch]$DemoData, [switch]$SkipNeo4j, [int]$PgPort = 5432)

$ErrorActionPreference = 'Continue'
$Root    = Split-Path -Parent $MyInvocation.MyCommand.Path
$Backend = Join-Path $Root 'backend'
$EnvFile = Join-Path $Backend '.env'
$Venv    = Join-Path $Backend 'venv\Scripts\python.exe'
$Todo    = New-Object System.Collections.ArrayList

function Step($m) { Write-Host "`n== $m" -ForegroundColor Cyan }
function Ok($m)   { Write-Host "   OK   $m" -ForegroundColor Green }
function Warn($m) { Write-Host "   TODO $m" -ForegroundColor Yellow; [void]$Todo.Add($m) }
function Fail($m) { Write-Host "   FAIL $m" -ForegroundColor Red; [void]$Todo.Add("Fix: $m") }
function Ask($prompt, $default = '') {
    try { $a = Read-Host -Prompt "   $prompt" } catch { $a = '' }   # no console: use the default
    if ($a) { return $a.Trim() } else { return $default }
}

function Get-EnvValue($name) {
    if (-not (Test-Path $EnvFile)) { return '' }
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
function Test-Port($port) {
    $c = New-Object Net.Sockets.TcpClient
    try { return $c.ConnectAsync('localhost', $port).Wait(1500) -and $c.Connected } catch { return $false } finally { $c.Close() }
}

# ---------------------------------------------------------------- prerequisites
Step 'Checking what is installed'
$missing = $false
$pyVer = $null
try { $pyVer = (& python --version 2>$null) | Out-String } catch {}
if ($pyVer -match 'Python 3\.(\d+)' -and [int]$Matches[1] -ge 10) { Ok $pyVer.Trim() }
else { Fail 'Python 3.10 or newer is missing. Install it from python.org and tick "Add python.exe to PATH".'; $missing = $true }

$nodeVer = $null
try { $nodeVer = (& node --version 2>$null) | Out-String } catch {}
if ($nodeVer -match 'v(\d+)\.(\d+)' -and ([int]$Matches[1] -ge 23 -or ([int]$Matches[1] -eq 22 -and [int]$Matches[2] -ge 12) -or ([int]$Matches[1] -eq 20 -and [int]$Matches[2] -ge 19))) { Ok "Node.js $($nodeVer.Trim())" }
else { Fail 'Node.js 20.19+ or 22.12+ is missing. Install the LTS version from nodejs.org.'; $missing = $true }

$pgBin = Get-ChildItem 'C:\Program Files\PostgreSQL\*\bin\psql.exe' -ErrorAction SilentlyContinue |
         Sort-Object { $v = 0; [void][int]::TryParse((Split-Path (Split-Path $_.FullName) -Leaf), [ref]$v); $v } -Descending |
         Select-Object -First 1 | ForEach-Object { Split-Path $_.FullName }
if (-not $pgBin) { $cmd = Get-Command psql -ErrorAction SilentlyContinue; if ($cmd) { $pgBin = Split-Path $cmd.Source } }
if ($pgBin) { Ok "PostgreSQL ($pgBin)" }
else { Fail 'PostgreSQL is missing. Install PostgreSQL 15 or newer from postgresql.org (EDB installer) and remember the postgres password.'; $missing = $true }

if ($missing) {
    Write-Host "`nInstall what is missing above, open a new window, and run setup.bat again." -ForegroundColor Red
    exit 1
}

# ---------------------------------------------------------------- env file
Step 'backend/.env (settings and passwords, never committed)'
if (-not (Test-Path $EnvFile)) {
    Copy-Item (Join-Path $Backend '.env.example') $EnvFile
    Ok 'created from .env.example'
} else { Ok 'exists; only empty values are asked for' }
if (-not (Get-EnvValue 'NEO4J_PASSWORD')) {
    $v = Ask 'Neo4j password (the one you gave your Neo4j database; Enter to skip for now)'
    if ($v) { Set-EnvValue 'NEO4J_PASSWORD' $v; Ok 'Neo4j password saved' }
    else { Warn 'NEO4J_PASSWORD is empty in backend/.env. Add it, then run setup again.' }
}
if (-not (Get-EnvValue 'MONGO_URL')) {
    $v = Ask 'MongoDB URL (Enter for a local MongoDB: mongodb://localhost:27017)' 'mongodb://localhost:27017'
    Set-EnvValue 'MONGO_URL' $v; Ok "MONGO_URL = $v"
}
if (-not (Get-EnvValue 'OPENAI_API_KEY')) {
    $v = Ask 'OpenAI API key for the chatbot (Enter to skip; everything else works without it)'
    if ($v) { Set-EnvValue 'OPENAI_API_KEY' $v; Ok 'OpenAI key saved' }
}

# ---------------------------------------------------------------- python + node
Step 'Python packages (backend/venv)'
if (-not (Test-Path $Venv)) { python -m venv (Join-Path $Backend 'venv') }
if (Test-Path $Venv) {
    & $Venv -m pip install -q --disable-pip-version-check -r (Join-Path $Backend 'requirements.txt')
    if ($LASTEXITCODE -eq 0) { Ok 'installed' } else { Fail 'pip install failed (see the error above)' }
} else { Fail 'could not create backend/venv' }

Step 'Frontend packages (frontend/node_modules)'
Push-Location (Join-Path $Root 'frontend')
npm install --no-audit --no-fund --loglevel=error
if ($LASTEXITCODE -eq 0) { Ok 'installed' } else { Fail 'npm install failed (see the error above)' }
Pop-Location

# ---------------------------------------------------------------- postgres
Step 'PostgreSQL'
$pgOk = $false
$svc = Get-Service 'postgresql*' -ErrorAction SilentlyContinue | Select-Object -First 1
if ($svc -and $svc.Status -ne 'Running') {
    try { Start-Service $svc.Name -ErrorAction Stop; Ok "started the $($svc.Name) service" }
    catch { Warn "The $($svc.Name) service is stopped. Start it in services.msc (or run setup.bat as administrator)." }
}
$psql = Join-Path $pgBin 'psql.exe'
$env:PGCONNECT_TIMEOUT = '5'
$env:PGHOST = 'localhost'
$env:PGPORT = "$PgPort"
$env:PGUSER = 'postgres'
if (-not $env:PGPASSWORD) {
    $sec = Read-Host -Prompt '   Password of the PostgreSQL "postgres" user (chosen when you installed PostgreSQL)' -AsSecureString
    $env:PGPASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec))
}
function Sql($db, $sql) { & $psql -d $db -tAqc $sql }
if ((Sql 'postgres' 'SELECT 1') -ne '1') {
    Fail "could not log in as postgres on localhost:$PgPort. Wrong password, or PostgreSQL is not running. Run setup again."
} else {
    $pgOk = $true
    Ok "logged in as postgres on localhost:$PgPort"
    if ((Sql 'postgres' "SELECT 1 FROM pg_database WHERE datname = 'booklog'") -eq '1') {
        Ok 'database "booklog" already exists. Left as it is (nothing restored, no users or activity removed).'
    } else {
        Write-Host '   unzipping the catalogue snapshot...'
        Expand-Archive -Path (Join-Path $Root 'database\booklog-database.zip') -DestinationPath (Join-Path $Root 'database') -Force
        & (Join-Path $pgBin 'createdb.exe') booklog
        Write-Host '   restoring books, authors, genres, publishers and mood tags...'
        & (Join-Path $pgBin 'pg_restore.exe') --no-owner --no-privileges -d booklog (Join-Path $Root 'database\booklog.dump')
        if ($LASTEXITCODE -ne 0) { Fail 'pg_restore reported errors (see above)' }
        # roles: the API logs in as booklog_app (not a superuser, so row-level security applies);
        # booklog_reports owns the report views. 004 also fills the report views.
        foreach ($m in '003_app_role.sql', '004_report_role.sql') {
            & $psql -d booklog -q -v ON_ERROR_STOP=1 -f (Join-Path $Backend "db\migrations\$m")
            if ($LASTEXITCODE -ne 0) { Fail "$m failed" }
        }
        # empty tables start their ids at 1 again (the first person to sign up is user 1)
        $reset = @'
DO $$ DECLARE r record; BEGIN
  FOR r IN SELECT s.oid::regclass AS seq, t.oid::regclass AS tbl, a.attname AS col
           FROM pg_class s JOIN pg_depend d ON d.objid = s.oid AND d.deptype IN ('a', 'i')
           JOIN pg_class t ON t.oid = d.refobjid
           JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = d.refobjsubid
           WHERE s.relkind = 'S' LOOP
    EXECUTE format('SELECT setval(%L, COALESCE((SELECT max(%I) FROM %s), 0) + 1, false)', r.seq, r.col, r.tbl);
  END LOOP;
END $$;
'@
        & $psql -d booklog -q -v ON_ERROR_STOP=1 -c (($reset -split "`r?`n") -join ' ') | Out-Null
        $counts = Sql 'booklog' "SELECT (SELECT count(*) FROM book) || ' books, ' || (SELECT count(*) FROM author) || ' authors, ' || (SELECT count(*) FROM users) || ' users'"
        if ((Sql 'booklog' 'SELECT count(*) > 0 FROM book') -eq 't') { Ok "restored: $counts" } else { Fail 'the restore produced no books' }
    }
    # mood tags (TAG / BOOK_TAG). The snapshot has them; this only runs for databases made before them.
    if ((Sql 'booklog' "SELECT to_regclass('public.mood_rule') IS NOT NULL") -ne 't') {
        & $psql -d booklog -q -v ON_ERROR_STOP=1 -f (Join-Path $Backend 'db\migrations\005_mood_tags.sql') | Out-Null
        if ($LASTEXITCODE -eq 0) { Ok 'mood tags added' } else { Fail '005_mood_tags.sql failed' }
    }
    # booklog_app needs a password, because PostgreSQL on Windows asks for one
    if ((Get-EnvValue 'DATABASE_URL') -notmatch 'booklog_app:[^@]+@') {
        $appPw = -join ((48..57) + (97..122) | Get-Random -Count 24 | ForEach-Object { [char]$_ })
        Sql 'postgres' "ALTER ROLE booklog_app WITH LOGIN PASSWORD '$appPw'" | Out-Null
        Set-EnvValue 'DATABASE_URL' "postgresql://booklog_app:$appPw@localhost:$PgPort/booklog"
        Ok 'booklog_app password set and saved in backend/.env'
    } else { Ok 'DATABASE_URL in backend/.env already has a password' }

    # optional demo readers (never added unless asked; never removes anyone)
    $demoCount = Sql 'booklog' "SELECT count(*) FROM users WHERE firebase_uid LIKE 'demo\_%'"
    if ($demoCount -eq '0' -and (Test-Path $Venv)) {
        $add = $DemoData
        if (-not $add) { $add = (Ask 'Add 16 demo readers with diaries, follows and lists, so feeds and analytics have data? (y/N)' 'n') -match '^(y|yes)$' }
        if ($add) {
            & $Venv (Join-Path $Backend 'scripts\seed_demo_users.py')
            if ($LASTEXITCODE -eq 0) { Ok 'demo readers added' } else { Fail 'seed_demo_users.py failed' }
        } else { Ok 'no demo readers (add them later with backend\scripts\seed_demo_users.py)' }
    }
}
Remove-Item Env:PGPASSWORD, Env:PGHOST, Env:PGPORT, Env:PGUSER -ErrorAction SilentlyContinue

# ---------------------------------------------------------------- neo4j
Step 'Neo4j'
$neoPort = if ((Get-EnvValue 'NEO4J_URI') -match ':(\d+)\s*$') { [int]$Matches[1] } else { 7687 }
if ($SkipNeo4j) { Ok 'skipped (-SkipNeo4j)' }
elseif (-not (Test-Port $neoPort)) {
    Warn "Neo4j is not running on localhost:$neoPort. Start your database in Neo4j Desktop (password = NEO4J_PASSWORD in backend/.env), then run setup again."
} elseif (-not (Get-EnvValue 'NEO4J_PASSWORD')) {
    Warn 'Neo4j is running, but NEO4J_PASSWORD is empty in backend/.env. Add it and run setup again.'
} elseif ($pgOk -and (Test-Path $Venv)) {
    Write-Host '   rebuilding the graph from PostgreSQL (about a minute)...'
    & $Venv (Join-Path $Backend 'scripts\sync_neo4j.py')
    if ($LASTEXITCODE -eq 0) { Ok 'graph rebuilt' } else { Fail 'sync_neo4j.py failed (is NEO4J_PASSWORD in backend/.env right?)' }
}

# ---------------------------------------------------------------- mongo, firebase, openai
Step 'MongoDB'
$mongo = Get-EnvValue 'MONGO_URL'
if ($mongo -match '^mongodb\+srv://') {
    if ($mongo -match '<|USER:PASSWORD') { Warn 'MONGO_URL in backend/.env still has a placeholder.' }
    else { Ok 'using MongoDB Atlas (Atlas > Network Access must allow your IP)' }
} elseif ($mongo -match 'localhost|127\.0\.0\.1') {
    if (Test-Port 27017) { Ok 'local MongoDB is running on localhost:27017' }
    else { Warn 'MongoDB is not running on localhost:27017. Install MongoDB Community Server, or start the "MongoDB" service in services.msc.' }
} else { Warn 'MONGO_URL is empty in backend/.env.' }

Step 'Firebase service account key (sign-in)'
if (Test-Path (Join-Path $Root 'booklog-firebase-key.json')) { Ok 'found booklog-firebase-key.json' }
else { Warn 'booklog-firebase-key.json is missing from the project folder. Without it nobody can sign in (browsing still works). See docs/SETUP.md, step 4.' }

Step 'OpenAI key (chatbot)'
if (Get-EnvValue 'OPENAI_API_KEY') { Ok 'set' } else { Warn 'OPENAI_API_KEY is empty in backend/.env (only the chatbot needs it).' }

Write-Host "`n=================================================" -ForegroundColor Cyan
if ($Todo.Count -eq 0) { Write-Host 'All set. Double-click run.bat to start BookLog.' -ForegroundColor Green }
else {
    Write-Host 'Setup finished. Still to do:' -ForegroundColor Yellow
    $i = 1; foreach ($t in $Todo) { Write-Host "  $i. $t"; $i++ }
    Write-Host "`nThen run run.bat. docs/SETUP.md explains each step." -ForegroundColor Yellow
}
