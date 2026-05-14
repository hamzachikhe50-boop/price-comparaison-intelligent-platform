@echo off
REM ════════════════════════════════════════════════════════════
REM  stop.bat — Arrete les 3 microservices sur Windows
REM ════════════════════════════════════════════════════════════

echo Arret des services uvicorn...

REM Tuer les process uvicorn sur les ports 8001 8002 8003
for %%p in (8001 8002 8003) do (
    for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":%%p " ^| findstr "LISTENING"') do (
        echo    Arret port %%p - PID %%a
        taskkill /PID %%a /F > nul 2>&1
    )
)

echo Tous les services arretes.
pause
