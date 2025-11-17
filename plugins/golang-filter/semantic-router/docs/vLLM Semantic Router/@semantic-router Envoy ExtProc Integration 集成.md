# @semantic-router Envoy ExtProc Integration 集成

语义路由器利用 Envoy 的外部处理（ExtProc）过滤器来实现智能路由决策。

这种集成实现了流量管理（Envoy）和业务逻辑（语义路由器）之间的清晰分离，在保持高性能的同时，实现了复杂的路由功能。

‍

### 了解 Envoy ExtProc

外部处理（ExtProc）是一种 Envoy 过滤器，**允许外部服务参与请求和响应处理**。与其他扩展机制不同，ExtProc 提供以下功能：

- 流式处理：在请求和响应流经 Envoy 时对其进行处理（可以边传输边处理）。
- 完全控制：修改请求头、响应头、消息体和路由决策。
- 低延迟：Envoy 与外部服务之间经过优化的 gRPC 通信。
- 容错能力：内置故障处理和超时管理。

‍

### ExtProc 与其他扩展方法的对比

|扩展方式|典型用途|延迟|灵活性|实现复杂度|
| ----------| ------------------------------------------| ------| --------| ------------|
|**HTTP Filters**|简单的数据转换（如增加Header、修改路径）|**最低**|**受限**|**低**|
|**WebAssembly (WASM)**|在沙箱中运行轻量逻辑，安全性高|**低**|**中等**|**中等**|
|**ExtProc (External Processing)**|处理复杂业务逻辑，与外部服务交互|**中等**|**高**|**中等**|
|**HTTP Callouts**|调用外部API（例如访问第三方服务）|**高**|**高**|**高**|

为什么在语义路由中使用 ExtProc？

- 复杂的机器学习模型：

  - **WASM 不适合运行像 BERT 这样的深度学习模型**（WASM 沙箱不支持 Python 生态，也缺乏深度学习库）。
  - ExtProc 通过 gRPC 与外部服务通信，可以让你的分类器（如 Python + PyTorch）在独立服务中运行。
- 动态决策制定：

  - 智能路由需要根据请求内容动态判断：这是数学题、代码问题、还是医疗问题？
  - ExtProc 能实时修改路由目标（例如将 `/v1/chat/completions` 动态改写为调用不同的后端模型）。
- 状态管理：

  - 语义路由可能需要缓存历史决策（如请求 ID、用户上下文、模型表现统计）。
  - ExtProc 允许外部服务维护这些状态，比如使用 Redis、内存缓存或数据库。
- 可观测性：

  - ExtProc 的**外部服务可以全面记录**：请求内容、延迟、模型选择、评分等指标。
  - 可以暴露 Prometheus 指标或日志，帮助监控系统效果与性能。

‍

### ExtProc 协议架构

#### **通信流程**

![image](assets/image-20251025165814-vqwtc6t.png)

|阶段|ExtProc 功能|对语义路由意义|
| ------------| --------------------| ----------------------------|
|请求头阶段|分析请求元数据|可根据用户信息提前判断模型|
|请求体阶段|语义分类、动态选路|决定使用哪个后端模型|
|响应阶段|评分与数据采集|支持自学习与性能优化|
|缓存与监控|持久化与指标采集|支撑 MLOps 循环改进|

 **🧠 整体结构**

图中有四个参与者：

1. ​**Client**​：客户端（例如调用 `/v1/chat/completions` 的用户请求）
2. ​**Envoy**：代理层（Higress 基于 Envoy 构建）
3. ​**Router (ExtProc)** ：外部处理服务（你的智能语义路由器）
4. ​**Backend**：后端模型服务（如 qwen-math、qwen-code 等）

---

 **📡 请求阶段流程**

1. **Client → Envoy：HTTP Request**

    - 客户端发送一个标准的 OpenAI 格式请求。
2. **Envoy 处理请求头**

    - Envoy 收到请求后，首先触发 ​**ExtProc Filter**，并向外部的 Router 发送：

      ```
      ProcessingRequest(RequestHeaders)
      ```
    - Router（即智能路由器）可以在此阶段分析请求头、用户信息、元数据等。
3. **Router → Envoy：ProcessingResponse (Continue/Modify)**

    - Router 可以选择继续处理（Continue）或修改请求头（Modify）。
4. **Envoy 发送请求体**

    - 接下来 Envoy 将请求体（包含用户的问题文本）流式发送给 Router：

      ```
      ProcessingRequest(RequestBody)
      ```
5. **Router 执行分类与路由逻辑**

    - 这是智能路由的核心：

      - Router 调用语义分类模型（如 BERT / MiniLM）
      - 判断问题类型（数学、代码、医学等）
      - 选择最优模型（如 qwen-math-7b）
6. **Router → Envoy：返回 HeaderMutation**

    - Router 修改请求头（例如添加 `X-Target-Model: qwen-math-7b`）
    - Envoy 据此“按头路由”（Route based on headers），将请求转发到相应后端。

---

 **🧭 响应阶段流程**

1. **Envoy → Router：ProcessingRequest(ResponseHeaders)**

    - 后端模型返回响应，Envoy 将响应头转发给 Router。
2. **Router 可选择继续或修改响应头**

    - 例如插入评分信息、响应来源标签等。
