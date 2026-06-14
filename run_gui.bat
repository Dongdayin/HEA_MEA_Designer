@echo off
setlocal
cd /d "%~dp0"
prompt $P
set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
if exist "%PYTHON_EXE%" (
    "%PYTHON_EXE%" hea_mea_designer.py
    goto :end
)
call "E:\ProgramData\anaconda3\Scripts\activate.bat" hea_mea_lammps 2>nul
if errorlevel 1 call "E:\ProgramData\anaconda3\Scripts\activate.bat" base 2>nul
python hea_mea_designer.py
:end
pause
