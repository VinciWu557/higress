# @Higress 挑战赛 智能路由方向数据集使用说明

**赛题背景**

本次竞赛要求基于 **Higress** 开发一个智能路由插件，实现对不同专业领域模型的精准路由。系统需要根据问题内容自动选择最适合的模型，在保证回答准确性的同时优化响应延时。

‍

**提供的 Mock 服务**

我们提供两个 Mock LLM 服务用于开发和测试：

- ​**训练数据集服务**​: `http://sem-router-train.higress.io`
- ​**验证数据集服务**​: `http://sem-router-verify.higress.io`

这些服务模拟真实的LLM后端，提供不同专业领域的模型和标准化的评分接口。

‍

**API 接口规范**

### 1. 兼容OpenAI的Chat接口: `/v1/chat/completions`

标准的OpenAI Chat Completions兼容接口，支持流式和非流式响应。

​**可用模型列表**：

- ​`qwen-max` （通用大模型，延时500ms）
- ​`qwen-math-32b`​, `qwen-math-7b`​, `qwen-math-3b` （数学专用模型）
- ​`qwen-code-32b`​, `qwen-code-7b`​, `qwen-code-3b` （代码专用模型）
- ​`qwen-medicine-32b`​, `qwen-medicine-7b`​, `qwen-medicine-3b` （医学专用模型）
- ​`qwen-writing-32b`​, `qwen-writing-7b`​, `qwen-writing-3b` （写作专用模型）

​**请求格式**：

```shell
curl -X POST http://sem-router-train.higress.io/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen-math-7b",
    "messages": [{"role": "user", "content": "求解方程 x^2 + 2x - 3 = 0"}],
    "stream": false
  }'
```

​**响应格式**：

```json
{
  "id": "mock-abc123",
  "created": 1234567890,
  "model": "qwen-math-7b",
  "object": "chat.completion",
  "choices": [{
    "index": 0,
    "message": {
      "role": "assistant",
      "content": "答案内容..."
    },
    "finish_reason": "stop"
  }]
}
```

‍

### 2. 答案评分接口: `/v1/evaluate`

​**重要**: 由于chat接口返回的是Mock数据，必须使用此接口来评估答案的正确性，不要使用其他评估方式。

​**请求格式**：

```json
{"question": "问题内容", "answer": "模型返回的完整答案"}
```

​**响应格式**：

```json
{"score": 0.8}  // 0-1之间的得分，-1表示无效问题或答案
```

​**使用示例**：

```shell
curl -X POST http://sem-router-train.higress.io/v1/evaluate \
  -H "Content-Type: application/json" \
  -d '{
    "question": "求解方程 x^2 + 2x - 3 = 0",
    "answer": "方程的解是 x = 1 或 x = -3"
  }'
```

‍

### 3. 获取问题数据集: `/questions`

获取用于训练或验证的问题列表。

​**请求**：

```shell
# 获取训练集问题（用于收集训练数据）
curl http://sem-router-train.higress.io/questions

# 获取验证集问题（用于最终测试）
curl http://sem-router-verify.higress.io/questions
```

​**响应格式**：

```json
{
  "questions": [
    {"id": "0000", "question": "开发一个PHP脚本用于终止MySQL连接"},
    {"id": "0001", "question": "头上长疙瘩的主要表现是什么？"},
    {"id": "0002", "question": "求解微分方程 dy/dx = x^2 + 1"},
    ...
  ]
}
```

‍

## 智能路由插件开发指南

### 第一步：实现数据收集功能

开发具备实时数据收集能力的智能路由插件：

#### 核心功能要求

- ​**数据收集模式**: 插件能够识别训练请求，在收到训练问题时自动调用所有可用模型
- ​**多模型调用**: 对同一问题依次调用所有模型（qwen-max、qwen-math-7b、qwen-code-7b、qwen-medicine-7b、qwen-writing-7b等）
- ​**实时评分**​: 对每个模型的答案调用`/v1/evaluate`接口获取准确性评分
- ​**数据存储**: 将问题、模型、答案、评分的映射关系存储为训练数据

#### 获取训练问题集

```shell
# 获取训练问题列表，用于数据收集
curl http://sem-router-train.higress.io/questions > training_questions.json
```

‍

### 第二步：通过网关收集训练数据

#### 2.1 启用数据收集模式

通过 Higress 网关实时收集训练数据，而不是直接调用API：

