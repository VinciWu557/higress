# @semantic-router 路由实现细节

本文档详细介绍了语义路由器（Semantic Router）的核心路由算法、分类逻辑和实现细节。

### 分类流程

#### 多阶段分类架构

![image](assets/image-20251026110525-pqhf9t0.png)

这套系统在一次请求中使用多个轻量模型（主要是 **ModernBERT** 家族）实现“并行安全检测 + 语义分类 + 决策路由”，从而保证：

- ​**高准确率**（精细分类）
- ​**高安全性**（隐私保护 + Jailbreak 防御）
- ​**高效率**（模型轻量化、并行推理）

‍

 **🧩 阶段 1：Text Preprocessing**

**输入：**  用户原始问题（User Query）  
**处理：**

- 分词 (Tokenization)
- 去除噪声（空格、标点、表情符号）
- 标准化格式（统一语言、符号）

➡️ 输出：干净的 token 序列，输入到后续分类模型。

‍

 **⚙️ 阶段 2：Parallel Classification （并行分类）**

系统会同时启动多个轻量模型执行独立的检测任务：

|模块|模型类型|功能|
| ------| ------------------------------------| ------------------------------------------------------------|
|🧩**PII Detector**|ModernBERT (Token Classification)|检测是否包含个人敏感信息（如身份证号、手机号等）|
|🧩**Jailbreak Guard**|ModernBERT (Binary Classification)|检测用户是否尝试绕过安全策略（例如 prompt 注入、越权请求）|
|🧩**Category Classifier**|ModernBERT (Multi-Class, 10 分类)|判断问题语义类别（数学、代码、医学、写作、通用等）|

这些模型在 GPU/CPU 上并行推理，大大降低整体延迟。

‍

 **🔒 阶段 3：Security Gate （安全门控）**

- 聚合来自 **PII Detector** 和 **Jailbreak Guard** 的结果；
- 如果检测到违规（PII 泄露或越权意图） → ​**阻断请求**；
- 否则允许通过到下一阶段。

🧩 输出结果：

- **Pass** → 进入路由决策阶段；
- **Block** → 直接生成 “Security Block Response”。

‍

 **🧮 阶段 4：Routing Decision Engine**

对于通过安全检查的请求：

- 使用 **Category Classifier** 的输出类别 + 置信度；
- 输入到 ​**Routing Decision Engine**（一个轻量逻辑模型）；
- 动态选择最优模型端点（例如：

  - Math → `qwen-math-7b`
  - Code → `qwen-code-7b`
  - Medicine → `qwen-medicine-7b`）。

‍

#### 实现细节

```go
// ===========================================================
// 🧠 分类模块：CategoryClassifier
// ===========================================================

// CategoryClassifier 负责使用轻量语义模型（如 ModernBERT）
// 对用户输入进行多类别分类，例如：数学、代码、写作、医学、闲聊等。
type CategoryClassifier struct {
    model                *ModernBERTModel        // 轻量分类模型（基于 BERT）
    tokenizer            *ModernBERTTokenizer    // 分词器，将文本转为 token ID
    labelMapping         map[int]string          // 类别索引 → 类别名称
    confidenceThreshold  float64                 // 分类置信度阈值
}

// ClassifyIntent 对输入 query 执行语义分类并输出结果
func (cc *CategoryClassifier) ClassifyIntent(query string) (*Classification, error) {
    // 记录开始时间（用于性能指标）
    start := time.Now()

    // 1️⃣ 文本分词（tokenization）
    // 将自然语言转化为 token 序列，输入到 BERT 模型
	// ["请", "写", "一个", "Python", "函数"]
    tokens := cc.tokenizer.Tokenize(query)
    
    // 2️⃣ 模型前向推理（inference）
    // 返回 logits（每个类别的原始得分）
	// [2.3, 0.4, 1.1, 5.6, 0.2]
    logits, err := cc.model.Forward(tokens)
    if err != nil {
        return nil, err
    }
    
    // 3️⃣ 计算 softmax 概率分布
	// [0.03, 0.01, 0.04, 0.90, 0.02]
    probabilities := softmax(logits)
    
    // 4️⃣ 找出概率最高的类别（argmax）
    maxIdx, maxProb := argmax(probabilities)
    category := cc.labelMapping[maxIdx]  // 例如 index=2 → “math”
    
    // 5️⃣ 构造分类结果对象
    return &Classification{
        Category:       category,           // 分类类别
        Confidence:     maxProb,            // 分类置信度
        Probabilities:  probabilities,      // 完整概率分布（用于分析）
        ProcessingTime: time.Since(start),  // 推理耗时
    }, nil
}

```