3. **Envoy → Router：ProcessingRequest(ResponseBody)**

    - Envoy 将响应体流式传给 Router。
4. **Router 进行响应处理与缓存**

    - Router 可以：

      - 调用 `/v1/evaluate` 接口为答案评分；
      - 缓存结果；
      - 将 `{question, model, answer, score}` 存入数据库以支持“数据飞轮”机制。
5. **Router → Envoy：ProcessingResponse (BodyMutation)**

    - Router 可以修改响应内容或附加元数据。
6. **Envoy → Client：Final Response**

    - 最终的响应返回给客户端。

‍

#### 处理模式

```yaml
processing_mode:
  request_header_mode: "SEND"      # 处理请求头
  response_header_mode: "SEND"     # 处理响应头
  request_body_mode: "BUFFERED"    # 处理完整请求体
  response_body_mode: "BUFFERED"   # 处理完整响应体
  request_trailer_mode: "SKIP"     # 跳过请求尾部
  response_trailer_mode: "SKIP"    # 跳过响应尾部
```

解释：

|阶段|配置项|说明|在智能路由中的作用|
| ------| --------| --------------------------------| --------------------------------------------------|
|**请求头 (Request Headers)**|​`request_header_mode: SEND`|将 HTTP 请求头发送给 ExtProc|可以读取`Authorization`​、`User-Agent`等信息，用于上下文分析或多租户判断|
|**请求体 (Request Body)**|​`request_body_mode: BUFFERED`|收集完整请求体后发送给 ExtProc|语义分类的关键步骤，需要分析`messages`中的用户输入|
|**响应头 (Response Headers)**|​`response_header_mode: SEND`|将响应头发送给 ExtProc|可添加模型信息或评分标记，如`X-Model: qwen-math-7b`|
|**响应体 (Response Body)**|​`response_body_mode: BUFFERED`|收集完整响应体后发送给 ExtProc|用于调用`/v1/evaluate`接口评估答案准确度|
|**请求尾 (Request Trailers)**|​`request_trailer_mode: SKIP`|不处理（最快）|一般HTTP请求几乎不用Trailers|
|**响应尾 (Response Trailers)**|​`response_trailer_mode: SKIP`|不处理（最快）|同上，节省性能开销|

‍

模式可选项详解：

|模式|含义|性能|适用场景|
| ------| -----------------------------------------| --------| ----------------------------|
|**SKIP**|完全跳过该阶段，不发送数据给 ExtProc|✅最快|无需处理的场景，如 trailer|
|**SEND**|只发送 header/trailer 信息，不包含 body|⚡很快|仅需检查头部或轻量逻辑|
|**BUFFERED**|等待整个 body 收齐再发送给 ExtProc|🧠中等|需要内容分析（如语义分类）|
|**STREAMED**|将 body 以流式分块发送|🚀稍慢|适合流式推理或长响应场景|

‍

推荐配置

|目标|推荐配置|原因|
| -------------------------------| ----------| -----------------------------------------------------|
|**语义分类（分析请求内容）**|​`request_body_mode: BUFFERED`|需要完整问题文本|
|**动态路由（修改请求头）**|​`request_header_mode: SEND`|通过添加`X-Target-Model`实现智能转发|
|**结果评分（分析响应内容）**|​`response_body_mode: BUFFERED`|需要完整模型输出用于`/v1/evaluate`|
|**性能优化（跳过无用部分）** <br />|​`request_trailer_mode: SKIP`|避免多余调用，降低延迟<br />|
||​`response_trailer_mode: SKIP`||

‍

### 语义路由器 ExtProc 实现

#### Go 实现结构

```go
// 主 ExtProc 服务器结构体
type Server struct {
    router *OpenAIRouter   // 核心业务逻辑组件（语义分类、路由决策等）
    server *grpc.Server    // gRPC 服务实例，用于 Envoy 与外部处理器通信
    port   int             // 服务监听端口（Envoy ext_proc filter 会通过此端口调用）
}

// OpenAIRouter 实现了 Envoy 的 ExtProc 服务接口
// 它是整个智能语义路由的核心：负责分类、路由、缓存、审查等逻辑
type OpenAIRouter struct {
    Config               *config.RouterConfig     // 插件运行配置（模型池、策略、阈值、后端地址等）
    CategoryDescriptions []string                 // 语义类别描述（例如“数学问题”“代码生成”“医学咨询”等）
    Classifier           *classification.Classifier // 文本分类器，用于根据请求内容选择最优模型
    PIIChecker           *pii.PolicyChecker       // PII 检查器，用于检测并屏蔽敏感信息
    Cache                *cache.SemanticCache     // 语义缓存，减少重复计算与模型调用
    ToolsDatabase        *tools.ToolsDatabase     // 工具数据库（可扩展：代码执行器、医学知识库等）

    pendingRequests     map[string][]byte         // 用于暂存正在处理的请求数据（按请求ID索引）
    pendingRequestsLock sync.Mutex                // 保证并发环境下访问 pendingRequests 的线程安全
}

// 这一行表示 OpenAIRouter 实现了 Envoy 的 ExternalProcessorServer 接口
// Envoy 通过 gRPC 调用该接口，从而让路由器能接收请求头、请求体、响应头、响应体事件
var _ ext_proc.ExternalProcessorServer = &OpenAIRouter{}
```

‍

