@echo off
rem ---------------------------------------------------------------------------
rem  AssistEval - offline kurulum (Windows x64, 64-bit Python 3.10 - 3.14)
rem  Kullanim:  install.cmd                -> %USERPROFILE%\.assisteval altina kurar
rem             set ASSISTEVAL_HOME=D:\x   -> baska bir klasore kurmak icin
rem             set ASSISTEVAL_PYTHON=C:\Python312\python.exe -> belirli bir Python kullanmak icin
rem  Internet gerekmez: Python paketleri wheelhouse, Node.js ve promptfoo node / promptfoo klasorlerinden gelir.
rem ---------------------------------------------------------------------------
setlocal EnableExtensions
set "HERE=%~dp0"
if "%ASSISTEVAL_HOME%"=="" set "ASSISTEVAL_HOME=%USERPROFILE%\.assisteval"

set "PYCHECK=import struct,sys; sys.exit(0 if (3,10) <= sys.version_info[:2] <= (3,14) and struct.calcsize('P')*8 == 64 else 1)"
set "PYANY=import sys; sys.exit(0 if (3,10) <= sys.version_info[:2] <= (3,14) else 1)"

rem 1) 64-bit Python bul
set "PYEXE="
if defined ASSISTEVAL_PYTHON (
    "%ASSISTEVAL_PYTHON%" -c "%PYCHECK%" >nul 2>&1 && set "PYEXE="%ASSISTEVAL_PYTHON%""
    if not defined PYEXE goto :wrong_python
)
for %%V in (3.14 3.13 3.12 3.11 3.10) do (
    if not defined PYEXE (
        py -%%V-64 -c "%PYCHECK%" >nul 2>&1 && set "PYEXE=py -%%V-64"
    )
)
if not defined PYEXE (
    python -c "%PYCHECK%" >nul 2>&1 && set "PYEXE=python"
)
if not defined PYEXE goto :wrong_python
echo [1/5] Python: %PYEXE% (64-bit)

rem 2) Sanal ortam (var olan ortam 64-bit degilse uyar)
if exist "%ASSISTEVAL_HOME%\Scripts\python.exe" (
    "%ASSISTEVAL_HOME%\Scripts\python.exe" -c "%PYCHECK%" >nul 2>&1
    if errorlevel 1 (
        echo [HATA] %ASSISTEVAL_HOME% icindeki mevcut kurulum 64-bit degil veya desteklenmeyen Python surumunde.
        echo        Klasoru silip tekrar calistirin ya da ASSISTEVAL_HOME ile baska bir klasor secin.
        exit /b 15
    )
    echo [2/5] Mevcut kurulum guncellenecek: %ASSISTEVAL_HOME%
) else (
    echo [2/5] Sanal ortam olusturuluyor: %ASSISTEVAL_HOME%
    %PYEXE% -m venv "%ASSISTEVAL_HOME%"
    if errorlevel 1 ( echo [HATA] venv olusturulamadi. & exit /b 11 )
)

rem 3) Offline Python paketleri
echo [3/5] Python paketleri kuruluyor (offline)...
"%ASSISTEVAL_HOME%\Scripts\python.exe" -m pip install --no-index --find-links "%HERE%wheelhouse" --upgrade --disable-pip-version-check --quiet assisteval
if errorlevel 1 ( echo [HATA] Paket kurulumu basarisiz. & exit /b 12 )

rem 4) Node.js ve promptfoo (degerlendirme icin) kurulum klasorune kopyalanir
echo [4/5] Node.js ve promptfoo kopyalaniyor...
robocopy "%HERE%node" "%ASSISTEVAL_HOME%\node" /MIR /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 ( echo [HATA] Node.js kopyalanamadi. & exit /b 17 )
robocopy "%HERE%promptfoo" "%ASSISTEVAL_HOME%\promptfoo" /MIR /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 ( echo [HATA] promptfoo kopyalanamadi. & exit /b 17 )

rem 5) Dogrulama: bagimliliklar tutarli mi, moduller yuklenebiliyor mu, promptfoo calisiyor mu?
echo [5/5] Dogrulama...
"%ASSISTEVAL_HOME%\Scripts\python.exe" -m pip check --disable-pip-version-check
if errorlevel 1 ( echo [HATA] Eksik veya uyumsuz paket var ^(yukaridaki liste^). Klasoru silip tekrar kurun: %ASSISTEVAL_HOME% & exit /b 16 )
"%ASSISTEVAL_HOME%\Scripts\python.exe" -c "import requests, yaml, dotenv, truststore, assisteval.cli, assisteval.evaluation.provider"
if errorlevel 1 ( echo [HATA] Python modulleri yuklenemedi. Klasoru silip tekrar kurun: %ASSISTEVAL_HOME% & exit /b 16 )
"%ASSISTEVAL_HOME%\Scripts\assisteval.exe" --version
if errorlevel 1 ( echo [HATA] assisteval calismiyor. & exit /b 13 )
pushd "%ASSISTEVAL_HOME%"
"%ASSISTEVAL_HOME%\Scripts\assisteval.exe" promptfoo --version
set "PFERR=%ERRORLEVEL%"
popd
if not "%PFERR%"=="0" ( echo [HATA] promptfoo calismiyor. Klasoru silip tekrar kurun: %ASSISTEVAL_HOME% & exit /b 17 )

echo.
echo KURULUM TAMAM
echo   Komut: %ASSISTEVAL_HOME%\Scripts\assisteval.exe
exit /b 0

:wrong_python
rem 64-bit Python yok. 32-bit (veya baska) bir Python var mi?
set "FOUND_OTHER="
if defined ASSISTEVAL_PYTHON "%ASSISTEVAL_PYTHON%" -c "%PYANY%" >nul 2>&1 && set "FOUND_OTHER=1"
py -c "%PYANY%" >nul 2>&1 && set "FOUND_OTHER=1"
python -c "%PYANY%" >nul 2>&1 && set "FOUND_OTHER=1"
if defined FOUND_OTHER (
    echo [HATA] AssistEval 64-bit Python ister, ama bilgisayarda sadece 32-bit Python var.
    echo        64-bit Python 3.10 - 3.14 kurun ^(kurumsal yazilim merkezi veya python.org^), sonra tekrar calistirin.
    exit /b 14
)
echo [HATA] Python 3.10 - 3.14 bulunamadi.
echo        Kurumsal yazilim merkezinden veya python.org'dan 64-bit Python 3.12 kurun, sonra tekrar calistirin.
exit /b 10