‍

### 语义缓存实现

#### 缓存架构

```go
// ===============================================================
// 🧠 Semantic Caching Implementation - 语义缓存系统实现
// ===============================================================

// SemanticCache 是语义缓存的核心结构体。
// 它存储历史请求、响应及其语义向量（embedding）。
type SemanticCache struct {
    entries             []CacheEntry     // 缓存条目列表
    mu                  sync.RWMutex     // 读写锁（支持高并发安全访问）
    similarityThreshold float32          // 相似度阈值（超过该值才认为匹配）
    maxEntries          int              // 最大缓存条目数量（LRU 或 FIFO 管理）
    ttlSeconds          int              // 条目过期时间（秒）
    enabled             bool             // 是否启用缓存功能
}

// CacheEntry 代表缓存中的一条数据记录。
// 包含请求、响应、语义向量及元信息。
type CacheEntry struct {
    RequestBody  []byte       // 原始请求体（用于重放或调试）
    ResponseBody []byte       // 模型响应体（缓存目标）
    Model        string       // 对应使用的模型名称
    Query        string       // 用户输入文本（原始 query）
    Embedding    []float32    // 语义向量（512维或自定义维度）
    Timestamp    time.Time    // 缓存时间戳（用于 TTL 过期判断）
}

// ===============================================================
// 🔍 FindSimilar：在缓存中查找语义相似的请求
// ===============================================================
func (c *SemanticCache) FindSimilar(model string, query string) ([]byte, bool, error) {
    // 1️⃣ 缓存功能关闭时直接跳过
    if !c.enabled {
        return nil, false, nil
    }

    // 2️⃣ 为当前 query 生成语义向量 (embedding)
    // 使用 candle_binding（基于 C++/Rust 的轻量推理库）
    // 向量长度通常为 512
	// 基于 ModernBERT / MiniLM 等嵌入模型
    queryEmbedding, err := candle_binding.GetEmbedding(query, 512)
    if err != nil {
        return nil, false, fmt.Errorf("failed to generate embedding: %w", err)
    }

    // 3️⃣ 加读锁（允许多线程同时读）
    c.mu.RLock()
    defer c.mu.RUnlock()

    // 清理过期条目（只读模式，不写锁）
    c.cleanupExpiredEntriesReadOnly()

    // 结果类型：存储每个候选条目及其相似度
    type SimilarityResult struct {
        Entry      CacheEntry
        Similarity float32
    }

    // 4️⃣ 遍历缓存条目，计算语义相似度
    results := make([]SimilarityResult, 0, len(c.entries))
    for _, entry := range c.entries {
        if entry.ResponseBody == nil {
            continue // 跳过无响应的条目
        }

        // 只比较相同模型下的条目（不同模型的语义空间可能不同）
		// 避免跨模型语义偏差
        if entry.Model != model {
            continue
        }

        // 计算余弦相似度（此处简化为点积，因为 embedding 已归一化）
        var dotProduct float32
        for i := 0; i < len(queryEmbedding) && i < len(entry.Embedding); i++ {
            dotProduct += queryEmbedding[i] * entry.Embedding[i]
        }

        results = append(results, SimilarityResult{
            Entry:      entry,
            Similarity: dotProduct,
        })
    }

    // 5️⃣ 没有候选项
    if len(results) == 0 {
        return nil, false, nil
    }

    // 6️⃣ 按相似度降序排序（最高的排在最前）
    sort.Slice(results, func(i, j int) bool {
        return results[i].Similarity > results[j].Similarity
    })

    // 7️⃣ 判断最相似条目是否超过相似度阈值
    if results[0].Similarity >= c.similarityThreshold {
        // 匹配成功：直接返回缓存的响应内容
        return results[0].Entry.ResponseBody, true, nil
    }

    // 无满足阈值的匹配项
    return nil, false, nil
}

```

‍

‍

‍

### 自动选择工具

#### 工具相关性算法