💡 补充说明：

- ​**​`ExternalProcessorServer`​**​ **接口**  
  由 Envoy 定义，包含以下典型回调方法：

  ```go
  func (r *OpenAIRouter) ProcessRequestHeaders(...) (*ext_proc.ProcessingResponse, error)
  func (r *OpenAIRouter) ProcessRequestBody(...) (*ext_proc.ProcessingResponse, error)
  func (r *OpenAIRouter) ProcessResponseHeaders(...) (*ext_proc.ProcessingResponse, error)
  func (r *OpenAIRouter) ProcessResponseBody(...) (*ext_proc.ProcessingResponse, error)
  ```

  每个方法对应 ExtProc 生命周期的一个阶段。
- **实现目的**

  - 拦截请求头/体 → 执行语义分类
  - 修改请求头（如加上 `X-Target-Model`）→ 动态路由到合适的模型
  - 拦截响应体 → 执行评分与缓存
  - 最终返回处理后的响应给 Envoy

‍

#### gRPC 服务实现

```go
// Process 方法是 ExtProc 的核心实现 —— 处理 Envoy 发来的流式请求
// Envoy 在请求/响应的每个阶段（headers、body 等）都会通过此 gRPC 流发送事件。
// OpenAIRouter 在此方法中接收、处理并返回修改后的响应。
func (r *OpenAIRouter) Process(stream ext_proc.ExternalProcessor_ProcessServer) error {
    // 日志：标记开始处理一个新的请求
    log.Println("Started processing a new request")
    
    // 创建上下文对象，用于保存一次完整请求的状态信息
    ctx := &RequestContext{
        Headers:   make(map[string]string), // 存储请求头键值对
        RequestID: generateRequestID(),     // 为本次请求生成唯一 ID（方便追踪与缓存）
    }

    // 主循环：持续从 Envoy 接收流式事件（headers/body/response 等）
    for {
        // ① 从 Envoy 接收一个 ProcessingRequest 消息（可能是 header、body 或 response）
        req, err := stream.Recv()
        if err != nil {
            // 如果接收失败（例如连接断开或流结束），调用错误处理函数
            return r.handleStreamError(err)
        }

        // ② 根据请求类型执行对应逻辑（如 header 阶段或 body 阶段）
        // processRequest 会判断 req 的类型（例如 RequestHeaders、RequestBody 等）
        // 然后调用对应的业务处理函数，如 handleRequestHeaders() / handleRequestBody()
        response, err := r.processRequest(ctx, req)
        if err != nil {
            // 如果处理阶段出错，终止流并返回错误
            return err
        }

        // ③ 将处理结果（ProcessingResponse）发送回 Envoy
        // Envoy 根据返回结果决定下一步操作，例如：
        // - CONTINUE: 继续请求流程
        // - MODIFY: 应用修改后的 headers/body
        // - IMMEDIATE_RESPONSE: 直接返回响应给客户端
        if err := stream.Send(response); err != nil {
            // 如果发送响应失败，终止处理
            return err
        }
    }
}

```

‍

**工作机制详解：**

1. **Envoy → ExtProc：发送阶段事件**

Envoy 会在不同阶段通过 gRPC 发送：

- ​`RequestHeaders`
- ​`RequestBody`
- ​`ResponseHeaders`
- ​`ResponseBody`

这些事件会逐条进入 `stream.Recv()`。

‍

2. **ExtProc → 调用业务逻辑**

​`processRequest(ctx, req)` 内部一般会这样：

```go
switch msg := req.Request.(type) {
case *ext_proc.ProcessingRequest_RequestHeaders:
    return r.handleRequestHeaders(ctx, msg)
case *ext_proc.ProcessingRequest_RequestBody:
    return r.handleRequestBody(ctx, msg)
case *ext_proc.ProcessingRequest_ResponseHeaders:
    return r.handleResponseHeaders(ctx, msg)
case *ext_proc.ProcessingRequest_ResponseBody:
    return r.handleResponseBody(ctx, msg)
}
```

每个阶段都可以独立分析、修改、打标签或路由。

‍

3. **ExtProc → Envoy：返回指令**

​`stream.Send(response)` 把结果发回 Envoy。  
典型返回：

- ​`CONTINUE`：继续原请求（不修改）
- ​`HEADER_MUTATION`：修改请求头（如添加目标模型）
- ​`BODY_MUTATION`：修改响应体（如附加评分）
- ​`IMMEDIATE_RESPONSE`：直接生成响应返回客户端（用于安全阻断）

‍

#### 请求处理流程

##### 请求头处理

