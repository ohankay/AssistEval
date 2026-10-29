@echo off
rem ---------------------------------------------------------------------------
rem  AssistEval - offline kurulum (Windows x64 veya x86/32-bit, Python 3.10 - 3.14)
rem  Kullanim:  install.cmd                -> %USERPROFILE%\.assisteval altina kurar
rem             set ASSISTEVAL_HOME=D:\x   -> baska bir klasore kurmak icin
rem             set ASSISTEVAL_PYTHON=C:\Python312\python.exe -> belirli bir Python kullanmak icin
rem  Internet gerekmez: tum paketler wheelhouse klasorunden yuklenir.
rem ---------------------------------------------------------------------------
setlocal EnableExtensions
set "HERE=%~dp0"
if "%ASSISTEVAL_HOME%"=="" set "ASSISTEVAL_HOME=%USERPROFILE%\.assisteval"

rem Paketin mimarisi (build sirasinda bundle_arch.txt yazilir): x64 veya x86
set "ARCH=x64"
if exist "%HERE%bundle_arch.txt" set /p ARCH=<"%HERE%bundle_arch.txt"
if /i "%ARCH%"=="x86" (
    set "BITS=32"
    set "OTHER=x64"
) else (
    set "BITS=64"
    set "OTHER=x86"
)
set "PYCHECK=import struct,sys; sys.exit(0 if (3,10) <= sys.version_info[:2] <= (3,14) and struct.calcsize('P')*8 == %BITS% else 1)"
set "PYANY=import sys; sys.exit(0 if (3,10) <= sys.version_info[:2] <= (3,14) else 1)"

rem 1) Paketle ayni mimaride (%BITS%-bit) Python bul
set "PYEXE="
if defined ASSISTEVAL_PYTHON (
    "%ASSISTEVAL_PYTHON%" -c "%PYCHECK%" >nul 2>&1 && set "PYEXE="%ASSISTEVAL_PYTHON%""
    if not defined PYEXE goto :wrong_python
)
for %%V in (3.14 3.13 3.12 3.11 3.10) do (
    if not defined PYEXE (
        py -%%V-%BITS% -c "%PYCHECK%" >nul 2>&1 && set "PYEXE=py -%%V-%BITS%"
    )
)
if not defined PYEXE (
    python -c "%PYCHECK%" >nul 2>&1 && set "PYEXE=python"
)
if not defined PYEXE goto :wrong_python
echo [1/4] Python: %PYEXE% (%BITS%-bit, paket: %ARCH%)

rem 2) Sanal ortam (var olan ortam farkli mimarideyse uyar)
if exist "%ASSISTEVAL_HOME%\Scripts\python.exe" (
    "%ASSISTEVAL_HOME%\Scripts\python.exe" -c "%PYCHECK%" >nul 2>&1
    if errorlevel 1 (
        echo [HATA] %ASSISTEVAL_HOME% icindeki mevcut kurulum farkli mimaride veya desteklenmeyen Python surumunde.
        echo        Klasoru silip tekrar calistirin ya da ASSISTEVAL_HOME ile baska bir klasor secin.
        exit /b 15
    )
    echo [2/4] Mevcut kurulum guncellenecek: %ASSISTEVAL_HOME%
) else (
    echo [2/4] Sanal ortam olusturuluyor: %ASSISTEVAL_HOME%
    %PYEXE% -m venv "%ASSISTEVAL_HOME%"
    if errorlevel 1 ( echo [HATA] venv olusturulamadi. & exit /b 11 )
)

rem 3) Offline paket kurulumu
echo [3/4] Paketler kuruluyor (offline)...
"%ASSISTEVAL_HOME%\Scripts\python.exe" -m pip install --no-index --find-links "%HERE%wheelhouse" --upgrade --disable-pip-version-check --quiet assisteval
if errorlevel 1 ( echo [HATA] Paket kurulumu basarisiz. & exit /b 12 )

rem 4) Dogrulama: bagimliliklar tutarli mi, moduller yuklenebiliyor mu?
echo [4/4] Dogrulama...
"%ASSISTEVAL_HOME%\Scripts\python.exe" -m pip check --disable-pip-version-check
if errorlevel 1 ( echo [HATA] Eksik veya uyumsuz paket var ^(yukaridaki liste^). Klasoru silip tekrar kurun: %ASSISTEVAL_HOME% & exit /b 16 )
"%ASSISTEVAL_HOME%\Scripts\python.exe" -c "import requests, yaml, dotenv, truststore, assisteval.cli"
if errorlevel 1 ( echo [HATA] Python modulleri yuklenemedi. Klasoru silip tekrar kurun: %ASSISTEVAL_HOME% & exit /b 16 )
"%ASSISTEVAL_HOME%\Scripts\assisteval.exe" --version
if errorlevel 1 ( echo [HATA] assisteval calismiyor. & exit /b 13 )

echo.
echo KURULUM TAMAM
echo   Komut: %ASSISTEVAL_HOME%\Scripts\assisteval.exe
exit /b 0

:wrong_python
rem Uygun mimaride Python yok. Baska mimaride Python var mi?
set "FOUND_OTHER="
if defined ASSISTEVAL_PYTHON "%ASSISTEVAL_PYTHON%" -c "%PYANY%" >nul 2>&1 && set "FOUND_OTHER=1"
py -c "%PYANY%" >nul 2>&1 && set "FOUND_OTHER=1"
python -c "%PYANY%" >nul 2>&1 && set "FOUND_OTHER=1"
if defined FOUND_OTHER (
    echo [HATA] Bu paket %ARCH% icin, ama bilgisayarda sadece farkli mimaride Python var.
    echo        assisteval-windows-%OTHER%.zip paketini indirip onunla kurun
    echo        veya %BITS%-bit Python 3.10 - 3.14 kurun.
    exit /b 14
)
echo [HATA] Python 3.10 - 3.14 bulunamadi.
echo        Kurumsal yazilim merkezinden veya python.org'dan Python 3.12 kurun, sonra tekrar calistirin.
exit /b 10
