@echo off
setlocal
cd /d "%~dp0"
rem 用法：先 conda activate 你的環境 再執行；或指定 Python：打包成exe.bat C:\路徑\python.exe
rem 加上「資料夾版」打包成一個資料夾（較不會被防毒軟體誤判）：打包成exe.bat 資料夾版
set "MODE=--onefile"
set "PY=%~1"
if /i "%~1"=="資料夾版" (
  set "MODE=--onedir"
  set "PY=%~2"
)
if /i "%~2"=="資料夾版" set "MODE=--onedir"
if "%PY%"=="" if defined CONDA_PREFIX set "PY=%CONDA_PREFIX%\python.exe"
if "%PY%"=="" set "PY=python"
set "PYPREFIX="
for /f "usebackq delims=" %%P in (`call "%PY%" -c "import sys;print(sys.prefix)"`) do set "PYPREFIX=%%P"
if not defined PYPREFIX (
  echo 找不到 Python：%PY%
  goto fail
)
echo 使用的 Python：%PYPREFIX%
rem conda 環境的 tk86t.dll、tcl86t.dll 等在 Library\bin，要加進 PATH 才會被打包
if exist "%PYPREFIX%\Library\bin" set "PATH=%PYPREFIX%\Library\bin;%PATH%"
echo 正在安裝或更新 PyInstaller...
"%PY%" -m pip install --upgrade pyinstaller
if errorlevel 1 (
  echo 安裝 PyInstaller 失敗，請確認可以上網。
  goto fail
)
echo 正在產生程式圖示...
"%PY%" "AI協作.py" --write-icon "AI協作.ico"
if errorlevel 1 (
  echo 產生圖示失敗。
  goto fail
)
echo 正在打包 AI協作.py ...
set "EXTRA="
rem 拓樸圖的動態角色：有「機器人動畫」資料夾就一起打包進 exe
if exist "機器人動畫\" set "EXTRA=--add-data "機器人動畫;機器人動畫""
"%PY%" -m PyInstaller --noconfirm %MODE% --windowed --icon "AI協作.ico" --name "AI協作" %EXTRA% "AI協作.py"
if errorlevel 1 (
  echo 打包失敗，請查看上面的錯誤訊息。
  goto fail
)
echo.
if "%MODE%"=="--onedir" (
  echo 完成：dist\AI協作\AI協作.exe（資料夾版：整個 dist\AI協作 資料夾要一起複製）
) else (
  echo 完成：dist\AI協作.exe
)
echo 設定、紀錄、對話會存在 exe 所在的資料夾。
if not defined NOPAUSE pause
exit /b 0
:fail
if not defined NOPAUSE pause
exit /b 1
