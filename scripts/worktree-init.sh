#!/bin/bash
# MemStack Worktree 初始化脚本
# 用于 git worktree 切换或新建后快速初始化开发环境

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 默认参数
DRY_RUN=false
SKIP_DEPS=false
SKIP_DOCKER=false
NO_START=false
VERBOSE=false

# 脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# 日志函数
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[OK]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_step() {
    echo -e "\n${GREEN}==>${NC} ${BLUE}$1${NC}"
}

# 执行命令（支持 dry-run）
run_cmd() {
    if [ "$DRY_RUN" = true ]; then
        echo -e "${YELLOW}[DRY-RUN]${NC} $*"
    else
        if [ "$VERBOSE" = true ]; then
            echo -e "${BLUE}[RUN]${NC} $*"
        fi
        eval "$@"
    fi
}

# 显示帮助
show_help() {
    cat << EOF
MemStack Worktree 初始化脚本

用法: $(basename "$0") [选项]

选项:
    -h, --help          显示此帮助信息
    -n, --dry-run       预览将要执行的操作，不实际执行
    --skip-deps         跳过依赖安装
    --skip-docker       跳过 Docker 基础设施启动
    --no-start          只初始化环境，不启动开发服务
    -v, --verbose       显示详细执行信息

使用场景:
    1. 新建 worktree 后初始化:
       git worktree add ../feature-xxx main
       cd ../feature-xxx
       ./scripts/worktree-init.sh

    2. 切换已有 worktree 时同步环境:
       cd ../another-worktree
       ./scripts/worktree-init.sh --skip-docker

    3. 预览操作:
       ./scripts/worktree-init.sh --dry-run

环境变量同步:
    - 如果是 worktree 环境，会自动检测主仓库的 .env 文件
    - 新建 worktree 时会自动从主仓库复制 .env
    - 已有 .env 时会提示选择是否从主仓库同步

EOF
}

# 解析参数
parse_args() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            -h|--help)
                show_help
                exit 0
                ;;
            -n|--dry-run)
                DRY_RUN=true
                shift
                ;;
            --skip-deps)
                SKIP_DEPS=true
                shift
                ;;
            --skip-docker)
                SKIP_DOCKER=true
                shift
                ;;
            --no-start)
                NO_START=true
                shift
                ;;
            -v|--verbose)
                VERBOSE=true
                shift
                ;;
            *)
                log_error "未知参数: $1"
                show_help
                exit 1
                ;;
        esac
    done
}

# 检查是否在 git 仓库中
check_git_repo() {
    log_step "检查 Git 仓库"
    
    if ! git rev-parse --git-dir > /dev/null 2>&1; then
        log_error "当前目录不是 Git 仓库"
        exit 1
    fi
    
    # 检查是否是 worktree
    if git rev-parse --is-inside-work-tree > /dev/null 2>&1; then
        local git_dir=$(git rev-parse --git-dir)
        if [[ "$git_dir" == *".git/worktrees/"* ]]; then
            log_info "检测到 Git Worktree 环境"
        else
            log_info "检测到主仓库环境"
        fi
    fi
    
    log_success "Git 仓库检查通过"
}

