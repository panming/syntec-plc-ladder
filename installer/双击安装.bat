@echo off
chcp 65001 >nul 2>nul
setlocal
cd /d "%~dp0"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
title 新代梯形图工具 安装

echo.
echo  ============================================================
echo   新代（SYNTEC）梯形图工具 安装程序
echo  ============================================================
echo.
echo  安装前请先关掉 WorkBuddy（托盘图标右键退出，不是点右上角）。
echo.

rem ---- 找一个能用的 Python。优先 py 启动器，其次 python。
set "PY="
where py >nul 2>nul && py -3 -V >nul 2>nul && set "PY=py -3"
if not defined PY (
    where python >nul 2>nul && python -V >nul 2>nul && set "PY=python"
)
if not defined PY (
    echo  [!!] 这台电脑上没有可用的 Python。
    echo.
    echo       接下来会自动打开下载页面，做三件事就行：
    echo         1. 点黄色的 Download Python 按钮
    echo         2. 双击下载好的安装包
    echo         3. 第一屏最下面那个 "Add python.exe to PATH" 一定要勾上
    echo.
    echo       装完把本窗口关掉，重新双击这个文件。
    echo.
    pause
    start "" "https://www.python.org/downloads/"
    exit /b 1
)

echo   用的是：%PY%
echo.
%PY% "%~dp0setup.py" %*
set "RC=%ERRORLEVEL%"

echo.
if "%RC%"=="0" (
    echo  安装完成。按任意键关闭本窗口。
) else (
    echo  [!!] 安装没有走完，上面最后几行就是原因。
    echo       把这几行截图发给你朋友。
)
echo.
pause
exit /b %RC%
