@echo off
rem Run-from-source setup (for development). Coworkers should use the .exe from Releases.
setlocal
cd /d "%~dp0"

echo === Installing Python packages ===
py -m pip install --upgrade -r requirements.txt
if errorlevel 1 goto err

if exist "vosk-model-small-en-us-0.15\" goto model_ok
echo === Downloading speech model, about 40 MB ===
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference='SilentlyContinue'; Invoke-WebRequest 'https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip' -OutFile 'model.zip'; Expand-Archive 'model.zip' -DestinationPath '.' -Force; Remove-Item 'model.zip'"
if errorlevel 1 goto err
:model_ok

echo === Creating desktop shortcut "Name Alert" ===
powershell -NoProfile -ExecutionPolicy Bypass -Command "$pyw=(Get-Command pyw.exe).Source; $s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop')+'\Name Alert.lnk'); $s.TargetPath=$pyw; $s.Arguments='\"%~dp0name_alert.py\"'; $s.WorkingDirectory='%~dp0'; $s.Save()"
if errorlevel 1 goto err

echo.
echo === DONE. Double-click "Name Alert" on your desktop to start it. ===
pause
exit /b 0

:err
echo.
echo *** Something failed above. Copy the error text and send it to Claude. ***
pause
exit /b 1
