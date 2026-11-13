@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo ==========================================
echo 课程记录与工资管理 - Windows 11 打包
echo ==========================================

if not exist ".venv" (
    echo [1/3] 创建 Python 虚拟环境...
    py -3.11 -m venv .venv
    if errorlevel 1 goto :error
)

call ".venv\Scripts\activate.bat"
if errorlevel 1 goto :error

echo [2/3] 安装或更新打包依赖...
python -m pip install --upgrade pip
python -m pip install -r requirements-windows.txt
if errorlevel 1 goto :error

echo [3/3] 打包 Windows 程序...
python -m PyInstaller --noconfirm --clean --windowed --onedir ^
  --name "CourseManager" ^
  --collect-all kivy ^
  --collect-all openpyxl ^
  --add-data "assets;assets" ^
  --add-data "fonts;fonts" ^
  main.py
if errorlevel 1 goto :error

echo.
echo 打包完成：dist\CourseManager\CourseManager.exe
echo 请将整个 dist\CourseManager 文件夹作为一个整体分发，不要只复制 exe。
pause
exit /b 0

:error
echo.
echo 打包失败。请检查上方错误信息，并确认已安装 Python 3.11 64 位。
pause
exit /b 1
