@echo off
setlocal
cd /d "%~dp0"
prompt $P
set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
if exist "%PYTHON_EXE%" (
    if exist "dist" rmdir /S /Q "dist"
    if exist "build" rmdir /S /Q "build"
    "%PYTHON_EXE%" -m PyInstaller --noconfirm --clean HEA_MEA_Designer.spec
    goto :end
)
call "E:\ProgramData\anaconda3\Scripts\activate.bat" hea_mea_lammps 2>nul
if errorlevel 1 call "E:\ProgramData\anaconda3\Scripts\activate.bat" base 2>nul
if exist "dist" rmdir /S /Q "dist"
if exist "build" rmdir /S /Q "build"
python -m PyInstaller --noconfirm --clean HEA_MEA_Designer.spec
:end
pause
