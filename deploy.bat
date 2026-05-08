@echo off
chcp 65001 >nul
REM Industrial Agent Deployment Script (Windows)
REM 智能体快速部署脚本 (Windows 版本)

setlocal enabledelayedexpansion

REM 颜色定义（Windows 10+ 支持 ANSI 颜色）
set "BLUE=[INFO]"
set "GREEN=[SUCCESS]"
set "YELLOW=[WARNING]"
set "RED=[ERROR]"

REM 日志函数
:log_info
echo %BLUE% %~1
goto :eof

:log_success
echo %GREEN% %~1
goto :eof

:log_warning
echo %YELLOW% %~1
goto :eof

:log_error
echo %RED% %~1
goto :eof

REM 检查 Docker 是否安装
:check_docker
docker --version >nul 2>&1
if errorlevel 1 (
    call :log_error "Docker 未安装，请先安装 Docker Desktop"
    echo 下载地址：https://www.docker.com/products/docker-desktop
    pause
    exit /b 1
)

docker compose version >nul 2>&1
if errorlevel 1 (
    call :log_error "Docker Compose 未安装"
    pause
    exit /b 1
)

call :log_success "Docker 和 Docker Compose 已安装"
goto :eof

REM 检查环境变量文件
:check_env
if not exist ".env" (
    call :log_warning ".env 文件不存在，正在从 .env.example 创建..."
    copy .env.example .env >nul
    call :log_warning "请编辑 .env 文件，填入实际的 API 密钥"
    echo.
    echo 按任意键继续...
    pause >nul
)
goto :eof

REM 创建必要目录
:create_directories
call :log_info "创建必要目录..."
if not exist "logs" mkdir logs
if not exist "data" mkdir data
if not exist "nginx" mkdir nginx
if not exist "nginx\ssl" mkdir nginx\ssl
if not exist "nginx\logs" mkdir nginx\logs
call :log_success "目录创建完成"
goto :eof

REM 构建镜像
:build_image
call :log_info "开始构建 Docker 镜像..."
docker compose build
if errorlevel 1 (
    call :log_error "镜像构建失败"
    exit /b 1
)
call :log_success "镜像构建完成"
goto :eof

REM 启动服务
:start_services
set "mode=%~1"

if "%mode%"=="intranet" (
    call :log_info "使用内网部署配置启动服务..."
    docker compose -f docker-compose.intranet.yml up -d
) else (
    call :log_info "启动服务..."
    docker compose up -d
)
call :log_success "服务启动完成"
goto :eof

REM 健康检查
:health_check
call :log_info "等待服务启动..."
timeout /t 10 /nobreak >nul

call :log_info "执行健康检查..."
curl -f http://localhost:18000/health >nul 2>&1
if errorlevel 1 (
    call :log_error "服务可能未正常启动，请查看日志"
    echo   docker compose logs
) else (
    call :log_success "服务运行正常!"
    echo.
    echo ==========================================
    echo   智能体部署完成!
    echo ==========================================
    echo.
    echo   API 地址：http://localhost:18000
    echo   健康检查：http://localhost:18000/health
    echo   前端页面：http://localhost:18000/static/index.html
    echo.
    echo   查看日志：docker compose logs -f
    echo   停止服务：docker compose down
    echo.
)
goto :eof

REM 显示使用帮助
:show_help
echo 智能体快速部署脚本 (Windows 版本)
echo.
echo 用法：%~nx0 [选项]
echo.
echo 选项:
echo   -b, --build       仅构建镜像，不启动服务
echo   -s, --start       启动已构建的服务
echo   -i, --intranet    使用内网部署配置（包含 Nginx）
echo   -r, --restart     重启服务
echo   -d, --down        停止并删除服务
echo   -l, --logs        查看日志
echo   -h, --help        显示此帮助信息
echo.
echo 示例:
echo   %~nx0                  # 快速部署（默认配置）
echo   %~nx0 -i               # 内网部署（带 Nginx 反向代理）
echo   %~nx0 -b               # 仅构建镜像
echo   %~nx0 -r               # 重启服务
echo.
goto :eof

REM 主函数
:main
echo.
echo ==========================================
echo   智能体 Docker 部署工具
echo ==========================================
echo.

if "%~1"=="" goto :default
if "%~1"=="-b" goto :build_only
if "%~1"=="--build" goto :build_only
if "%~1"=="-s" goto :start_only
if "%~1"=="--start" goto :start_only
if "%~1"=="-i" goto :intranet
if "%~1"=="--intranet" goto :intranet
if "%~1"=="-r" goto :restart
if "%~1"=="--restart" goto :restart
if "%~1"=="-d" goto :down
if "%~1"=="--down" goto :down
if "%~1"=="-l" goto :logs
if "%~1"=="--logs" goto :logs
if "%~1"=="-h" goto :help
if "%~1"=="--help" goto :help

call :log_error "未知选项：%~1"
goto :help

:default
call :check_docker
call :check_env
call :create_directories
call :build_image
call :start_services
call :health_check
goto :end

:build_only
call :check_docker
call :check_env
call :create_directories
call :build_image
goto :end

:start_only
call :check_docker
call :start_services
call :health_check
goto :end

:intranet
call :check_docker
call :check_env
call :create_directories
call :build_image
call :start_services intranet
call :health_check
goto :end

:restart
docker compose restart
call :log_success "服务已重启"
goto :end

:down
docker compose down
call :log_success "服务已停止"
goto :end

:logs
docker compose logs -f
goto :end

:help
call :show_help
goto :end

:end
endlocal