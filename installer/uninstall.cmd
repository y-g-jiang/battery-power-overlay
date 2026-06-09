@echo off
setlocal

set "APP_NAME=BatteryPowerOverlay"
set "INSTALL_DIR=%LOCALAPPDATA%\BatteryPowerOverlay"
set "RUN_KEY=HKCU\Software\Microsoft\Windows\CurrentVersion\Run"

taskkill /IM battery_power_overlay.exe /F >nul 2>nul
reg delete "%RUN_KEY%" /v "%APP_NAME%" /f >nul 2>nul

start "" /MIN cmd /c "timeout /t 1 /nobreak >nul & rmdir /S /Q ""%INSTALL_DIR%"""

echo Battery Power Overlay uninstalled.
endlocal
