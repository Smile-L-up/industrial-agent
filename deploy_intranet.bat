@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

REM ==========================================
REM 智能体内网部署脚本 (Windows)
REM 用于在内网机器上部署服务
REM ==========================================

echo.
echo ==========================================
echo   智能体内网部署工具
echo ==========================================
echo.

REM 检查 Docker 是否安装
docker --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未检测到 Docker，请安装 Docker Desktop
    pause
    exit /b 1
)

echo [信息] Docker 已安装
echo.

REM 检查 Docker 镜像
echo ==========================================
echo 步骤 1: 检查 Docker 镜像
echo ==========================================
echo.

docker images python:3.11-slim | findstr "python" >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 python:3.11-slim 镜像
    echo [提示] 请先导入镜像：docker load -i python-3.11-slim.tar
    pause
    exit /b 1
)

echo [成功] Docker 基础镜像已就绪
echo.

REM 检查项目文件
echo ==========================================
echo 步骤 2: 检查项目文件
echo ==========================================
echo.

if not exist "Dockerfile" (
    echo [错误] 未找到 Dockerfile
    pause
    exit /b 1
)

if not exist "docker-compose.intranet.yml" (
    echo [错误] 未找到 docker-compose.intranet.yml
    pause
    exit /b 1
)

if not exist "requirements.txt" (
    echo [错误] 未找到 requirements.txt
    pause
    exit /b 1
)

if not exist "python-packages" (
    echo [错误] 未找到 python-packages 目录
    echo [提示] 请确保 python-packages 目录与 Dockerfile 在同一层级
    pause
    exit /b 1
)

echo [成功] 项目文件检查通过
echo.

REM 检查环境变量
echo ==========================================
echo 步骤 3: 检查环境变量配置
echo ==========================================
echo.

if not exist ".env" (
    echo [警告] .env 文件不存在，正在创建...
    copy .env.example .env >nul
    echo [提示] 请编辑 .env 文件，填入 DASHSCOPE_API_KEY
    echo.
    set /p edit="是否现在编辑 .env 文件？(Y/N): "
    if /i "!edit!"=="Y" (
        notepad .env
    )
)

echo.

REM 创建必要目录
echo ==========================================
echo 步骤 4: 创建必要目录
echo ==========================================
echo.

if not exist "logs" mkdir logs
if not exist "data" mkdir data
echo [成功] 目录创建完成
echo.

REM 构建镜像
echo ==========================================
echo 步骤 5: 构建 Docker 镜像
echo ==========================================
echo.

echo [信息] 开始构建镜像，这可能需要几分钟...
docker compose -f docker-compose.intranet.yml build
if errorlevel 1 (
    echo [错误] 镜像构建失败
    pause
    exit /b 1
)

echo [成功] 镜像构建完成
echo.

REM 启动服务
echo ==========================================
echo 步骤 6: 启动服务
echo ==========================================
echo.

docker compose -f docker-compose.intranet.yml up -d
if errorlevel 1 (
    echo [错误] 服务启动失败
    pause
    exit /b 1
)

echo [成功] 服务已启动
echo.

REM 等待服务启动
echo ==========================================
echo 步骤 7: 等待服务启动...
echo ==========================================
echo.

timeout /t 10 /nobreak >nul

REM 健康检查
echo ==========================================
echo 步骤 8: 健康检查
echo ==========================================
echo.

curl -f http://localhost:18000/health >nul 2>&1
if errorlevel 1 (
    echo [警告] 服务可能未正常启动
    echo [提示] 查看日志：docker compose logs -f
) else (
    echo [成功] 服务运行正常!
)

echo.
echo ==========================================
echo   部署完成!
echo ==========================================
echo.
echo 服务信息:
echo   API 地址：http://localhost:18000
echo   健康检查：http://localhost:18000/health
echo   前端页面：http://localhost:18000/static/index.html
echo.
echo 常用命令:
echo   查看日志：docker compose logs -f
echo   停止服务：docker compose down
echo   重启服务：docker compose restart
echo.

pause