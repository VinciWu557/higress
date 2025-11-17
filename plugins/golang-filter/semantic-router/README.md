# Semantic Router (Golang HTTP Filter)

语义路由插件（原生 Go 插件），在 Envoy HTTP 过滤链中拦截请求，解析 OpenAI 风格的 `messages`，调用独立的 gRPC 分类服务（ModernBERT），并基于分类结果设置路由头，将请求分发到最合适的模型后端。

## 特性
- 语义分类：调用独立的 gRPC 分类服务（支持缓存与健康检查）
- 路由决策：根据类别与置信度阈值选择模型
- 数据采样：按 `sampling_rate` 异步上报分类结果（不含原文）到指定端点
- 可观测性：保留 `monitoring` 字段，便于后续扩展指标与健康检查

## Envoy 过滤器配置示例（typed_config）

将以下配置以 Envoy Golang HTTP Filter 的方式下发（library_path 指向构建出的 `golang-filter.so`）：

```yaml
http_filters:
- name: envoy.filters.http.golang
  typed_config:
    "@type": type.googleapis.com/envoy.extensions.filters.http.golang.v3alpha.Config
    library_id: semantic-router
    library_path: "/usr/local/higress/filters/golang-filter.so"
    plugin_name: "semantic-router"
    plugin_config:
      "@type": type.googleapis.com/xds.type.v3.TypedStruct
      value:
        classifier_service:
          service_host: "semantic-classifier-service.default.svc.cluster.local"
          service_port: 50051
          timeout_ms: 3000
          enable_tls: false
          connection_pool:
            max_connections: 16
            max_idle_time_ms: 300000
          retry:
            max_retries: 3
            initial_interval_ms: 100
            max_interval_ms: 5000
            backoff_multiplier: 2.0
        routing:
          model_mapping:
            math: "qwen-math-7b"
            code: "qwen-code-7b"
            medical: "qwen-medical-7b"
            finance: "qwen-finance-7b"
            general: "qwen-turbo"
          default_model: "qwen-turbo"
          confidence_threshold: 0.8
        cache:
          enabled: true
          ttl_seconds: 3600
          max_size: 10000
        data_collection:
          enabled: true
          sampling_rate: 0.1
          storage_endpoint: "http://data-collector:8080/collect"
          batch_size: 100
          flush_interval: 60
        monitoring:
          enabled: true
          metrics_endpoint: "/metrics"
          health_check_interval: 30
```

> 插件设置的路由相关头部：`X-Target-Model`、`X-Classification`、`X-Confidence`、`X-Classification-Method`、`X-Routing-Method`

## 构建与使用

1. 生成 Go 的 protobuf 代码（真实 gRPC 客户端）：
   - `cd plugins/golang-filter/semantic-router/proto && ./generate.sh`
   - 如缺少工具：
     - `brew install protobuf`
     - `go install google.golang.org/protobuf/cmd/protoc-gen-go@latest`
     - `go install google.golang.org/grpc/cmd/protoc-gen-go-grpc@latest`

2. 构建原生 Golang Filter：
   - `cd plugins/golang-filter && go mod tidy && make build`
   - 或在项目根目录：`make build-gateway-local`

3. 启用真实 gRPC 客户端（可选）：
   - 构建时设置构建标签：`GOFLAGS='-tags semantic_router_grpc' make build`
   - 或根据你的构建系统，在相应的构建命令中加入 `-tags semantic_router_grpc`

4. 部署分类服务（Python）：
   - 目录：`plugins/golang-filter/semantic-router/classifier-service`
   - 生成 Python gRPC 代码：
     - `cd classifier-service/proto && ./generate_python.sh`
   - 构建镜像与部署：参考 `Dockerfile` 与 `k8s-deployment.yaml`

## 设计说明
- 请求路径：`DecodeHeaders` 判断是否读取请求体（仅处理 `POST` 且 `content-type` 含 `json`）。
- 请求体：`DecodeData` 缓冲 body，在 endStream 时解析 `messages` 拿到用户 `prompt`。
- 分类调用：使用 gRPC 客户端调用分类服务（默认占位，生成 pb 后可启用真实客户端）。
- 路由头：写入目标模型与分类信息，供下游路由或上游服务使用。
- 数据采样：按 `sampling_rate` 异步 `POST` 上报分类结果摘要（不含原文）。

## FAQ
- 未生成 pb 导致无法编译真实客户端？
  - 先执行 proto 生成，再按标签构建；在不加标签的构建下，客户端走占位实现，插件会自动触发降级逻辑（使用 `default_model`）。
- 如何开启 TLS 到分类服务？
  - 在配置中设置 `classifier_service.enable_tls: true`，并在真实客户端中按需扩展 CA 加载与证书校验逻辑。