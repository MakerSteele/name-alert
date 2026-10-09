@echo off
rem Builds dist\NameAlert\NameAlert.exe and dist\NameAlert-win64.zip
setlocal
cd /d "%~dp0"

echo === Installing build tools ===
py -m pip install --upgrade -r requirements.txt pyinstaller
if errorlevel 1 goto err

if exist "vosk-model-small-en-us-0.15\" goto model_ok
echo === Downloading speech model, about 40 MB ===
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference='SilentlyContinue'; Invoke-WebRequest 'https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip' -OutFile 'model.zip'; Expand-Archive 'model.zip' -DestinationPath '.' -Force; Remove-Item 'model.zip'"
if errorlevel 1 goto err
:model_ok

echo === Building exe ===
py -m PyInstaller --noconfirm --clean --windowed --name NameAlert ^
  --add-data "vosk-model-small-en-us-0.15;vosk-model-small-en-us-0.15" ^
  --collect-binaries vosk --hidden-import pystray._win32 name_alert.py
if errorlevel 1 goto err

echo === Zipping ===
powershell -NoProfile -Command "Compress-Archive -Path 'dist\NameAlert' -DestinationPath 'dist\NameAlert-win64.zip' -Force"
if errorlevel 1 goto err

echo.
echo === DONE: dist\NameAlert-win64.zip  (test with dist\NameAlert\NameAlert.exe) ===
pause
exit /b 0

:err
echo.
echo *** Build failed - copy the error text above and send it to Claude. ***
pause
exit /b 1
