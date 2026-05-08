@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

REM ==========================================
REM 智能体内网离线部署准备脚本 (Windows)
REM 用于在外网机器上准备所有离线部署文件
REM ==========================================

echo.
echo ==========================================
echo   智能体内网离线部署准备工具
echo ==========================================
echo.

REM 检查 Python 是否安装
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未检测到 Python，请安装 Python 3.11+
    pause
    exit /b 1
)

REM 检查 Docker 是否安装
docker --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未检测到 Docker，请安装 Docker Desktop
    pause
    exit /b 1
)

echo [信息] 环境检查通过
echo.

REM 步骤 1: 下载 Python 包
echo ==========================================
echo 步骤 1: 下载 Python 依赖包
echo ==========================================
echo.

python download_packages.py
if errorlevel 1 (
    echo [错误] Python 包下载失败
    pause
    exit /b 1
)

echo.

REM 步骤 2: 拉取 Docker 镜像
echo ==========================================
echo 步骤 2: 拉取 Docker 基础镜像
echo ==========================================
echo.

echo [信息] 正在拉取 python:3.11-slim 镜像...
docker pull python:3.11-slim
if errorlevel 1 (
    echo [错误] Docker 镜像拉取失败
    pause
    exit /b 1
)

echo [信息] 正在导出 Docker 镜像...
docker save -o python-3.11-slim.tar python:3.11-slim
if errorlevel 1 (
    echo [错误] Docker 镜像导出失败
    pause
    exit /b 1
)

echo [成功] Docker 镜像已导出为 python-3.11-slim.tar
echo.

REM 步骤 3: 打包项目文件
echo ==========================================
echo 步骤 3: 打包项目文件
echo ==========================================
echo.

echo [信息] 正在创建项目文件包...

REM 使用 PowerShell 创建压缩包（排除不必要的文件）
powershell -Command "Compress-Archive -Path @(Get-ChildItem -Exclude '.git','__pycache__','logs','data','*.tar','*.tar.gz','python-packages') -DestinationPath 'industrial-agent-src.zip' -Force"

if errorlevel 1 (
    echo [警告] PowerShell 压缩失败，尝试使用其他方式...
    REM 如果 PowerShell 失败，提示手动操作
    echo [提示] 请手动复制以下文件到内网:
    echo   - Dockerfile
    echo   - docker-compose.intranet.yml
    echo   - requirements.txt
    echo   - .env.example
    echo   - 所有源代码目录 (agent, core, llm, prompts, rag, skills, static)
) else (
    echo [成功] 项目文件已打包为 industrial-agent-src.zip
)

echo.

REM 完成
echo ==========================================
echo   准备工作完成!
echo ==========================================
echo.
echo 请复制以下文件到内网机器:
echo.
echo   1. python-3.11-slim.tar     (Docker 基础镜像)
echo   2. python-packages\          (Python 依赖包)
echo   3. industrial-agent-src.zip  (项目源代码)
echo.
echo ==========================================
echo.

pause