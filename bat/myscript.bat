@echo off
setlocal enabledelayedexpansion

REM 检查参数是否为 "list"
if "%~1"=="list" (
    REM 设置目标目录路径（相对当前脚本所在目录的上级目录下的 scripts 文件夹）
    set "target_dir=%~dp0..\scripts"

    REM 检查目录是否存在
    if not exist "!target_dir!\" (
        echo Directory "!target_dir!" does not exist.
        exit /b 1
    )

    REM 列出所有 Python 脚本（.py 文件）
    echo Python scripts in "!target_dir!": 
    echo --------------------------------
    dir /b /a-d "!target_dir!\*.py" 2>nul
    echo --------------------------------

    REM 如果没有找到文件，显示提示
    if errorlevel 1 (
        echo No Python scripts found in "!target_dir!".
    )
    echo.  
    exit /b 0
)

REM 如果没有参数或参数无效，显示帮助信息
echo Usage:
echo   myscript list    List all Python scripts in ../scripts/
echo.  
exit /b 1