```go
// handleRequestHeaders 负责处理 Envoy 在“请求头阶段”发送的事件。
// 在这个阶段，我们通常只做一些轻量操作，例如：
// - 提取请求头信息
// - 解析路径、方法、内容类型
// - 暂存元数据以供后续请求体分析（分类逻辑）使用
func (r *OpenAIRouter) handleRequestHeaders(
	ctx *RequestContext, 
	headers *ext_proc.ProcessingRequest_RequestHeaders) (*ext_proc.ProcessingResponse, error) {
    
    // 1️⃣ 提取并保存所有请求头到上下文中
    // Envoy 通过 gRPC 发送的请求头列表结构是：
    // headers.RequestHeaders.Headers.Headers -> []HeaderValue
    // 我们把它们存入 ctx.Headers 以备后续使用
    for _, header := range headers.RequestHeaders.Headers.Headers {
        ctx.Headers[header.Key] = header.Value
    }
    
    // 2️⃣ 提取关键元数据
    // :method 是 HTTP 方法 (POST/GET)
    // :path 是请求路径（例如 /v1/chat/completions）
    // content-type 用于判断请求体格式（通常是 application/json）
    ctx.Method = ctx.Headers[":method"]
    ctx.Path = ctx.Headers[":path"]
    ctx.ContentType = ctx.Headers["content-type"]
    
    // 3️⃣ 返回一个继续执行的响应
    // 在这里我们不做任何修改，只告诉 Envoy “继续处理请求”
    // 因为语义分类需要分析请求体（Body），此阶段仅作准备。
    return &ext_proc.ProcessingResponse{
        Response: &ext_proc.ProcessingResponse_RequestHeaders_{
            RequestHeaders: &ext_proc.ProcessingResponse_RequestHeaders{},
        },
    }, nil
}

```

##### 请求体处理（核心逻辑）

```go
// handleRequestBody 是智能语义路由的核心处理函数。
// 当 Envoy 收到完整请求体（Body）后，会调用此方法。
// 在这里我们要：
// 1. 解析用户问题
// 2. 执行安全检查与缓存查询
// 3. 使用分类模型判断语义类别
// 4. 选择最优模型和工具
// 5. 修改请求并设置动态路由头
func (r *OpenAIRouter) handleRequestBody(
    ctx *RequestContext,
    body *ext_proc.ProcessingRequest_RequestBody,
) (*ext_proc.ProcessingResponse, error) {
    
    // 1️⃣ 提取请求体内容（原始字节）
    requestBody := body.RequestBody.Body
    
    // 2️⃣ 解析 OpenAI Chat API 请求结构
    // 通常格式为：
    // {
    //   "model": "qwen-max",
    //   "messages": [{"role": "user", "content": "..."}]
    // }
    var openAIRequest OpenAIRequest
    if err := json.Unmarshal(requestBody, &openAIRequest); err != nil {
        return nil, fmt.Errorf("failed to parse OpenAI request: %w", err)
    }
    
    // 3️⃣ 提取用户输入内容（即语义分类所需文本）
    // 例如 messages 最后一条 user 内容
    userQuery := extractUserQuery(openAIRequest.Messages)
    
    // 4️⃣ Step 1: 查询语义缓存
    // 如果之前处理过相似问题，直接复用缓存结果，避免重复分类和模型调用
    if cachedResponse, found := r.Cache.Get(userQuery); found {
        return r.handleCacheHit(cachedResponse)
    }
    
    // 5️⃣ Step 2: 安全与隐私检查（PII 检测）
    // 检测用户输入中是否含有敏感或禁止内容
    if blocked, reason := r.performSecurityChecks(userQuery); blocked {
        return r.handleSecurityBlock(reason)
    }
    
    // 6️⃣ Step 3: 执行语义分类
    // 使用轻量级模型（如 MiniLM / BERT）识别问题类型：
    // 可能输出：{Category: "math", Confidence: 0.95}
    classification, err := r.Classifier.ClassifyIntent(userQuery)
    if err != nil {
        return nil, err
    }
    
    // 7️⃣ Step 4: 根据分类结果选择最优后端模型
    // 例如：
    // math → qwen-math-7b
    // code → qwen-code-7b
    // medicine → qwen-medicine-7b
    selectedEndpoint := r.selectModelEndpoint(classification)
    
    // 8️⃣ Step 5: 自动选择工具（可选逻辑）
    // 如果模型需要使用特定工具（如代码执行器、检索数据库），则自动匹配
    selectedTools := r.autoSelectTools(userQuery, openAIRequest.Tools)
    
    // 9️⃣ Step 6: 修改请求内容
    // 根据工具或模型选择结果动态重写请求（例如替换 model 字段）
    modifiedRequest := r.modifyRequest(openAIRequest, selectedTools)
    modifiedBody, _ := json.Marshal(modifiedRequest)
    
    // 🔟 Step 7: 为 Envoy 设置动态路由头
    // Envoy 将依据这些 Header 把请求转发到目标模型后端
    headerMutations := []*core.HeaderValueOption{
        {
            Header: &core.HeaderValue{
                Key:   "x-gateway-destination-endpoint", // 告诉网关目标上游地址
                Value: selectedEndpoint,
            },
            Append: &wrapperspb.BoolValue{Value: false},
        },
        {
            Header: &core.HeaderValue{
                Key:   "x-selected-model", // 记录选择的模型类别
                Value: classification.Category,
            },
            Append: &wrapperspb.BoolValue{Value: false},
        },
        {
            Header: &core.HeaderValue{
                Key:   "x-routing-confidence", // 路由置信度，便于后续监控和评估
                Value: fmt.Sprintf("%.3f", classification.Confidence),
            },
            Append: &wrapperspb.BoolValue{Value: false},
        },
    }
    
    // 🧾 Step 8: 记录路由决策（用于监控和训练数据生成）
    r.recordRoutingDecision(ctx, classification, selectedEndpoint)
    
    // 🧠 Step 9: 返回给 Envoy 的处理响应
    // - 修改请求体为新的 JSON
    // - 设置 ModeOverride 表示后续还要处理响应头
    // - 附带 DynamicMetadata 方便监控
    return &ext_proc.ProcessingResponse{
        Response: &ext_proc.ProcessingResponse_RequestBody_{
            RequestBody: &ext_proc.ProcessingResponse_RequestBody{
                Response: &ext_proc.BodyResponse{
                    BodyMutation: &ext_proc.BodyMutation{
                        Mutation: &ext_proc.BodyMutation_Body{
                            Body: modifiedBody, // 替换后的请求体
                        },
                    },
                },
            },
        },
        ModeOverride: &ext_proc.ProcessingMode{
            RequestHeaderMode:  ext_proc.ProcessingMode_SEND,
            ResponseHeaderMode: ext_proc.ProcessingMode_SEND,
        },
        DynamicMetadata: r.buildDynamicMetadata(classification), // 附带分类结果等元信息
    }, nil
}

```

