# @semantic-router 模型评估

当然可以。下面是去掉所有 emoji、保持正式技术文档风格的中文翻译与注释版。

---

# 模型性能评估（Model Performance Evaluation）

## 为什么要评估 (Why evaluate?)

模型评估让路由决策数据化。通过在 MMLU-Pro（并通过 ARC 进行快速 sanity check）中测量每个类别的准确率，你可以：

- **为每个类别选择最合适的模型，并将其排名写入** **​`categories.model_scores`​**
- 根据整体表现选择合理的 `default_model`
- 判断在延迟/成本权衡下何时启用 CoT（Chain-of-Thought）提示
- 在模型、提示词或参数变化时捕获性能回退（regression）
- 保证更改是可复现、可审计的（用于 CI 和版本发布）

简而言之：  
评估将经验判断转化为可量化信号，使路由更高质量、更高效、更可靠。

---

本指南介绍如何通过 vLLM 兼容的 OpenAI 接口自动化评估模型（包括 MMLU-Pro 和 ARC Challenge），并基于结果自动生成性能导向的路由配置，更新配置文件中的 `categories.model_scores`。

代码路径：`/src/training/model_eval`

---

## 评估流程总览

1. 模型评估

    - 每类别准确率（MMLU-Pro）
    - 整体准确率（ARC Challenge）
2. 可视化结果

    - 条形图、热力图（各类别准确率）
3. 生成新的配置文件 (`config.yaml`)

    - 按准确率排序的 `categories.model_scores`
    - 设置 `default_model`（全局最优）
    - 保留或调整推理配置（use\_reasoning、reasoning\_effort）

---

## 前置条件 (Prerequisites)

### 运行 vLLM 兼容的 OpenAI Endpoint

在本地启动一个或多个模型服务：

```bash
# 启动 phi-4 模型
vllm serve microsoft/phi-4 --port 11434 --served_model_name phi4

# 启动 Qwen 模型
vllm serve Qwen/Qwen3-0.6B --port 11435 --served_model_name qwen3-0.6B
```

Endpoint URL 格式：`http://localhost:8000/v1`  
如有需要，可设置 API Key。

---

### 安装依赖

```bash
cd /src/training/model_eval
pip install -r requirements.txt
```

---

### 配置要求

​`--served-model-name`​ 必须与 `config/config.yaml` 中的模型名一致：

```yaml
vllm_endpoints:
  - name: "endpoint1"           # vLLM 模型服务实例名称
    address: "127.0.0.1"        # 本地或远程服务地址
    port: 11434                 # 对应端口（必须与 serve 命令一致）

  - name: "endpoint2"           # 第二个模型服务实例
    address: "127.0.0.1"
    port: 11435

model_config:
  "phi4":                       # 模型名称（必须与 vllm serve 参数 --served_model_name 相同）
    description: "Small reasoning model for business tasks"
    max_tokens: 2048
    temperature: 0.2
    cost_per_1k_tokens: 0.0002
  "qwen3-0.6B":                 # 第二个模型的配置
    description: "Lightweight general-purpose reasoning model"
    max_tokens: 2048
    temperature: 0.5
    cost_per_1k_tokens: 0.0003

```

建议：  
确保配置文件 `config/config.yaml`​ 中的 `vllm_endpoints[].models`​ 与 `model_config` 定义一致。

---

## MMLU-Pro 评估

脚本位置：`mmlu_pro_vllm_eval.py`

### 示例命令

```bash
# 评估单模型（每类10条）
python mmlu_pro_vllm_eval.py \
  --endpoint http://localhost:11434/v1 \
  --models phi4 \
  --samples-per-category 10

python mmlu_pro_vllm_eval.py \
  --endpoint http://localhost:11435/v1 \
  --models qwen3-0.6B \
  --samples-per-category 10

# 启用 CoT 提示（结果保存至 *_cot 文件夹）
python mmlu_pro_vllm_eval.py \
  --endpoint http://localhost:11435/v1 \
  --models qwen3-0.6B \
  --samples-per-category 10 \
  --use-cot

# 批量评估多个模型
python mmlu_pro_vllm_eval.py \
  --endpoint http://localhost:8801/v1 \
  --models qwen3-0.6B,phi4 \
  --samples-per-category 10
```

---

### 参数说明