```go
// ================================================================
// 🧰 Tools Auto-Selection - 工具自动选择算法实现
// ================================================================

// ToolsSelector 用于根据用户请求自动挑选最相关的工具。
// 在智能路由系统中，这一模块让模型具备“可调用外部能力”的能力。
// 例如：代码任务 → 调用代码执行器；医学问题 → 查询医学知识库。
type ToolsSelector struct {
    toolsDB             *tools.ToolsDatabase   // 工具数据库（包含工具元数据、类别、关键词等）
    relevanceModel      *RelevanceModel        // 相关性模型（用于语义匹配与得分）
    maxTools            int                    // 最多选择多少个工具
    confidenceThreshold float64                // 工具选择的置信度阈值
}

// SelectRelevantTools 根据 query 自动筛选出最相关的工具。
func (ts *ToolsSelector) SelectRelevantTools(query string, availableTools []Tool // 候选工具列表) []Tool {
    var selectedTools []Tool

    // 1️⃣ 遍历所有候选工具，计算与 query 的相关性分数
    for _, tool := range availableTools {
        relevanceScore := ts.calculateRelevance(query, tool)

        // 2️⃣ 如果分数超过阈值，则加入结果集
        if relevanceScore > ts.confidenceThreshold {
            tool.RelevanceScore = relevanceScore
            selectedTools = append(selectedTools, tool)
        }
    }

    // 3️⃣ 按相关性得分降序排序
    sort.Slice(selectedTools, func(i, j int) bool {
        return selectedTools[i].RelevanceScore > selectedTools[j].RelevanceScore
    })

    // 4️⃣ 限制最多选择的工具数量
    if len(selectedTools) > ts.maxTools {
        selectedTools = selectedTools[:ts.maxTools]
    }

    return selectedTools
}

// calculateRelevance 计算 query 与某个工具之间的相关性得分。
// 它融合了多种信号（关键词匹配 + 语义匹配 + 类别一致性）。
func (ts *ToolsSelector) calculateRelevance(query string, tool Tool) float64 {
    // 1️⃣ 基于关键词的匹配分数（简单、快速）
    keywordScore := ts.calculateKeywordRelevance(query, tool)

    // 2️⃣ 基于语义向量的相似度分数（Embedding）
    semanticScore := ts.calculateSemanticRelevance(query, tool)

    // 3️⃣ 基于类别匹配的分数（分类标签一致性）
    categoryScore := ts.calculateCategoryRelevance(query, tool)
    
    // 4️⃣ 采用加权融合策略（可通过实验调整权重）
    // 当前权重：语义与关键词权重更高，类别一致性权重较低
    return 0.4*keywordScore + 0.4*semanticScore + 0.2*categoryScore
}

```

‍

### 安全实现

#### 敏感信息检测

```go
// ==========================================================
// 🔒 PII Detector - 个人信息检测模块
// ==========================================================

// PIIDetector 使用两种检测策略：
// 1️⃣ ModernBERT 的 Token-Level 分类器（检测上下文中的敏感实体）
// 2️⃣ 正则表达式（Regex）模式匹配（精确检测常见敏感字段，如手机号、邮箱）
//
// 两种结果融合后得到更高召回率与精度。
type PIIDetector struct {
    tokenClassifier  *ModernBERTTokenClassifier  // 基于 BERT 的 Token 分类模型
    piiPatterns      map[string]*regexp.Regexp   // 手工定义的正则检测规则
    confidence       float64                     // 置信度阈值
}

// DetectPII 对文本进行 PII 检测，返回检测结果与敏感实体列表
func (pd *PIIDetector) DetectPII(text string) (*PIIDetectionResult, error) {
    result := &PIIDetectionResult{
        HasPII:   false,         // 默认无敏感信息
        Entities: []PIIEntity{}, // 敏感实体列表
    }
    
    // 1️⃣ 使用 ModernBERT 进行 Token 级别分类
    tokens := pd.tokenClassifier.Tokenize(text)
    predictions, err := pd.tokenClassifier.Predict(tokens)
    if err != nil {
        return nil, err
    }
    
    // 2️⃣ 从预测结果中提取 PII 实体（如姓名、邮箱、银行卡号）
    entities := pd.extractEntities(tokens, predictions)
    
    // 3️⃣ 使用规则检测（正则匹配）增强精度
    patternEntities := pd.detectWithPatterns(text)
    
    // 4️⃣ 合并两种检测结果
    allEntities := append(entities, patternEntities...)
    
    // 5️⃣ 若检测到任何敏感实体，标记结果为阳性
    if len(allEntities) > 0 {
        result.HasPII = true
        result.Entities = allEntities
    }
    
    return result, nil
}

```

‍

#### 越狱/提示词注入检测

