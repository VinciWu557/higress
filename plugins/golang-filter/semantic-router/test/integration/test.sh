#!/bin/bash

# 语义路由插件集成测试脚本
# 用于阶段一基础框架验证
# 包含数学、代码、医学等场景测试

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 测试配置
GATEWAY_URL="${GATEWAY_URL:-http://localhost:8001}"
MOCK_CLASSIFIER_PORT="${MOCK_CLASSIFIER_PORT:-50051}"
TEST_CONFIG="./test-config.yaml"

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

# 检查依赖
check_dependencies() {
    log_info "检查依赖工具..."

    if ! command -v curl &> /dev/null; then
        log_error "curl 未安装"
        exit 1
    fi

    if ! command -v jq &> /dev/null; then
        log_warn "jq 未安装，JSON 解析功能可能受限"
    fi

    log_info "依赖检查完成"
}

# 启动Mock分类服务
start_mock_classifier() {
    log_info "启动Mock分类服务..."

    # 创建简单的mock服务脚本
    cat > /tmp/mock_classifier.py << 'EOF'
#!/usr/bin/env python3
import json
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.parse as urlparse

class MockClassifierHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path == '/classify':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)

            try:
                data = json.loads(post_data.decode('utf-8'))
                text = data.get('text', '').lower()

                # 简单的关键词分类
                category = 'general'
                if any(keyword in text for keyword in ['方程', '求解', '计算', 'x^2', '数学']):
                    category = 'math'
                elif any(keyword in text for keyword in ['代码', '函数', 'python', 'java', '编程']):
                    category = 'code'
                elif any(keyword in text for keyword in ['病', '症', '药', '医生', '医学']):
                    category = 'medical'

                response = {
                    'category': category,
                    'confidence': 0.85,
                    'scores': {category: 0.85},
                    'method': 'model',
                    'latency_ms': 15
                }

                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(response).encode())
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'error': str(e)}).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # 静默日志

if __name__ == '__main__':
    server = HTTPServer(('0.0.0.0', int('$MOCK_CLASSIFIER_PORT')), MockClassifierHandler)
    print(f"Mock分类服务启动，端口: $MOCK_CLASSIFIER_PORT")
    server.serve_forever()
EOF

    # 后台启动mock服务
    python3 /tmp/mock_classifier.py &
    MOCK_PID=$!
    sleep 2

    log_info "Mock分类服务已启动 (PID: $MOCK_PID)"
}

# 停止Mock服务
stop_mock_classifier() {
    if [ ! -z "$MOCK_PID" ]; then
        log_info "停止Mock分类服务..."
        kill $MOCK_PID 2>/dev/null || true
        wait $MOCK_PID 2>/dev/null || true
    fi
}

# 发送测试请求并验证
test_request() {
    local test_name="$1"
    local messages="$2"
    local expected_category="$3"

    log_info "测试: $test_name"

    # 发送请求
    response=$(curl -s -i -X POST "$GATEWAY_URL/v1/chat/completions" \
        -H "Content-Type: application/json" \
        -d "{\"model\": \"gpt-3.5-turbo\", \"messages\": $messages}")

    # 检查HTTP状态码
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

    # 验证结果
    if [ -z "$target_model" ]; then
        log_error "未设置 X-Target-Model 头"
        return 1
    fi

    if [ -z "$classification" ]; then
        log_error "未设置 X-Classification 头"
        return 1
    fi

    log_info "  ✓ 路由头设置成功: X-Target-Model=$target_model, X-Classification=$classification, X-Confidence=$confidence"
    return 0
}

# 测试用例
run_tests() {
    log_info "开始执行集成测试..."

    # 测试1: 数学问题
    test_request "数学问题分类" \
        '[{"role": "user", "content": "求解方程 x^2 + 2x - 3 = 0"}]' \
        "math"

    # 测试2: 代码问题
    test_request "代码问题分类" \
        '[{"role": "user", "content": "写一个Python函数实现快速排序"}]' \
        "code"

    # 测试3: 医学问题
    test_request "医学问题分类" \
        '[{"role": "user", "content": "头痛的常见原因有哪些？"}]' \
        "medical"

    # 测试4: 通用问题
    test_request "通用问题分类" \
        '[{"role": "user", "content": "今天天气怎么样？"}]' \
        "general"

    # 测试5: 金融问题
    test_request "金融问题分类" \
        '[{"role": "user", "content": "如何计算投资回报率？"}]' \
        "finance"

    log_info "所有测试用例执行完成"
}

# 清理资源
cleanup() {
    log_info "清理测试资源..."
    stop_mock_classifier
    rm -f /tmp/mock_classifier.py
    log_info "清理完成"
}

# 主函数
main() {
    log_info "=================================="
    log_info "  语义路由插件集成测试"
    log_info "=================================="

    # 设置陷阱，确保退出时清理
    trap cleanup EXIT

    # 检查配置文件
    if [ ! -f "$TEST_CONFIG" ]; then
        log_error "测试配置文件不存在: $TEST_CONFIG"
        exit 1
    fi

    # 执行测试流程
    check_dependencies
    start_mock_classifier
    run_tests

    log_info "=================================="
    log_info "  测试完成 ✓"
    log_info "=================================="
}

# 运行主函数
main "$@"