```shell
# 1. 部署启用数据收集模式的插件
kubectl apply -f semantic-router-plugin-training.yaml

# 2. 发送训练问题到网关，触发数据收集
cat training_questions.json | jq -r '.questions[].question' | while read question; do
  curl -X POST https://your-higress-gateway/v1/chat/completions \
    -H "Content-Type: application/json" \
    -H "X-Training-Mode: true" \
    -d "{\"messages\":[{\"role\":\"user\",\"content\":\"$question\"}]}"
done
```

#### 2.2 数据收集流程

支持插件配置开启数据收集

1. ​**多模型调用**: 依次调用所有配置的模型后端
2. ​**答案评分**​: 对每个模型的答案调用 `/v1/evaluate` 接口
3. ​**数据存储**​: 将 `question → model → score` 映射存储到训练数据集
4. ​**返回响应**: 可选择返回最佳模型的答案或收集状态

‍

### 第三步：训练路由模型

基于通过网关收集的数据训练分类器：

- ​**输入**: 问题文本特征
- ​**输出**: 最优模型选择
- ​**目标**: 最大化准确率 × 效率权重

‍

### 第四步：部署智能路由模式

切换插件到生产路由模式：

```shell
# 部署智能路由模式插件
kubectl apply -f semantic-router-plugin-production.yaml
```

插件核心功能：

1. ​**请求拦截**: 解析用户问题
2. ​**模型预测**: 调用训练好的路由模型
3. ​**请求转发**: 将请求路由到选定的后端模型
4. ​**性能监控**: 记录路由决策和响应指标

‍

### 第五步：验证和评估

#### 5.1 切换到验证环境

使用验证数据集测试智能路由系统：

```shell
# 1. 配置验证服务作为后端
# 修改插件配置，将后端指向验证服务
    endpoint: http://sem-router-verify.higress.io/v1/chat/completions
  # ... 其他模型配置

# 2. 获取验证问题集
curl http://sem-router-verify.higress.io/questions > verify_questions.json
```

#### 5.2 执行性能测试

通过Higress网关进行端到端测试：

```shell
# 发送验证问题，测试智能路由效果
cat verify_questions.json | jq -r '.questions[].question' | while read question; do
  start_time=$(date +%s%3N)

  # 通过网关发送请求，插件自动选择最佳模型
  response=$(curl -s -X POST https://your-higress-gateway/v1/chat/completions \
    -H "Content-Type: application/json" \
    -d "{\"messages\":[{\"role\":\"user\",\"content\":\"$question\"}]}")

  end_time=$(date +%s%3N)
  elapsed=$((end_time - start_time))

  answer=$(echo "$response" | jq -r '.choices[0].message.content')

  # 调用验证服务评分
  score=$(curl -s -X POST http://sem-router-verify.higress.io/v1/evaluate \
    -H "Content-Type: application/json" \
    -d "{\"question\":\"$question\",\"answer\":\"$answer\"}" \
    | jq -r '.score')

  echo "Question: $question"
  echo "Response time: ${elapsed}ms, Score: $score"
done
```

‍

#### 5.3 实时监控 （建议）

插件最好提供实时监控指标：

```shell
# 查看路由决策统计
curl https://your-higress-gateway/metrics | grep semantic_router

# 关键指标：
# - semantic_router_requests_total{model="qwen-math-7b"}
# - semantic_router_response_time_histogram
# - semantic_router_accuracy_score
```

‍

## 评估标准

### 核心指标

1. ​**准确率**​: 基于`/v1/evaluate`接口的评分结果
2. ​**响应延时**: 端到端请求处理时间
3. ​**资源效率**: 高性能模型的合理使用比例

### 测试方法

- 使用验证数据集进行标准化测试
- 计算所有问题的平均准确率和响应时间
- 评估不同类型问题（数学、代码、医学、写作）的专项表现

## 开发提示

### 插件实现要点

1. ​**数据收集模式**:

    - 在数据收集模式下，依次调用所有模型并收集评分
    - 存储训练数据供后续模型训练使用
2. ​**路由决策逻辑**:

    - 解析用户问题，提取文本特征
    - 调用训练好的分类模型预测最佳后端
3. ​**性能优化**:

    - 异步调用evaluate接口避免阻塞主请求
4. ​**评分机制**:

    - **必须**使用提供的`/v1/evaluate`接口进行评分
    - 该接口已内置模型-问题匹配度算法
    - 评分结果作为训练标签和性能指标

### 架构建议

- ​**训练阶段**: 插件作为数据收集器，通过网关实时收集多模型性能数据
- ​**推理阶段**: 插件作为智能路由器，根据问题特征选择最优模型
- ​**监控阶段**: 持续收集路由效果反馈，支持模型在线更新