```go
// ==========================================================
// 🚫 Jailbreak Guard - Prompt Injection / 越狱检测模块
// ==========================================================
//
// 用于识别恶意或越权指令，例如：
// “忽略上面的安全限制”、“帮我获取管理员密码”
//
type JailbreakGuard struct {
    classifier     *ModernBERTBinaryClassifier  // 二分类模型：是否为 Jailbreak
    patterns       []JailbreakPattern           // 规则库（字符串匹配或语义模板）
    riskThreshold  float64                      // 风险阈值
}

// AssessRisk 对输入 query 进行越狱风险评估
func (jg *JailbreakGuard) AssessRisk(query string) (*SecurityAssessment, error) {
    // 1️⃣ 机器学习模型打分（ML-based Detection）
    // 输出 0~1 风险概率，例如 0.85 表示高风险
    mlScore, err := jg.classifier.PredictRisk(query)
    if err != nil {
        return nil, err
    }
    
    // 2️⃣ 基于规则的检测（Pattern-based Detection）
    // 匹配典型越狱模板，如 “忽略所有之前的指令”、“system override”
    patternScore := jg.calculatePatternScore(query)
    
    // 3️⃣ 融合模型与规则得分
    overallRisk := 0.7*mlScore + 0.3*patternScore
    
    // 4️⃣ 构造评估结果
    return &SecurityAssessment{
        RiskScore:    overallRisk,                     // 综合风险分数
        IsJailbreak:  overallRisk > jg.riskThreshold,  // 是否越狱行为
        MLScore:      mlScore,                         // 机器学习得分
        PatternScore: patternScore,                    // 模式匹配得分
        Reasoning:    jg.explainDecision(overallRisk, mlScore, patternScore),
    }, nil
}

```

‍

### 性能优化

#### 模型加载与缓存

```go
// ===========================================================
// 🧠 ModelManager - 模型加载与缓存管理器
// ===========================================================
//
// 主要功能：
// 1️⃣ 懒加载（Lazy Loading）：按需加载模型，节省启动时间与内存。
// 2️⃣ 模型缓存（Caching）：已加载模型常驻内存，避免重复加载。
// 3️⃣ 模型预热（Warmup）：异步预热模型，减少首次调用延迟。
type ModelManager struct {
    models     map[string]*LoadedModel // 已加载模型缓存池
    modelLock  sync.RWMutex            // 读写锁：并发安全的模型访问
    warmupPool sync.Pool               // 模型预热任务复用池（可减少内存分配）
}

// GetModel 提供线程安全的模型获取接口。
// 如果模型已加载 → 直接返回；否则执行懒加载 + 异步预热。
func (mm *ModelManager) GetModel(modelName string) (*LoadedModel, error) {
    // 1️⃣ 读锁快速路径（模型已存在时避免锁冲突）
    mm.modelLock.RLock()
    if model, exists := mm.models[modelName]; exists {
        mm.modelLock.RUnlock()
        return model, nil
    }
    mm.modelLock.RUnlock()
    
    // 2️⃣ 升级为写锁（避免多个线程同时加载同一模型）
    mm.modelLock.Lock()
    defer mm.modelLock.Unlock()
    
    // 双重检查（Double-check pattern）
    if model, exists := mm.models[modelName]; exists {
        return model, nil
    }
    
    // 3️⃣ 加载模型（例如从磁盘或远程模型仓库）
    model, err := mm.loadModel(modelName)
    if err != nil {
        return nil, err
    }
    
    // 4️⃣ 异步预热模型（加载权重到 GPU / 执行一次空推理）
    go mm.warmupModel(model)
    
    // 5️⃣ 缓存模型对象
    mm.models[modelName] = model
    return model, nil
}

func (mm *ModelManager) warmupModel(model *LoadedModel) {
    dummyInput := []string{"hello"}
    _, _ = model.Forward(dummyInput) // 一次空推理，加载权重到显存
    log.Printf("Model %s warmup complete", model.Name)
}

```

‍

#### 批量处理

