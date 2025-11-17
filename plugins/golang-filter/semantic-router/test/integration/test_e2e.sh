#!/bin/bash

# 语义路由插件端到端集成测试
# 测试 Higress 插件 + 分类服务的完整集成

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 测试配置
GATEWAY_URL="${GATEWAY_URL:-http://localhost:8001}"
CLASSIFIER_PORT="${CLASSIFIER_PORT:-50051}"
TEST_CONFIG="../test-config.yaml"

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

log_test() {
    echo -e "${BLUE}[TEST]${NC} $1"
}

# 检查依赖
check_dependencies() {
    log_info "检查测试依赖..."

    if ! command -v curl &> /dev/null; then
        log_error "curl 未安装"
        exit 1
    fi

    if ! command -v jq &> /dev/null; then
        log_warn "jq 未安装，JSON 解析功能可能受限"
    fi

    log_info "依赖检查完成"
}

# 启动分类服务
start_classifier_service() {
    log_info "启动分类服务..."

    # 检查服务是否已运行
    if nc -z localhost $CLASSIFIER_PORT 2>/dev/null; then
        log_warn "分类服务已在端口 $CLASSIFIER_PORT 上运行"
        return 0
    fi

    # 启动服务（后台运行）
    # 注意：在实际使用中，应该使用正确的 Python 虚拟环境路径
    python3 ../src/server.py &
    CLASSIFIER_PID=$!
    log_info "分类服务已启动 (PID: $CLASSIFIER_PID)"

    # 等待服务就绪
    log_info "等待服务就绪..."
    for i in {1..30}; do
        if nc -z localhost $CLASSIFIER_PORT 2>/dev/null; then
            log_info "分类服务已就绪"
            return 0
        fi
        sleep 1
    done

    log_error "分类服务启动超时"
    return 1
}

# 停止分类服务
stop_classifier_service() {
    if [ ! -z "$CLASSIFIER_PID" ]; then
        log_info "停止分类服务..."
        kill $CLASSIFIER_PID 2>/dev/null || true
        wait $CLASSIFIER_PID 2>/dev/null || true
        log_info "分类服务已停止"
    fi
}

# 发送测试请求并验证
test_request() {
    local test_name="$1"
    local messages="$2"
    local expected_category="$3"
    local expected_model="$4"

    log_test "测试: $test_name"

    # 发送请求
    response=$(curl -s -i -X POST "$GATEWAY_URL/v1/chat/completions" \
        -H "Content-Type: application/json" \
        -d "{\"model\": \"gpt-3.5-turbo\", \"messages\": $messages}")

    # 检查 HTTP 状态码
    http_code=$(echo "$response" | grep -i "HTTP" | head -1 | awk '{print $2}')
    if [ "$http_code" -ne 200 ]; then
        log_error "HTTP状态码错误: $http_code"
        echo "$response"
        return 1
    fi

    # 检查路由头
    target_model=$(echo "$response" | grep -i "X-Target-Model" | awk '{print $2}' | tr -d '\r')
    classification=$(echo "$response" | grep -i "X-Classification" | awk '{print $2}' | tr -d '\r')
    confidence=$(echo "$response" | grep -i "X-Confidence" | awk '{print $2}' | tr -d '\r')
    method=$(echo "$response" | grep -i "X-Classification-Method" | awk '{print $2}' | tr -d '\r')

    # 验证结果
    local success=true

    if [ -z "$target_model" ]; then
        log_error "  ✗ 未设置 X-Target-Model 头"
        success=false
    else
        log_info "  ✓ X-Target-Model: $target_model"
        if [ ! -z "$expected_model" ] && [ "$target_model" != "$expected_model" ]; then
            log_error "  ✗ 模型不匹配: 期望 $expected_model, 实际 $target_model"
            success=false
        fi
    fi

    if [ -z "$classification" ]; then
        log_error "  ✗ 未设置 X-Classification 头"
        success=false
    else
        log_info "  ✓ X-Classification: $classification"
    fi

    if [ -z "$confidence" ]; then
        log_warn "  ⚠ 未设置 X-Confidence 头"
    else
        log_info "  ✓ X-Confidence: $confidence"
    fi

    if [ -z "$method" ]; then
        log_warn "  ⚠ 未设置 X-Classification-Method 头"
    else
        log_info "  ✓ X-Classification-Method: $method"
    fi

    if [ "$success" = true ]; then
        log_info "  ✓ 测试通过"
        return 0
    else
        return 1
    fi
}

