@echo off
REM ════════════════════════════════════════════════════════════
REM  start.bat — Lance les 3 microservices sur Windows
REM  Double-clic ou : start.bat
REM ════════════════════════════════════════════════════════════

set ROOT=%~dp0

echo ========================================================
echo   Tunisia Price Hunter - Demarrage des 3 services
echo ========================================================
echo.

if not exist "%ROOT%logs" mkdir "%ROOT%logs"

echo [1/3] Service 1 - Scraping       -^> http://localhost:8001
cd /d "%ROOT%service1-scraping"
start "Service1-Scraping" /MIN cmd /c "uvicorn app.main:app --host 0.0.0.0 --port 8001 --log-level info >> ..\logs\service1.log 2>&1"
timeout /t 2 /nobreak > nul

echo [2/3] Service 2 - Price History  -^> http://localhost:8002
cd /d "%ROOT%service2-price"
start "Service2-Price" /MIN cmd /c "uvicorn app.main:app --host 0.0.0.0 --port 8002 --log-level info >> ..\logs\service2.log 2>&1"
timeout /t 2 /nobreak > nul

echo [3/3] Service 3 - Alertes        -^> http://localhost:8003
cd /d "%ROOT%service3-alerts"
start "Service3-Alerts" /MIN cmd /c "uvicorn app.main:app --host 0.0.0.0 --port 8003 --log-level info >> ..\logs\service3.log 2>&1"

cd /d "%ROOT%"
echo.
echo ========================================================
echo Les 3 services tournent dans des fenetres minimisees
echo.
echo   Swagger UI :
echo     http://localhost:8001/docs  (Scraping)
echo     http://localhost:8002/docs  (Price History)
echo     http://localhost:8003/docs  (Alertes)
echo.
echo   Diagnostic DB :
echo     http://localhost:8002/
echo     http://localhost:8003/
echo.
echo   Pour arreter : fermez les 3 fenetres CMD minimisees
echo    ou lancez stop.bat
echo ========================================================
pause