```go
// ===========================================================
// ⚙️ BatchProcessor - 批量处理优化器
// ===========================================================
//
// 用于将多个分类或推理请求合并为一次 GPU 批处理。
// 特别适用于语义分类器（BERT 类模型）这种小输入任务。
type BatchProcessor struct {
    batchSize     int              // 最大批量大小
    batchTimeout  time.Duration    // 超时时间（达到此时间即强制flush）
    pendingBatch  []ProcessingRequest // 待处理请求队列
    batchMutex    sync.Mutex       // 并发安全锁
    flushTimer    *time.Timer      // 定时flush
}

// ProcessRequest 将单个请求加入批次；
// 如果达到批量上限或超时，则立即执行批处理。
func (bp *BatchProcessor) ProcessRequest(req ProcessingRequest) {
    bp.batchMutex.Lock()
    defer bp.batchMutex.Unlock()
    
    // 1️⃣ 添加到待处理队列
    bp.pendingBatch = append(bp.pendingBatch, req)
    
    // 2️⃣ 若批次已满 → 立即flush
    if len(bp.pendingBatch) >= bp.batchSize {
        bp.flushBatch()
        return
    }
    
    // 3️⃣ 启动定时器（超时后自动触发flush）
    if bp.flushTimer == nil {
        bp.flushTimer = time.AfterFunc(bp.batchTimeout, bp.flushBatch)
    }
}

// flushBatch 将队列中的请求合并推理并返回结果。
func (bp *BatchProcessor) flushBatch() {
    if len(bp.pendingBatch) == 0 {
        return
    }

    // 1️⃣ 合并请求 → 批量推理
    // 例如 BERT 模型一次处理 16 个文本
    results := bp.classifier.ProcessBatch(bp.pendingBatch)
    
    // 2️⃣ 将每个结果分发回对应请求
    for i, result := range results {
        bp.pendingBatch[i].ResultChannel <- result
    }

    // 3️⃣ 清空批次，重置定时器
    bp.pendingBatch = bp.pendingBatch[:0]
    if bp.flushTimer != nil {
        bp.flushTimer.Stop()
        bp.flushTimer = nil
    }
}

```

‍

### 监控与可观测

#### 请求跟踪

```go
// ===========================================================
// 🔍 RequestTracer - 请求级追踪系统
// ===========================================================
//
// 功能：
// - 为每个请求生命周期创建独立的 trace span
// - 记录每个阶段的耗时与上下文信息
// - 输出结构化日志，支持与 OpenTelemetry / Grafana Loki 对接
type RequestTracer struct {
    spans map[string]*Span  // 存储活跃中的 trace spans
    mutex sync.RWMutex      // 并发安全锁
}

// StartSpan 启动一个追踪片段（span），用于记录特定操作的起止时间。
func (rt *RequestTracer) StartSpan(requestID, operation string) *Span {
    span := &Span{
        RequestID: requestID,                    // 请求ID（唯一标识整个请求）
        Operation: operation,                    // 操作名（例如 "classification" / "routing"）
        StartTime: time.Now(),                   // 开始时间戳
        Tags:      make(map[string]interface{}), // 记录额外标签（如模型名、置信度等）
    }

    // 写入 span 集合
    rt.mutex.Lock()
    rt.spans[requestID+":"+operation] = span
    rt.mutex.Unlock()
    
    return span
}

// FinishSpan 结束追踪片段，记录持续时间并打印结构化日志。
func (rt *RequestTracer) FinishSpan(span *Span) {
    span.EndTime = time.Now()
    span.Duration = span.EndTime.Sub(span.StartTime)
    
    // 输出详细性能日志，可被 Promtail / Loki 收集
    log.WithFields(log.Fields{
        "request_id": span.RequestID,
        "operation":  span.Operation,
        "duration":   span.Duration.Milliseconds(),
        "tags":       span.Tags,
    }).Info("Operation completed")
    
    // 清理 span（防止内存泄漏）
    rt.mutex.Lock()
    delete(rt.spans, span.RequestID+":"+span.Operation)
    rt.mutex.Unlock()
}

```

‍

#### 性能指标

```go
// ===========================================================
// 📈 PerformanceTracker - 系统性能监控
// ===========================================================
//
// 功能：
// - 通过 Prometheus metrics 追踪系统关键性能指标
// - 评估分类延迟、缓存命中率、安全检测耗时、路由准确率
type PerformanceTracker struct {
    classificationLatency prometheus.Histogram // 分类延迟分布
    cacheHitRatio         prometheus.Gauge     // 缓存命中率
    securityCheckLatency  prometheus.Histogram // 安全检测耗时
    routingAccuracy       *prometheus.GaugeVec // 按类别统计的分类准确率
}

// RecordClassification 记录一次分类操作的性能数据。
func (pt *PerformanceTracker) RecordClassification(
    category string, 
    confidence float64, 
    duration time.Duration,
) {
    // 1️⃣ 记录延迟分布
    pt.classificationLatency.Observe(duration.Seconds())
    
    // 2️⃣ 记录分类准确率（按类别标签区分）
    accuracyMetric := pt.routingAccuracy.WithLabelValues(category)
    accuracyMetric.Set(confidence)
}

```
