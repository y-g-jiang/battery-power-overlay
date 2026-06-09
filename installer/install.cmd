@echo off
setlocal

set "APP_NAME=BatteryPowerOverlay"
set "INSTALL_DIR=%LOCALAPPDATA%\BatteryPowerOverlay"
set "RUN_KEY=HKCU\Software\Microsoft\Windows\CurrentVersion\Run"

if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"
if not exist "%INSTALL_DIR%\BatteryInfoView" mkdir "%INSTALL_DIR%\BatteryInfoView"

copy /Y "%~dp0battery_power_overlay.exe" "%INSTALL_DIR%\battery_power_overlay.exe" >nul
copy /Y "%~dp0battery_power_overlay.json" "%INSTALL_DIR%\battery_power_overlay.json" >nul
copy /Y "%~dp0README.md" "%INSTALL_DIR%\README.md" >nul
copy /Y "%~dp0NOTICE.md" "%INSTALL_DIR%\NOTICE.md" >nul
copy /Y "%~dp0uninstall.cmd" "%INSTALL_DIR%\uninstall.cmd" >nul
copy /Y "%~dp0BatteryInfoView.exe" "%INSTALL_DIR%\BatteryInfoView\BatteryInfoView.exe" >nul
copy /Y "%~dp0BatteryInfoView_lng.ini" "%INSTALL_DIR%\BatteryInfoView\BatteryInfoView_lng.ini" >nul

reg add "%RUN_KEY%" /v "%APP_NAME%" /t REG_SZ /d "\"%INSTALL_DIR%\battery_power_overlay.exe\"" /f >nul

taskkill /IM battery_power_overlay.exe /F >nul 2>nul
start "" "%INSTALL_DIR%\battery_power_overlay.exe"

echo Battery Power Overlay installed to:
echo %INSTALL_DIR%
endlocal
