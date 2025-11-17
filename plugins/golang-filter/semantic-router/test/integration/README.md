# 语义路由插件集成测试

## 概述

本目录包含语义路由插件的集成测试，用于验证阶段一基础框架的核心功能：
- HTTP 请求拦截
- OpenAI 格式 Prompt 提取
- 路由决策和头部设置
- 插件配置解析

## 目录结构

```
test/integration/
├── README.md          # 本文档
└── test.sh           # 自动化测试脚本

../test-config.yaml   # 测试配置文件
```

## 测试场景

测试脚本覆盖以下场景：

### 1. 数学问题分类
- **输入**: "求解方程 x^2 + 2x - 3 = 0"
- **期望类别**: math
- **期望路由**: qwen-math-7b

### 2. 代码问题分类
- **输入**: "写一个Python函数实现快速排序"
- **期望类别**: code
- **期望路由**: qwen-code-7b

### 3. 医学问题分类
- **输入**: "头痛的常见原因有哪些？"
- **期望类别**: medical
- **期望路由**: qwen-medical-7b

### 4. 金融问题分类
- **输入**: "如何计算投资回报率？"
- **期望类别**: finance
- **期望路由**: qwen-finance-7b

### 5. 通用问题分类
- **输入**: "今天天气怎么样？"
- **期望类别**: general
- **期望路由**: qwen-turbo

## 前置条件

### 1. 环境依赖
- `bash` shell
- `curl` 命令行工具
- `python3` (用于启动 mock 分类服务)
- 可选: `jq` (JSON 解析美化)

### 2. Higress Gateway
确保 Higress Gateway 已启动并配置了语义路由插件：
- 监听端口: `8001` (默认，可通过 `GATEWAY_URL` 环境变量自定义)
- 插件配置文件: `test-config.yaml`

### 3. 分类服务
测试脚本会自动启动一个 mock 分类服务，监听端口 `50051`。
生产环境中，应配置真实的分类服务地址。

## 运行测试

### 基本用法

```bash
# 进入项目根目录
cd /Users/vinci/workspace/higress/plugins/golang-filter/semantic-router

# 赋予执行权限
chmod +x test/integration/test.sh

# 运行测试
./test/integration/test.sh
```

### 自定义配置

```bash
# 自定义 Gateway URL
export GATEWAY_URL=http://localhost:8080
./test/integration/test.sh

# 自定义 Mock 服务端口
export MOCK_CLASSIFIER_PORT=50052
./test/integration/test.sh

# 同时自定义多个参数
export GATEWAY_URL=http://localhost:8080
export MOCK_CLASSIFIER_PORT=50052
./test/integration/test.sh
```

## 测试流程

1. **依赖检查**
   - 验证 `curl`、`python3` 等工具可用

2. **启动 Mock 服务**
   - 在后台启动 Python 实现的分类服务
   - 提供基本的关键词分类功能

3. **执行测试用例**
   - 发送 HTTP POST 请求到 Gateway
   - 验证响应中的路由头

4. **验证结果**
   - 检查 HTTP 状态码 (应为 200)
   - 验证路由头设置:
     - `X-Target-Model`: 目标模型名称
     - `X-Classification`: 分类类别
     - `X-Confidence`: 置信度
     - `X-Classification-Method`: 分类方法

5. **清理资源**
   - 停止 Mock 服务
   - 删除临时文件

## 验证点

### ✅ 成功标志

测试通过时，您将看到：
```
[INFO] 测试: 数学问题分类
[INFO]   ✓ 路由头设置成功: X-Target-Model=qwen-math-7b, X-Classification=math, X-Confidence=0.850
[INFO] 所有测试用例执行完成
[INFO] ==================================
[INFO]   测试完成 ✓
[INFO] ==================================
```

### ❌ 失败标志

常见失败场景及解决方法：

1. **HTTP 状态码错误**
   ```
   [ERROR] HTTP状态码错误: 404
   ```
   - **原因**: Gateway 未启动或 URL 错误
   - **解决**: 确认 Gateway 运行在指定端口

2. **未设置路由头**
   ```
   [ERROR] 未设置 X-Target-Model 头
   ```
   - **原因**: 插件未正确加载或配置
   - **解决**: 检查插件配置和加载状态

3. **Mock 服务启动失败**
   ```
   [ERROR] curl 未安装
   ```
   - **原因**: 缺少必要工具
   - **解决**: 安装缺失的依赖

## 高级用法

### 手动测试单个场景

```bash
# 发送数学问题测试
curl -s -i -X POST http://localhost:8001/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-3.5-turbo",
    "messages": [
      {"role": "user", "content": "求解方程 x^2 + 2x - 3 = 0"}
    ]
  }' | grep -i "X-"
```

### 调试模式

在测试脚本中添加调试信息：
```bash
# 在 test.sh 中添加
set -x  # 开启命令回显
```

或直接查看详细响应：
```bash
curl -v -X POST http://localhost:8001/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"测试"}]}'
```

## 故障排除

### 问题1: 测试脚本无法执行
```bash
# 解决：添加执行权限
chmod +x test/integration/test.sh
```

### 问题2: Gateway 连接失败
```bash
# 检查 Gateway 状态
curl -I http://localhost:8001/health

# 检查端口占用
lsof -i :8001
```

### 问题3: Mock 服务冲突
```bash
# 停止占用端口的进程
lsof -ti:50051 | xargs kill -9

# 或使用自定义端口
export MOCK_CLASSIFIER_PORT=50052
```

### 问题4: 插件配置错误

1. 检查配置文件语法:
   ```bash
   # YAML 语法检查（需要安装 yamllint）
   yamllint test-config.yaml
   ```

2. 查看插件日志:
   ```bash
   # 查看 Higress Gateway 日志
   kubectl logs -f deployment/higress-gateway -n higress-system
   ```

## 扩展测试

### 添加新测试用例

在 `test.sh` 的 `run_tests()` 函数中添加新的测试:

```bash
# 示例：添加历史问题测试
test_request "历史问题分类" \
  '[{"role": "user", "content": "唐朝是什么时候建立的？"}]' \
  "history"
```

### 集成真实分类服务

修改测试脚本，连接真实的分类服务而不是 Mock:

```bash
# 在 test.sh 中注释掉 start_mock_classifier 调用
# 直接使用配置的分类服务
```

## 注意事项

1. **测试环境隔离**: 建议在测试环境中运行，避免影响生产流量
2. **资源清理**: 测试结束后会自动清理，但可以手动调用 `cleanup`
3. **并发限制**: 当前测试为串行执行，避免对系统造成压力
4. **数据隐私**: 测试请求不包含敏感信息

## 下一步

完成基础框架测试后，建议继续：
- 阶段二: 分类服务开发
- 阶段三: 模型训练
- 阶段四: 数据飞轮实现

## 参考

- [阶段一文档](../../docs/plan/02-阶段一-基础框架.md)
- [Higress 官方文档](https://higress.io/)
- [语义路由设计文档](../../docs/vLLM%20Semantic%20Router/@semantic-router%20系统架构.md)