# 检查必要工具
check_prerequisites() {
    log_step "检查必要工具"
    
    local missing_tools=()
    
    # 检查 uv
    if ! command -v uv &> /dev/null; then
        missing_tools+=("uv (Python 包管理器)")
    fi
    
    # 检查 pnpm
    if ! command -v pnpm &> /dev/null; then
        missing_tools+=("pnpm (Node.js 包管理器)")
    fi
    
    # 检查 docker
    if ! command -v docker &> /dev/null; then
        missing_tools+=("docker")
    fi
    
    # 检查 make
    if ! command -v make &> /dev/null; then
        missing_tools+=("make")
    fi
    
    if [ ${#missing_tools[@]} -gt 0 ]; then
        log_error "缺少以下工具:"
        for tool in "${missing_tools[@]}"; do
            echo "  - $tool"
        done
        echo ""
        echo "安装建议:"
        echo "  uv:    curl -LsSf https://astral.sh/uv/install.sh | sh"
        echo "  pnpm:  npm install -g pnpm"
        echo "  docker: https://docs.docker.com/get-docker/"
        exit 1
    fi
    
    log_success "所有必要工具已安装"
}

# 获取主仓库路径
get_main_repo_path() {
    local git_common_dir=$(git rev-parse --git-common-dir 2>/dev/null)
    if [ -n "$git_common_dir" ] && [ "$git_common_dir" != ".git" ]; then
        # 这是一个 worktree，主仓库在 git_common_dir 的上级目录
        echo "$(cd "$git_common_dir/.." && pwd)"
    else
        # 这是主仓库本身
        echo ""
    fi
}

# 复制环境配置文件
setup_env_file() {
    log_step "配置环境文件"
    
    cd "$PROJECT_ROOT"
    
    local main_repo=$(get_main_repo_path)
    local main_env=""
    
    # 如果是 worktree，检查主仓库是否有 .env
    if [ -n "$main_repo" ] && [ -f "$main_repo/.env" ]; then
        main_env="$main_repo/.env"
        log_info "检测到主仓库 .env: $main_env"
    fi
    
    if [ -f .env ]; then
        log_warn ".env 文件已存在"
        
        # 检查是否需要从主仓库同步
        if [ -n "$main_env" ]; then
            if [ "$DRY_RUN" = false ]; then
                echo ""
                echo "可选操作:"
                echo "  1) 保留当前 .env"
                echo "  2) 从主仓库同步 .env"
                echo "  3) 从 .env.example 重新创建"
                echo ""
                read -p "请选择 [1]: " -n 1 -r choice
                echo
                
                case $choice in
                    2)
                        run_cmd "cp '$main_env' .env"
                        log_success "已从主仓库同步 .env"
                        ;;
                    3)
                        if [ -f .env.example ]; then
                            run_cmd "cp .env.example .env"
                            log_success "已从 .env.example 创建 .env"
                            log_warn "请编辑 .env 文件配置必要的 API 密钥"
                        else
                            log_error "找不到 .env.example 文件"
                        fi
                        ;;
                    *)
                        log_info "保留当前 .env 文件"
                        ;;
                esac
            else
                log_info "[DRY-RUN] 会提示用户选择是否从主仓库同步"
            fi
        else
            log_info "如需重置，请手动删除 .env 后重新运行"
        fi
    else
        # .env 不存在，需要创建
        if [ -n "$main_env" ]; then
            # 优先从主仓库复制
            run_cmd "cp '$main_env' .env"
            log_success "已从主仓库复制 .env"
            log_info "主仓库路径: $main_repo"
        elif [ -f .env.example ]; then
            # 从示例文件创建
            run_cmd "cp .env.example .env"
            log_success "已从 .env.example 创建 .env"
            log_warn "请编辑 .env 文件配置必要的 API 密钥"
        else
            log_error "找不到 .env.example 文件，也无法从主仓库获取 .env"
            exit 1
        fi
    fi
}

# 安装后端依赖
install_backend_deps() {
    log_step "安装后端依赖"
    
    cd "$PROJECT_ROOT"
    
    if [ "$SKIP_DEPS" = true ]; then
        log_warn "跳过后端依赖安装 (--skip-deps)"
        return
    fi
    
    # 检查是否已安装
    if [ -d ".venv" ] && [ -f ".venv/pyvenv.cfg" ]; then
        log_info "检测到已有虚拟环境"
        if [ "$DRY_RUN" = false ]; then
            read -p "是否重新安装依赖? (y/N) " -n 1 -r
            echo
            if [[ ! $REPLY =~ ^[Yy]$ ]]; then
                log_info "跳过后端依赖安装"
                return
            fi
        fi
    fi
    
    run_cmd "make install-backend"
    log_success "后端依赖安装完成"
}

# 安装前端依赖
install_frontend_deps() {
    log_step "安装前端依赖"
    
    cd "$PROJECT_ROOT"
    
    if [ "$SKIP_DEPS" = true ]; then
        log_warn "跳过前端依赖安装 (--skip-deps)"
        return
    fi
    
    # 检查 web 目录
    if [ ! -d "web" ]; then
        log_warn "未找到 web 目录，跳过前端依赖安装"
        return
    fi
    
    # 检查是否已安装
    if [ -d "web/node_modules" ]; then
        log_info "检测到已有 node_modules"
        if [ "$DRY_RUN" = false ]; then
            read -p "是否重新安装依赖? (y/N) " -n 1 -r
            echo
            if [[ ! $REPLY =~ ^[Yy]$ ]]; then
                log_info "跳过前端依赖安装"
                return
            fi
        fi
    fi
    
    run_cmd "make install-web"
    log_success "前端依赖安装完成"
}