# 测试分类服务健康检查
test_classifier_health() {
    log_test "测试: 分类服务健康检查"

    # 检查端口
    if nc -z localhost $CLASSIFIER_PORT 2>/dev/null; then
        log_info "  ✓ 分类服务端口可访问"
    else
        log_error "  ✗ 分类服务端口不可访问"
        return 1
    fi

    # 测试 gRPC 连接
    python3 -c "
import grpc
import sys
sys.path.insert(0, 'src')
import classifier_pb2
import classifier_pb2_grpc

try:
    channel = grpc.insecure_channel('localhost:$CLASSIFIER_PORT')
    stub = classifier_pb2_grpc.SemanticClassifierServiceStub(channel)
    request = classifier_pb2.HealthCheckRequest(check_type='basic')
    response = stub.HealthCheck(request)
    print(f'  ✓ 状态: {response.status}')
    print(f'  ✓ 详细信息: {response.details}')
except Exception as e:
    print(f'  ✗ gRPC 连接失败: {e}')
    sys.exit(1)
"

    return $?
}

# 执行端到端测试
run_e2e_tests() {
    log_info "开始执行端到端测试..."

    local passed=0
    local failed=0

    # 测试1: 数学问题
    if test_request "数学问题分类与路由" \
        '[{"role": "user", "content": "求解方程 x^2 + 2x - 3 = 0"}]' \
        "math" \
        "qwen-math-7b"; then
        ((passed++))
    else
        ((failed++))
    fi

    # 测试2: 代码问题
    if test_request "代码问题分类与路由" \
        '[{"role": "user", "content": "写一个Python函数实现快速排序"}]' \
        "code" \
        "qwen-code-7b"; then
        ((passed++))
    else
        ((failed++))
    fi

    # 测试3: 医学问题
    if test_request "医学问题分类与路由" \
        '[{"role": "user", "content": "头痛的常见原因有哪些？"}]' \
        "medical" \
        "qwen-medical-7b"; then
        ((passed++))
    else
        ((failed++))
    fi

    # 测试4: 金融问题
    if test_request "金融问题分类与路由" \
        '[{"role": "user", "content": "如何计算投资回报率？"}]' \
        "finance" \
        "qwen-finance-7b"; then
        ((passed++))
    else
        ((failed++))
    fi

    # 测试5: 通用问题
    if test_request "通用问题分类与路由" \
        '[{"role": "user", "content": "今天天气怎么样？"}]' \
        "general" \
        "qwen-turbo"; then
        ((passed++))
    else
        ((failed++))
    fi

    echo
    log_info "=================================="
    log_info "  端到端测试总结"
    log_info "=================================="
    log_info "  通过: $passed"
    log_info "  失败: $failed"
    log_info "=================================="

    return $failed
}

# 清理资源
cleanup() {
    log_info "清理测试资源..."
    stop_classifier_service
    log_info "清理完成"
}

# 主函数
main() {
    log_info "=================================="
    log_info "  语义路由插件端到端测试"
    log_info "=================================="

    # 设置陷阱，确保退出时清理
    trap cleanup EXIT

    # 检查配置文件
    if [ ! -f "$TEST_CONFIG" ]; then
        log_error "测试配置文件不存在: $TEST_CONFIG"
        exit 1
    fi

    # 检查服务配置
    if [ ! -f "src/server.py" ]; then
        log_error "分类服务文件不存在: src/server.py"
        exit 1
    fi

    # 执行测试流程
    check_dependencies
    start_classifier_service
    test_classifier_health
    run_e2e_tests

    log_info "=================================="
    log_info "  测试完成"
    log_info "=================================="
}

# 运行主函数
main "$@"