|参数|含义|
| ------------| ----------------------------|
|​`--endpoint`|vLLM 服务地址|
|​`--models`|模型名（可用逗号分隔）|
|​`--categories`|限定评估类别（默认全评估）|
|​`--samples-per-category`|每类采样数量|
|​`--use-cot`|启用 Chain-of-Thought|
|​`--concurrent-requests`|并发请求数|
|​`--output-dir`|输出目录（默认`results/`）|
|​`--max-tokens`​,`--temperature`​,`--seed`|控制生成参数与复现性|

---

### 输出结果结构

```
results/Model_Name_(direct|cot)/
 ├── detailed_results.csv      # 每题结果
 ├── analysis.json             # 汇总指标
 ├── summary.json              # 摘要指标
 └── mmlu_pro_vllm_eval.txt    # 提示与回答日志
```

模型名中 `/`​ 会被替换为 `_`​（如 `Qwen/Qwen3-0.6B → Qwen_Qwen3-0.6B_direct`）。  
只统计成功响应的结果。

---

## ARC Challenge 评估（可选）

脚本位置：`arc_challenge_vllm_eval.py`

### 示例命令

```bash
python arc_challenge_vllm_eval.py \
  --endpoint http://localhost:8801/v1 \
  --models qwen3-0.6B,phi4 \
  --output-dir arc_results
```

|参数|含义|
| ----------| ---------------------|
|​`--samples`|抽样数量（默认 20）|
|其他参数|与 MMLU-Pro 相同|

输出文件同上，包括：

- ​`detailed_results.csv`
- ​`analysis.json`
- ​`summary.json`
- ​`arc_challenge_vllm_eval.txt`

说明：ARC 结果用于 sanity check，不会直接写入 `categories.model_scores`。

---

## 可视化评估结果

脚本位置：`plot_category_accuracies.py`

### 示例命令

```bash
# 生成柱状图
python plot_category_accuracies.py \
  --results-dir results \
  --plot-type bar \
  --output-file results/bar.png

# 生成热力图
python plot_category_accuracies.py \
  --results-dir results \
  --plot-type heatmap \
  --output-file results/heatmap.png

# 使用示例数据生成图表（测试用）
python src/training/model_eval/plot_category_accuracies.py \
  --sample-data \
  --plot-type heatmap \
  --output-file results/category_accuracies.png
```

|参数|含义|
| ------| --------------------------|
|​`--results-dir`|结果文件目录|
|​`--plot-type`|图类型（bar 或 heatmap）|
|​`--output-file`|输出图路径|
|​`--sample-data`|使用示例数据测试|

说明：  
该脚本读取 `analysis.json`​，计算各类别平均准确率并绘制图表。  
若存在 `direct`​ 与 `cot` 版本，将分别绘制。

---

## 生成性能导向的路由配置

脚本位置：`result_to_config.py`

### 示例命令

```bash
# 从评估结果生成配置（不会覆盖原文件）
python src/training/model_eval/result_to_config.py \
  --results-dir results \
  --output-file config/config.eval.yaml

# 自定义语义缓存阈值
python src/training/model_eval/result_to_config.py \
  --results-dir results \
  --output-file config/config.eval.yaml \
  --similarity-threshold 0.85

# 指定结果路径生成
python src/training/model_eval/result_to_config.py \
  --results-dir results/mmlu_run_2025_09_10 \
  --output-file config/config.eval.yaml
```

|参数|含义|
| ------| ------------------------|
|​`--results-dir`|存放分析结果的目录|
|​`--output-file`|输出配置路径|
|​`--similarity-threshold`|设置语义缓存相似度阈值|

---

### 工作原理

脚本执行步骤：

1. 读取所有 `analysis.json`
2. 提取 `category_accuracy`
3. 构造新配置结构：

    - ​`categories.model_scores`: 模型按准确率降序排列
    - ​`default_model`: 平均表现最优模型
    - 自动设置 `use_reasoning`​、`reasoning_effort`（数学/物理等为高推理）

生成示例：

```yaml
categories:
  - name: business                  # 类别名称
    use_reasoning: false            # 是否使用推理模式（一般任务关闭）
    reasoning_effort: low           # 推理复杂度（low/medium/high）
    model_scores:                   # 各模型在该类别的准确率排名
      - model: phi4
        score: 0.2
      - model: qwen3-0.6B
        score: 0.0

  - name: law
    use_reasoning: medium
    reasoning_effort: medium
    model_scores:
      - model: phi4
        score: 0.8
      - model: qwen3-0.6B
        score: 0.2

default_reasoning_effort: medium    # 默认推理等级
default_model: phi4                 # 全局默认模型（平均准确率最高）
```

