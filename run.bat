@echo off
setlocal
cd /d "%~dp0"

if not exist "backend\venv\Scripts\python.exe" (
    echo Run setup.bat first.
    pause
    exit /b 1
)

REM Start the PostgreSQL service if it is stopped (any version). Start Neo4j yourself in Neo4j Desktop.
for /f "tokens=2" %%s in ('sc query state^= all ^| findstr /r /c:"SERVICE_NAME: postgresql"') do (
    sc query %%s | find "RUNNING" >nul || net start %%s >nul 2>&1
)

start "BookLog API (port 8000)" cmd /k "cd /d %~dp0backend && venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000"
start "BookLog Web (port 5173)" cmd /k "cd /d %~dp0frontend && npm run dev"

timeout /t 6 /nobreak >nul
start "" http://localhost:5173
start "" http://localhost:8000/health
echo.
echo BookLog is starting in two new windows. Close them to stop.