##### 响应处理

```go
// handleResponseBody 处理模型响应阶段（Response Body）
// Envoy 在收到上游模型的响应后，会通过 ExtProc 把响应体传给此方法。
// 我们在这里可以：
//  - 解析模型返回的内容
//  - 缓存结果
//  - 记录路由性能指标
//  - 给响应附加元数据（例如路由信息、置信度等）
func (r *OpenAIRouter) handleResponseBody(
    ctx *RequestContext,
    responseBody *ext_proc.ProcessingRequest_ResponseBody,
) (*ext_proc.ProcessingResponse, error) {
    
    // 1️⃣ 解析上游模型的响应体（OpenAI 标准格式）
    // 模型响应一般形如：
    // {
    //   "id": "...",
    //   "model": "qwen-code-7b",
    //   "choices": [{
    //       "message": {"role": "assistant", "content": "生成的答案..."}
    //   }]
    // }
    var modelResponse OpenAIResponse
    if err := json.Unmarshal(responseBody.ResponseBody.Body, &modelResponse); err != nil {
        return nil, err
    }
    
    // 2️⃣ 将结果存入语义缓存（Semantic Cache）
    // 这样下次遇到相同或相似的 userQuery，可以直接命中缓存，避免重复计算。
    // 缓存结构大致为：
    //   { userQuery → (modelResponse, selectedModel) }
    if ctx.UserQuery != "" {
        r.Cache.Store(ctx.UserQuery, modelResponse, ctx.SelectedModel)
    }
    
    // 3️⃣ 记录路由性能与响应指标
    // 例如：
    // - 处理时延
    // - 模型选择准确率（后续通过 /v1/evaluate 评分）
    // - 成本统计（按模型类型）
    r.recordResponseMetrics(ctx, modelResponse)
    
    // 4️⃣ 为响应添加路由元数据（Metadata）
    // 比如：
    // - x-selected-model
    // - x-routing-confidence
    // - x-response-latency
    // 这些信息会返回给客户端或被监控系统采集
    modifiedResponse := r.addRoutingMetadata(modelResponse, ctx)
    modifiedBody, _ := json.Marshal(modifiedResponse)
    
    // 5️⃣ 返回处理结果给 Envoy
    // 用 BodyMutation 替换响应体，将增强后的响应发回客户端
    return &ext_proc.ProcessingResponse{
        Response: &ext_proc.ProcessingResponse_ResponseBody_{
            ResponseBody: &ext_proc.ProcessingResponse_ResponseBody{
                Response: &ext_proc.BodyResponse{
                    BodyMutation: &ext_proc.BodyMutation{
                        Mutation: &ext_proc.BodyMutation_Body{
                            Body: modifiedBody, // 替换为包含路由信息的新响应
                        },
                    },
                },
            },
        },
    }, nil
}

```

‍

### ExtProc 的 Envoy 配置

#### 完整示例