---

### 注意事项

- 仅适用于 MMLU-Pro 评估结果。
- 可输出到临时文件（如 `config/config.eval.yaml`），避免覆盖正式配置。
- 若生产配置包含自定义字段（价格、端点等），请手动合并新的 `model_scores`​ 与 `default_model`。

---

## 完整配置示例（`config.eval.yaml`）

```yaml
bert_model:
  model_id: sentence-transformers/all-MiniLM-L12-v2   # 用于语义相似度计算的嵌入模型
  threshold: 0.6                                      # 相似度阈值
  use_cpu: true                                       # 是否使用 CPU 运行

semantic_cache:
  enabled: true                                       # 启用语义缓存
  similarity_threshold: 0.85                          # 命中阈值
  max_entries: 1000                                   # 最大缓存条数
  ttl_seconds: 3600                                   # 缓存过期时间（秒）

tools:
  enabled: true                                       # 是否启用工具选择
  top_k: 3                                            # 每次选取最相关的 3 个工具
  similarity_threshold: 0.2                           # 工具匹配相似度阈值
  tools_db_path: config/tools_db.json                 # 工具数据库文件路径
  fallback_to_empty: true                             # 无匹配时是否返回空工具集

prompt_guard:
  enabled: true                                       # 启用越权检测（Jailbreak 检测）
  use_modernbert: true                                # 使用 ModernBERT 作为检测模型
  model_id: models/jailbreak_classifier_modernbert-base_model
  threshold: 0.7                                      # 风险阈值（越高越严格）
  use_cpu: true                                       # 是否在 CPU 上运行
  jailbreak_mapping_path: models/jailbreak_classifier_modernbert-base_model/jailbreak_type_mapping.json

classifier:
  category_model:
    model_id: models/category_classifier_modernbert-base_model  # 语义分类模型
    threshold: 0.6
  pii_model:
    model_id: models/pii_classifier_modernbert-base_presidio_token_model # PII 检测模型
    threshold: 0.7

categories:
- name: business
  use_reasoning: false
  reasoning_effort: low
  model_scores:
  - model: phi4
    score: 0.2
  - model: qwen3-0.6B
    score: 0.0
- name: law
  use_reasoning: medium
  reasoning_effort: medium
  model_scores:
  - model: phi4
    score: 0.8
  - model: qwen3-0.6B
    score: 0.2
- name: engineering
  use_reasoning: true
  reasoning_effort: high
  model_scores:
  - model: phi4
    score: 0.6
  - model: qwen3-0.6B
    score: 0.2

default_reasoning_effort: medium
default_model: phi4
```

|阶段|模块|功能|
| ------| ---------------------| --------------------------------------------|
|1|​`ExtProc`过滤器|拦截 HTTP 请求，将请求体发给外部 gRPC 服务|
|2|​`OpenAIRouter.handleRequestBody()`|解析请求，调用分类模型识别类别|
|3|​`Router.selectModelEndpoint()`|根据`categories.model_scores`查找最优模型|
|4|​`Router`设置 HTTP 头部|添加`x-gateway-destination-endpoint`​、`x-selected-model`​、`x-routing-confidence`|
|5|Envoy Router Filter|根据头部匹配相应的集群（cluster）进行转发|

```python
def selectModelEndpoint(self, classification):
    # classification.category 是分类器返回的类别，例如 "mathematics"
    category = classification.Category
    confidence = classification.Confidence

    # 从配置中加载类别对应模型及评分
    if category in self.Config.Categories:
        models = self.Config.Categories[category].ModelScores
    else:
        # 未知类别使用默认模型
        return self.Config.DefaultModel

    # 选出得分最高的模型
    best_model = max(models.items(), key=lambda x: x[1])[0]
    score = models[best_model]

    # 如果分类置信度较低，使用默认模型以保证稳定性
    if confidence < 0.6:
        return self.Config.DefaultModel

    return best_model

```

‍

# 如何使用评估结果？

系统读取后会在内存中形成映射：

