#!/bin/bash
# Industrial Agent Deployment Script
# 智能体快速部署脚本

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 日志函数
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 检查 Docker 是否安装
check_docker() {
    if ! command -v docker &> /dev/null; then
        log_error "Docker 未安装，请先安装 Docker"
        exit 1
    fi
    
    if ! command -v docker compose &> /dev/null; then
        log_error "Docker Compose 未安装，请先安装 Docker Compose"
        exit 1
    fi
    
    log_success "Docker 和 Docker Compose 已安装"
}

# 检查环境变量文件
check_env() {
    if [ ! -f ".env" ]; then
        log_warning ".env 文件不存在，正在从 .env.example 创建..."
        cp .env.example .env
        log_warning "请编辑 .env 文件，填入实际的 API 密钥"
        read -p "按回车键继续..."
    fi
}

# 创建必要目录
create_directories() {
    log_info "创建必要目录..."
    mkdir -p logs data nginx/ssl nginx/logs
    log_success "目录创建完成"
}

# 构建镜像
build_image() {
    log_info "开始构建 Docker 镜像..."
    docker compose build
    log_success "镜像构建完成"
}

# 启动服务
start_services() {
    local mode=$1
    
    if [ "$mode" == "intranet" ]; then
        log_info "使用内网部署配置启动服务..."
        docker compose -f docker-compose.intranet.yml up -d
    else
        log_info "启动服务..."
        docker compose up -d
    fi
    
    log_success "服务启动完成"
}

# 健康检查
health_check() {
    log_info "等待服务启动..."
    sleep 10
    
    log_info "执行健康检查..."
    if curl -f http://localhost:18000/health &> /dev/null; then
        log_success "服务运行正常!"
        echo ""
        echo "=========================================="
        echo "  智能体部署完成!"
        echo "=========================================="
        echo ""
        echo "  API 地址：http://localhost:18000"
        echo "  健康检查：http://localhost:18000/health"
        echo "  前端页面：http://localhost:18000/static/index.html"
        echo ""
        echo "  查看日志：docker compose logs -f"
        echo "  停止服务：docker compose down"
        echo ""
    else
        log_error "服务可能未正常启动，请查看日志"
        echo "  docker compose logs"
    fi
}

# 显示使用帮助
show_help() {
    echo "智能体快速部署脚本"
    echo ""
    echo "用法：$0 [选项]"
    echo ""
    echo "选项:"
    echo "  -b, --build       仅构建镜像，不启动服务"
    echo "  -s, --start       启动已构建的服务"
    echo "  -i, --intranet    使用内网部署配置（包含 Nginx）"
    echo "  -r, --restart     重启服务"
    echo "  -d, --down        停止并删除服务"
    echo "  -l, --logs        查看日志"
    echo "  -h, --help        显示此帮助信息"
    echo ""
    echo "示例:"
    echo "  $0                  # 快速部署（默认配置）"
    echo "  $0 -i               # 内网部署（带 Nginx 反向代理）"
    echo "  $0 -b               # 仅构建镜像"
    echo "  $0 -r               # 重启服务"
    echo ""
}

# 主函数
main() {
    echo ""
    echo "=========================================="
    echo "  智能体 Docker 部署工具"
    echo "=========================================="
    echo ""
    
    case "${1:-}" in
        -b|--build)
            check_docker
            check_env
            create_directories
            build_image
            ;;
        -s|--start)
            check_docker
            start_services
            health_check
            ;;
        -i|--intranet)
            check_docker
            check_env
            create_directories
            build_image
            start_services "intranet"
            health_check
            ;;
        -r|--restart)
            docker compose restart
            log_success "服务已重启"
            ;;
        -d|--down)
            docker compose down
            log_success "服务已停止"
            ;;
        -l|--logs)
            docker compose logs -f
            ;;
        -h|--help)
            show_help
            ;;
        "")
            check_docker
            check_env
            create_directories
            build_image
            start_services
            health_check
            ;;
        *)
            log_error "未知选项：$1"
            show_help
            exit 1
            ;;
    esac
}

main "$@"