```yaml
# ===============================
# Envoy 主配置文件 - config/envoy.yaml
# ===============================
static_resources:
  listeners:
  - name: listener_0
    address:
      socket_address:
        address: 0.0.0.0
        port_value: 8801   # Envoy 网关监听端口（供客户端访问）

    filter_chains:
    - filters:
      - name: envoy.filters.network.http_connection_manager
        typed_config:
          "@type": type.googleapis.com/envoy.extensions.filters.network.http_connection_manager.v3.HttpConnectionManager
          stat_prefix: ingress_http

          # ------------------------------------------
          # 访问日志配置：记录请求路径、模型选择等元信息
          # ------------------------------------------
          access_log:
          - name: envoy.access_loggers.stdout
            typed_config:
              "@type": type.googleapis.com/envoy.extensions.access_loggers.stream.v3.StdoutAccessLog
              log_format:
                json_format:
                  time: "%START_TIME%"
                  method: "%REQ(:METHOD)%"
                  path: "%REQ(X-ENVOY-ORIGINAL-PATH?:PATH)%"
                  response_code: "%RESPONSE_CODE%"
                  duration: "%DURATION%"
                  selected_model: "%REQ(X-SELECTED-MODEL)%"
                  selected_endpoint: "%REQ(X-GATEWAY-DESTINATION-ENDPOINT)%"
                  routing_confidence: "%REQ(X-ROUTING-CONFIDENCE)%"
          
          # ------------------------------------------
          # 动态路由配置：根据 ExtProc 注入的 Header 动态分流
          # ------------------------------------------
          route_config:
            name: local_route
            virtual_hosts:
            - name: local_service
              domains: ["*"]
              routes:
              # 根据 x-gateway-destination-endpoint 头路由到不同集群（对应不同类型的大模型）
              - match:
                  prefix: "/"
                  headers:
                  - name: "x-gateway-destination-endpoint"
                    string_match:
                      exact: "endpoint1"
                route:
                  cluster: math_model_cluster
                  timeout: 300s

              - match:
                  prefix: "/"
                  headers:
                  - name: "x-gateway-destination-endpoint"
                    string_match:
                      exact: "endpoint2"
                route:
                  cluster: creative_model_cluster
                  timeout: 300s

              - match:
                  prefix: "/"
                  headers:
                  - name: "x-gateway-destination-endpoint"
                    string_match:
                      exact: "endpoint3"
                route:
                  cluster: code_model_cluster
                  timeout: 300s

              # 默认兜底路由：若未设置路由头，则走通用大模型
              - match:
                  prefix: "/"
                route:
                  cluster: general_model_cluster
                  timeout: 300s
          
          # ------------------------------------------
          # HTTP 过滤器链配置
          # ------------------------------------------
          http_filters:
          # 🧠 ExtProc 过滤器 - 必须在 router 过滤器之前
          - name: envoy.filters.http.ext_proc
            typed_config:
              "@type": type.googleapis.com/envoy.extensions.filters.http.ext_proc.v3.ExternalProcessor
              
              # gRPC 服务配置（连接智能语义路由器）
              grpc_service:
                envoy_grpc:
                  cluster_name: semantic_router_extproc   # 下方 cluster 定义
                timeout: 30s

              # --------------------------------------
              # ExtProc 生命周期处理模式
              # --------------------------------------
              processing_mode:
                request_header_mode: "SEND"      # 处理请求头
                response_header_mode: "SEND"     # 处理响应头
                request_body_mode: "BUFFERED"    # 缓冲整个请求体（语义分析用）
                response_body_mode: "BUFFERED"   # 缓冲整个响应体（可做评分或附加信息）
                request_trailer_mode: "SKIP"     # 跳过尾部 Trailer
                response_trailer_mode: "SKIP"

              # --------------------------------------
              # 容错与高级配置
              # --------------------------------------
              failure_mode_allow: true            # 若 ExtProc 失败，仍允许请求继续（保证系统可用性）
              allow_mode_override: true           # 允许 ExtProc 动态修改处理模式（如流式输出时切换为 STREAMED）
              message_timeout: 300s               # 单次消息超时
              max_message_timeout: 600s           # 全局最大超时

              # ⚙️ 流式响应说明（SSE）
              # 若上游返回 text/event-stream（如 LLM 流式输出），
              # ExtProc 会自动切换到 STREAMED 模式以确保首 token 延迟可监控。

              # --------------------------------------
              # 高级变更与安全控制
              # --------------------------------------
              mutation_rules:
                allow_all_routing: true
                allow_envoy: true
                disallow_system: false
                disallow_x_forwarded: false

              # --------------------------------------
              # ExtProc 统计项配置
              # --------------------------------------
              stats_config:
                stats_matches:
                - name: "extproc_requests"
                  actions:
                  - name: "extproc_requests_total"
                    action: 
                      "@type": type.googleapis.com/envoy.extensions.filters.http.fault.v3.HTTPFault

          # 🚦 Router 过滤器（必须位于最后，用于转发到目标集群）
          - name: envoy.filters.http.router
            typed_config:
              "@type": type.googleapis.com/envoy.extensions.filters.http.router.v3.Router
              suppress_envoy_headers: true

  # ==========================================================
  # 后端集群定义（模型服务 & ExtProc 服务）
  # ==========================================================

  clusters:
  # 🔹 ExtProc 外部处理服务（语义路由器）
  - name: semantic_router_extproc
    connect_timeout: 5s
    type: STATIC
    lb_policy: ROUND_ROBIN
    typed_extension_protocol_options:
      envoy.extensions.upstreams.http.v3.HttpProtocolOptions:
        "@type": type.googleapis.com/envoy.extensions.upstreams.http.v3.HttpProtocolOptions
        explicit_http_config:
          http2_protocol_options:
            connection_keepalive:
              interval: 30s
              timeout: 5s
            max_concurrent_streams: 1000   # 高并发优化（ExtProc 通信走 HTTP/2）
    load_assignment:
      cluster_name: semantic_router_extproc
      endpoints:
      - lb_endpoints:
        - endpoint:
            address:
              socket_address:
                address: 127.0.0.1         # 语义路由服务地址
                port_value: 50051          # 对应 gRPC 端口（ExtProc Server）
    
    # 健康检查：保证 ExtProc 服务可靠性
    health_checks:
    - timeout: 5s
      interval: 10s
      unhealthy_threshold: 3
      healthy_threshold: 2
      grpc_health_check:
        service_name: "semantic-router"

  # 🔹 数学模型服务集群
  - name: math_model_cluster
    connect_timeout: 30s
    type: STRICT_DNS
    lb_policy: ROUND_ROBIN
    load_assignment:
      cluster_name: math_model_cluster
      endpoints:
      - lb_endpoints:
        - endpoint:
            address:
              socket_address:
                address: 127.0.0.1
                port_value: 11434           # math 模型 mock 服务端口
    # 健康检查
    health_checks:
    - timeout: 10s
      interval: 15s
      unhealthy_threshold: 3
      healthy_threshold: 2
      http_health_check:
        path: "/health"
        expected_statuses:
        - start: 200
          end: 299

  # creative_model_cluster / code_model_cluster / general_model_cluster
  # ...（结构类似，指向不同后端模型）

```

