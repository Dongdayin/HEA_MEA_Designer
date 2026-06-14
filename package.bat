@echo off
setlocal
cd /d "%~dp0"
prompt $P
set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
set "RUNTIME_BACKUP=%TEMP%\HEA_MEA_Designer_runtime_%RANDOM%%RANDOM%"
set "BUILD_RESULT=0"
call :backup_runtime
if exist "%PYTHON_EXE%" (
    if exist "dist" rmdir /S /Q "dist"
    if exist "build" rmdir /S /Q "build"
    "%PYTHON_EXE%" -m PyInstaller --noconfirm --clean HEA_MEA_Designer.spec
    set "BUILD_RESULT=%ERRORLEVEL%"
    call :restore_runtime
    goto :end
)
call "E:\ProgramData\anaconda3\Scripts\activate.bat" hea_mea_lammps 2>nul
if errorlevel 1 call "E:\ProgramData\anaconda3\Scripts\activate.bat" base 2>nul
if exist "dist" rmdir /S /Q "dist"
if exist "build" rmdir /S /Q "build"
python -m PyInstaller --noconfirm --clean HEA_MEA_Designer.spec
set "BUILD_RESULT=%ERRORLEVEL%"
call :restore_runtime
:end
pause
exit /b %BUILD_RESULT%

:backup_runtime
if exist "dist\HEA_MEA_Designer\config.json" (
    if not exist "%RUNTIME_BACKUP%" mkdir "%RUNTIME_BACKUP%"
    copy /Y "dist\HEA_MEA_Designer\config.json" "%RUNTIME_BACKUP%\config.json" >nul
)
if exist "dist\HEA_MEA_Designer\generated" (
    if not exist "%RUNTIME_BACKUP%" mkdir "%RUNTIME_BACKUP%"
    xcopy /E /I /Y "dist\HEA_MEA_Designer\generated" "%RUNTIME_BACKUP%\generated" >nul
)
exit /b 0

:restore_runtime
if not exist "dist\HEA_MEA_Designer" exit /b 0
if exist "%RUNTIME_BACKUP%\config.json" (
    copy /Y "%RUNTIME_BACKUP%\config.json" "dist\HEA_MEA_Designer\config.json" >nul
)
if exist "%RUNTIME_BACKUP%\generated" (
    if exist "dist\HEA_MEA_Designer\generated" rmdir /S /Q "dist\HEA_MEA_Designer\generated"
    xcopy /E /I /Y "%RUNTIME_BACKUP%\generated" "dist\HEA_MEA_Designer\generated" >nul
)
exit /b 0
