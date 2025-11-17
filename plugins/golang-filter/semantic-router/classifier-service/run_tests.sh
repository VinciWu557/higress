#!/bin/bash

# 自动化测试脚本
# 启动分类服务、运行测试并清理

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# 配置
SERVICE_PORT=50051
SERVICE_PID=""
TEST_MODE="${1:-all}"  # all, unit, e2e

# 日志函数
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 启动分类服务
start_service() {
    log_info "启动分类服务..."

    # 检查端口是否被占用
    if nc -z localhost $SERVICE_PORT 2>/dev/null; then
        log_warn "端口 $SERVICE_PORT 已被占用，跳过服务启动"
        return 0
    fi

    # 检查虚拟环境
    if [ ! -f ".venv/bin/python3" ]; then
        log_error "虚拟环境不存在，请先运行: uv venv && uv pip install -r requirements.txt"
        exit 1
    fi

    # 启动服务
    .venv/bin/python3 src/server_demo.py > /tmp/classifier.log 2>&1 &
    SERVICE_PID=$!

    log_info "分类服务已启动 (PID: $SERVICE_PID)"
    log_info "日志位置: /tmp/classifier.log"

    # 等待服务就绪
    log_info "等待服务就绪..."
    for i in {1..30}; do
        if nc -z localhost $SERVICE_PORT 2>/dev/null; then
            log_info "分类服务已就绪"
            return 0
        fi
        sleep 1
    done

    log_error "服务启动超时"
    cat /tmp/classifier.log
    exit 1
}

# 停止分类服务
stop_service() {
    if [ ! -z "$SERVICE_PID" ]; then
        log_info "停止分类服务 (PID: $SERVICE_PID)..."
        kill $SERVICE_PID 2>/dev/null || true
        wait $SERVICE_PID 2>/dev/null || true
        log_info "分类服务已停止"
    fi
}

# 运行单元测试
run_unit_tests() {
    log_info "=" * 60
    log_info "运行单元测试"
    log_info "=" * 60

    # 启动服务
    start_service

    # 等待额外 2 秒确保服务完全就绪
    sleep 2

    # 运行测试
    log_info "执行测试脚本..."
    .venv/bin/python3 test_classifier.py

    log_info "单元测试完成"
}

# 运行端到端测试
run_e2e_tests() {
    log_info "=" * 60
    log_info "运行端到端测试"
    log_info "=" * 60

    # 设置环境变量
    export GATEWAY_URL="${GATEWAY_URL:-http://localhost:8001}"
    export CLASSIFIER_PORT=$SERVICE_PORT

    # 运行测试
    log_info "执行端到端测试脚本..."
    bash ../test/integration/test_e2e.sh

    log_info "端到端测试完成"
}

# 显示帮助
show_help() {
    cat << EOF
自动化测试脚本

用法:
    $0 [模式]

模式:
    all     运行所有测试（默认）
    unit    仅运行单元测试
    e2e     仅运行端到端测试
    help    显示此帮助

示例:
    $0              # 运行所有测试
    $0 unit         # 仅运行单元测试
    $0 e2e          # 仅运行端到端测试

环境变量:
    GATEWAY_URL     Gateway URL（默认: http://localhost:8001）
    SERVICE_PORT    服务端口（默认: 50051）

注意:
    - 分类服务会自动启动和停止
    - 需要先安装依赖: uv venv && uv pip install -r requirements.txt
EOF
}

# 主函数
main() {
    # 处理帮助
    if [ "$TEST_MODE" = "help" ]; then
        show_help
        exit 0
    fi

    log_info "=================================="
    log_info "  自动化测试开始"
    log_info "=================================="

    # 设置陷阱，确保清理
    trap stop_service EXIT

    # 根据模式运行测试
    case "$TEST_MODE" in
        unit)
            run_unit_tests
            ;;
        e2e)
            run_e2e_tests
            ;;
        all|"")
            run_unit_tests
            echo
            run_e2e_tests
            ;;
        *)
            log_error "未知模式: $TEST_MODE"
            show_help
            exit 1
            ;;
    esac

    log_info "=================================="
    log_info "  所有测试完成 ✓"
    log_info "=================================="
}

# 运行主函数
main "$@"