### 性能优化

#### 降低 ExtProc 延迟

1. 连接池与 Keepalive 优化

```yaml
# 优化 Envoy 到 ExtProc 的 gRPC 连接
grpc_service:
  envoy_grpc:
    cluster_name: semantic_router_extproc
  timeout: 10s  # 从默认 30s 缩短为 10s，提高响应敏感度

# ExtProc 集群优化配置
typed_extension_protocol_options:
  envoy.extensions.upstreams.http.v3.HttpProtocolOptions:
    explicit_http_config:
      http2_protocol_options:
        connection_keepalive:
          interval: 30s      # 定期发送心跳，保持连接活跃
          timeout: 5s        # 若心跳失败 5s 内无响应则重连
        max_concurrent_streams: 1000  # 同一连接支持 1000 个并发流请求

```

2. 选择性处理

```yaml
# 只处理必要的阶段，减少无意义的 gRPC 往返
processing_mode:
  request_header_mode: "SEND"        # 必需，用于拦截路由头
  response_header_mode: "SKIP"       # 若不需修改响应头则跳过
  request_body_mode: "BUFFERED"      # 语义分类必须读取完整 Body
  response_body_mode: "BUFFERED"     # 若启用缓存或评分，则保留；否则可 SKIP

```

3. 快速失败与超时

```yaml
# ExtProc 失败时快速恢复
failure_mode_allow: true     # 若 ExtProc 挂掉，不阻塞主请求
message_timeout: 30s         # 每次 ExtProc 响应最大等待 30s
max_message_timeout: 60s     # 上限 60s，用于紧急情况
```

‍

### 内存管理

#### 请求上下文池化

```go
// ================================================
// 🚀 内存优化：请求上下文池化 (Request Context Pooling)
// ================================================

// 创建一个全局的 sync.Pool，用于复用 RequestContext 对象
// sync.Pool 的作用是：
//   - 避免每次请求都分配新的上下文结构体
//   - 减少 GC 压力（尤其在高并发 gRPC 流中）
//   - 提升内存局部性（复用热对象）
var requestContextPool = sync.Pool{
    New: func() interface{} {
        // 当池中没有可复用对象时，会调用此函数创建一个新的
        return &RequestContext{
            Headers: make(map[string]string, 10), // 预分配少量 Header 空间
        }
    },
}

// 修改后的 Process 主函数
func (r *OpenAIRouter) Process(stream ext_proc.ExternalProcessor_ProcessServer) error {
    // 1️⃣ 从对象池中获取一个 RequestContext（若无则创建新对象）
    ctx := requestContextPool.Get().(*RequestContext)

    // 2️⃣ 在函数结束时清理并归还到池中
    defer func() {
        ctx.Reset()                 // 清空上下文（释放引用、清理 map）
        requestContextPool.Put(ctx) // 放回对象池以便复用
    }()
    
    // 3️⃣ 执行常规请求处理逻辑（与之前相同）
    // 循环读取 Envoy 的 gRPC 流、执行分类、路由、响应等
    for {
        req, err := stream.Recv()
        if err != nil {
            return r.handleStreamError(err)
        }
        response, err := r.processRequest(ctx, req)
        if err != nil {
            return err
        }
        if err := stream.Send(response); err != nil {
            return err
        }
    }
}

```

在高并发环境（例如 Envoy 同时处理上千个请求）中，每次新建结构体都会：

- 分配内存；
- 创建内部 map；
- 增加垃圾回收负担。

​`sync.Pool`​ 可以在请求完成后**回收并复用对象**，极大减少 GC 频率。

‍

### 错误处理与降级

#### ExtProc 错误处理

```go
// =====================================================
// 🧩 ExtProc 错误处理 (Error Handling)
// =====================================================

// handleStreamError 用于统一处理 gRPC 流式通信中的错误。
// 这个函数保证 ExtProc 服务在异常情况下不会崩溃，
// 并能在可恢复错误（如连接断开、超时）时优雅退出。
func (r *OpenAIRouter) handleStreamError(err error) error {
    // 1️⃣ gRPC 流正常结束（EOF 表示流被对方关闭）
    if err == io.EOF {
        log.Println("Stream ended gracefully")
        return nil
    }

    // 2️⃣ gRPC 层错误处理（状态码分类）
    if s, ok := status.FromError(err); ok {
        switch s.Code() {

        // 🔹 Canceled / DeadlineExceeded：客户端主动关闭或超时终止（非错误）
        case codes.Canceled, codes.DeadlineExceeded:
            log.Println("Stream canceled gracefully")
            return nil

        // 🔹 Unavailable：外部处理器（例如语义路由服务）暂时不可用
        // 可以由 Envoy fallback 到默认路由
        case codes.Unavailable:
            log.Printf("ExtProc temporarily unavailable: %v", err)
            return err

        // 🔹 其他 gRPC 错误：记录日志但不中断主进程
        default:
            log.Printf("gRPC error: %v", err)
            return err
        }
    }

    // 3️⃣ 上下文取消（例如超时或手动中断）
    if errors.Is(err, context.Canceled) || errors.Is(err, context.DeadlineExceeded) {
        log.Println("Stream canceled gracefully")
        return nil
    }

    // 4️⃣ 其他未知错误：记录警告日志
    log.Printf("Unexpected error receiving request: %v", err)
    return err
}

```