# 启动 Docker 基础设施
start_docker_infra() {
    log_step "启动 Docker 基础设施"
    
    cd "$PROJECT_ROOT"
    
    if [ "$SKIP_DOCKER" = true ]; then
        log_warn "跳过 Docker 启动 (--skip-docker)"
        return
    fi
    
    # 检查 Docker 是否运行
    if ! docker info > /dev/null 2>&1; then
        log_error "Docker 未运行，请先启动 Docker Desktop"
        exit 1
    fi
    
    # 检查是否已有容器运行
    local running_containers=$(docker compose ps -q 2>/dev/null | wc -l | tr -d ' ')
    if [ "$running_containers" -gt 0 ]; then
        log_info "检测到已运行的 Docker 容器"
        if [ "$DRY_RUN" = false ]; then
            docker compose ps
            echo ""
            read -p "是否重启 Docker 服务? (y/N) " -n 1 -r
            echo
            if [[ ! $REPLY =~ ^[Yy]$ ]]; then
                log_info "保持现有 Docker 服务"
                return
            fi
        fi
    fi
    
    run_cmd "make dev-infra"
    
    # 等待服务就绪
    if [ "$DRY_RUN" = false ]; then
        log_info "等待服务就绪..."
        sleep 5
        
        # 检查关键服务
        local max_retries=30
        local retry=0
        while [ $retry -lt $max_retries ]; do
            if docker compose ps | grep -q "healthy\|running"; then
                break
            fi
            sleep 2
            retry=$((retry + 1))
        done
    fi
    
    log_success "Docker 基础设施启动完成"
}

# 初始化数据库
init_database() {
    log_step "初始化数据库"
    
    cd "$PROJECT_ROOT"
    
    if [ "$SKIP_DOCKER" = true ]; then
        log_warn "跳过数据库初始化 (因为跳过了 Docker)"
        return
    fi
    
    # 运行数据库初始化
    run_cmd "make db-init || true"  # 数据库可能已存在
    
    # 运行迁移
    run_cmd "make db-migrate"
    
    log_success "数据库初始化完成"
}

# 启动开发服务
start_dev_services() {
    log_step "启动开发服务"
    
    cd "$PROJECT_ROOT"
    
    if [ "$NO_START" = true ]; then
        log_warn "跳过服务启动 (--no-start)"
        log_info "稍后可使用 'make dev' 启动服务"
        return
    fi
    
    # 检查端口占用
    check_port_available() {
        local port=$1
        if lsof -Pi :$port -sTCP:LISTEN -t >/dev/null 2>&1; then
            return 1
        fi
        return 0
    }
    
    if ! check_port_available 8000; then
        log_warn "端口 8000 已被占用"
        if [ "$DRY_RUN" = false ]; then
            read -p "是否继续启动服务? (y/N) " -n 1 -r
            echo
            if [[ ! $REPLY =~ ^[Yy]$ ]]; then
                log_info "跳过服务启动"
                return
            fi
        fi
    fi
    
    run_cmd "make dev"
    
    log_success "开发服务启动完成"
}

# 显示完成信息
show_completion_info() {
    log_step "初始化完成"
    
    if [ "$DRY_RUN" = true ]; then
        echo ""
        log_info "以上是 dry-run 模式的预览"
        log_info "移除 --dry-run 参数以实际执行"
        return
    fi
    
    echo ""
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}  MemStack 开发环境初始化完成!${NC}"
    echo -e "${GREEN}========================================${NC}"
    echo ""
    echo "服务访问地址:"
    echo "  - API 文档:    http://localhost:8000/docs"
    echo "  - 前端应用:    http://localhost:3000"
    echo "  - Neo4j UI:    http://localhost:7474"
    echo "  - Grafana:     http://localhost:3001"
    echo ""
    echo "常用命令:"
    echo "  make dev          # 启动所有服务"
    echo "  make dev-stop     # 停止所有服务"
    echo "  make test         # 运行测试"
    echo "  make check        # 格式化 + 检查 + 测试"
    echo ""
    
    if [ -f .env ]; then
        if grep -q "your_.*_here\|YOUR_.*_KEY" .env 2>/dev/null; then
            log_warn "请编辑 .env 文件配置 API 密钥"
        fi
    fi
}

# 主函数
main() {
    echo ""
    echo -e "${BLUE}╔════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║  MemStack Worktree 初始化脚本          ║${NC}"
    echo -e "${BLUE}╚════════════════════════════════════════╝${NC}"
    echo ""
    
    parse_args "$@"
    
    if [ "$DRY_RUN" = true ]; then
        log_warn "运行模式: DRY-RUN (不会实际执行命令)"
    fi
    
    # 切换到项目根目录
    cd "$PROJECT_ROOT"
    log_info "项目目录: $PROJECT_ROOT"
    
    # 执行初始化步骤
    check_git_repo
    check_prerequisites
    setup_env_file
    install_backend_deps
    install_frontend_deps
    start_docker_infra
    init_database
    start_dev_services
    show_completion_info
}

# 运行主函数
main "$@"