```python
{
  "mathematics": {"qwen-math-7b": 0.942, "gpt-4-turbo": 0.936, "modernbert-base": 0.915},
  "law": {"phi4": 0.881, "gpt-3.5-turbo": 0.875},
  "default": "gpt-4-turbo"
}
```

---

### 决策逻辑实现（Go 伪代码 / Python 等价逻辑）

在 ExtProc 服务（`OpenAIRouter`​）中，  
决策逻辑大致如下（来自 `handleRequestBody()`​ → `selectModelEndpoint()`）：

```python
def selectModelEndpoint(self, classification):
    # classification.category 是分类器返回的类别，例如 "mathematics"
    category = classification.Category
    confidence = classification.Confidence

    # 从配置中加载类别对应模型及评分
    if category in self.Config.Categories:
        models = self.Config.Categories[category].ModelScores
    else:
        # 未知类别使用默认模型
        return self.Config.DefaultModel

    # 选出得分最高的模型
    best_model = max(models.items(), key=lambda x: x[1])[0]
    score = models[best_model]

    # 如果分类置信度较低，使用默认模型以保证稳定性
    if confidence < 0.6:
        return self.Config.DefaultModel

    return best_model
```

---

### Envoy 侧如何使用该决策结果

当 `OpenAIRouter` 返回决策后，会生成如下响应（即发回 Envoy 的外部处理结果）：

```json
{
  "response": {
    "request_body": {
      "response": {
        "body_mutation": {
          "mutation": {
            "body": "<modified OpenAI request>"
          }
        }
      }
    }
  },
  "mode_override": {
    "request_header_mode": "SEND",
    "response_header_mode": "SEND"
  },
  "dynamic_metadata": {
    "classification_category": "mathematics",
    "selected_model": "qwen-math-7b",
    "routing_confidence": 0.942
  }
}
```

Envoy 的 **ExtProc filter** 会将这些动态元数据写入 HTTP Header：

```yaml
headers_to_add:
  x-selected-model: qwen-math-7b
  x-routing-confidence: 0.942
  x-gateway-destination-endpoint: endpoint_math
```

然后，Envoy 的路由配置（`route_config`）中有匹配规则：

```yaml
routes:
  - match:
      prefix: "/"
      headers:
        - name: "x-gateway-destination-endpoint"
          string_match:
            exact: "endpoint_math"
    route:
      cluster: math_model_cluster
```

Envoy 读取这些头部值后，将请求转发到对应的后端模型集群。

---

### 在系统中它的三种典型用途

#### 1. 模型选择（核心）

- 按照每个类别的最高得分模型路由请求；
- 若置信度较低或类别未知，使用 `default_model`；
- 可扩展为“加权采样”（未来支持多模型投票）。

#### 2. 推理策略选择（use\_reasoning / reasoning\_effort）

- 根据配置决定是否启用推理增强（例如 CoT / ReAct）；
- 高推理类别（数学、工程）会在调用时插入提示模板，如：

  ```
  "Let's think step by step."
  ```

#### 3. 持续性能监控

- ​`model_scores` 可被 CI/CD 流水线更新；
- 在每次模型或提示版本变更后，重新跑评估脚本；
- 若检测到得分下降（回退），会发出警告或阻止上线。

---

### 与自动化评估流程的集成

评估脚本 `/src/training/model_eval/result_to_config.py`​ 会根据 `analysis.json`​ 生成新的 `categories.model_scores`：

```python
# 伪代码
for category, acc_by_model in category_accuracy.items():
    sorted_models = sorted(acc_by_model.items(), key=lambda x: x[1], reverse=True)
    config["categories"].append({
        "name": category,
        "model_scores": [{"model": m, "score": s} for m, s in sorted_models]
    })
```

这意味着评估结果和线上配置是自动闭环的：

> 测试 → 评估 → 更新配置 → 部署 → 新路由决策。

---

### 总结

|功能|描述|
| ------| ---------------------------------|
|**配置来源**|自动评估生成 (`result_to_config.py`)|
|**加载位置**|ExtProc 服务启动时读取|
|**用途 1**|依据分类结果选择最优模型|
|**用途 2**|影响`use_reasoning`与提示模板|
|**用途 3**|在 Envoy 动态路由时标记目标集群|
|**用途 4**|用作性能追踪与版本控制基线|

---

‍