#### 优雅降级

```go
// =====================================================
// 🧭 优雅降级 (Graceful Degradation)
// =====================================================

// handleClassificationFailure 用于在语义分类失败时提供安全回退。
// 无论是分类器崩溃、模型加载失败，还是输入异常，系统都会回退到默认模型。
func (r *OpenAIRouter) handleClassificationFailure(
    query string, 
    err error,
) *RoutingDecision {
    log.Printf("Classification failed: %v, using fallback", err)
    
    // 1️⃣ 增加分类失败计数指标（用于 Prometheus 或日志监控）
    classificationFailures.Inc()
    
    // 2️⃣ 构造一个安全的回退决策对象
    // Fallback 模型通常是通用大模型（如 qwen-max），确保功能可用
    return &RoutingDecision{
        Category:       "general",                  // 回退到通用类别
        Confidence:     0.0,                        // 置信度为0，表示无预测结果
        SelectedModel:  r.Config.DefaultModel,      // 使用配置文件中的默认模型
        Fallback:       true,                       // 标记此为降级决策
        FailureReason:  err.Error(),                // 记录失败原因（便于调试）
    }
}

```

‍

### 监控 ExtProc 集成

#### 跟踪关键指标

```go
// =============================================================
// 📊 ExtProc 指标监控 (Prometheus Metrics)
// =============================================================

// 定义 ExtProc 相关监控指标（Prometheus 格式）
var (
    // 1️⃣ 计数器：记录 ExtProc 处理的请求总数（按类型和状态分类）
    extprocRequestsTotal = prometheus.NewCounterVec(
        prometheus.CounterOpts{
            Name: "extproc_requests_total",
            Help: "Total ExtProc requests by type", // 按请求类型统计 ExtProc 调用次数
        },
        []string{"request_type", "status"}, // 标签：如 ("RequestBody", "success")
    )
    
    // 2️⃣ 直方图：记录 ExtProc 每种请求类型的处理耗时（秒）
    // 可用于生成延迟分布（p50, p90, p99）
    extprocProcessingDuration = prometheus.NewHistogramVec(
        prometheus.HistogramOpts{
            Name: "extproc_processing_duration_seconds",
            Help: "Time spent processing ExtProc requests",
            Buckets: []float64{
                0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0,
            }, // 毫秒到秒级延迟分布桶
        },
        []string{"request_type"}, // 标签：RequestHeaders / RequestBody / ResponseBody
    )
    
    // 3️⃣ 计数器：记录 gRPC 流错误的总次数（按错误类型分类）
    // 有助于发现网络不稳定、超时或服务不可用等问题
    extprocStreamErrors = prometheus.NewCounterVec(
        prometheus.CounterOpts{
            Name: "extproc_stream_errors_total", 
            Help: "Total ExtProc stream errors", // 按错误类型统计流错误次数
        },
        []string{"error_type"}, // 标签：如 ("io.EOF"), ("Unavailable"), ("Timeout")
    )
)

```

|指标名称|类型|描述|应用场景|
| ----------| -----------| ---------------------------| ------------------------|
|​`extproc_requests_total`|Counter|按类型统计 ExtProc 调用量|流量与请求成功率|
|​`extproc_processing_duration_seconds`|Histogram|处理延迟分布|性能优化与瓶颈定位|
|​`extproc_stream_errors_total`|Counter|gRPC 流错误次数|健康状态与网络问题监控|

‍

‍

#### 健康检查实现

```go
// =============================================================
// ❤️ ExtProc 健康检查 (Health Check Implementation)
// =============================================================

// 实现 gRPC 标准健康检查接口
// 允许 Envoy / Kubernetes 通过健康探针自动检测 ExtProc 服务状态
func (s *Server) Check(
    ctx context.Context, 
    req *grpc_health_v1.HealthCheckRequest,
) (*grpc_health_v1.HealthCheckResponse, error) {
    
    // 1️⃣ 检查分类器健康状态（例如 BERT 模型加载是否正常）
    if !s.router.Classifier.IsHealthy() {
        return &grpc_health_v1.HealthCheckResponse{
            Status: grpc_health_v1.HealthCheckResponse_NOT_SERVING,
        }, nil
    }
    
    // 2️⃣ 检查缓存系统健康状态（例如 Redis 或内存缓存是否可用）
    if !s.router.Cache.IsHealthy() {
        return &grpc_health_v1.HealthCheckResponse{
            Status: grpc_health_v1.HealthCheckResponse_NOT_SERVING,
        }, nil
    }
    
    // 3️⃣ 全部组件健康，返回正常状态
    return &grpc_health_v1.HealthCheckResponse{
        Status: grpc_health_v1.HealthCheckResponse_SERVING,
    }, nil
}

```

```yaml
grpc_health_check:
  service_name: "semantic-router"
```
