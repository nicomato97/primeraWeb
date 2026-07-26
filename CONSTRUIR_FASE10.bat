@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>nul
if not errorlevel 1 (
  set "PY=py -3"
) else (
  set "PY=python"
)
if not exist "Rumbo11_Fase_9_v0.9.0.zip" (
  echo Coloque Rumbo11_Fase_9_v0.9.0.zip en esta misma carpeta.
  pause
  exit /b 1
)
%PY% finalize_phase10.py Rumbo11_Fase_9_v0.9.0.zip
if errorlevel 1 (
  echo No fue posible construir la entrega final.
  pause
  exit /b 1
)
echo.
echo Entrega creada: Rumbo11_Final_v1.0.0.zip
pause
