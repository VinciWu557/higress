# 语义分类服务

基于 ModernBERT 的语义分类服务，为语义路由插件提供 gRPC 接口。

## 特性

- ✅ 基于 ModernBERT 的语义分类
- ✅ 支持 5 大类别：数学、代码、医学、金融、通用
- ✅ 关键词匹配 + 模型推理混合策略
- ✅ gRPC 接口，支持单条和批量分类
- ✅ 缓存机制，提高响应速度
- ✅ Prometheus 监控指标
- ✅ Redis 缓存支持（可选）
- ✅ 配置化管理
- ✅ 健康检查

## 快速开始

### 1. 安装依赖

```bash
# 使用 uv（推荐）
uv venv
source .venv/bin/activate
uv pip install -r requirements.txt

# 或使用 pip
pip install -r requirements.txt
```

### 2. 准备模型

```bash
# 模型已创建完成，位于
models/category_classifier/
├── config.json           # 模型配置
└── pytorch_model.bin     # 分类头权重

# 如需训练新模型，运行
python3 models/create_model.py
```

### 3. 启动服务

#### 方式一：使用主入口（推荐）

```bash
python3 main.py
```

可用的命令行参数：
```bash
python3 main.py --help

# 自定义配置
python3 main.py \
    --host 0.0.0.0 \
    --port 50051 \
    --device auto \
    --log-level INFO \
    --max-workers 10 \
    --enable-cache \
    --enable-monitoring
```

#### 方式二：使用配置文件

```bash
# 创建配置文件 config.json
cat > config.json << EOF
{
  "model": {
    "model_path": "./models/category_classifier",
    "device": "auto",
    "max_length": 512
  },
  "server": {
    "host": "0.0.0.0",
    "port": 50051,
    "max_workers": 10,
    "enable_cache": true
  },
  "monitoring": {
    "enabled": true,
    "metrics_port": 8080,
    "log_level": "INFO"
  }
}
EOF

# 启动服务
python3 main.py --config config.json
```


### 4. 验证服务

#### 健康检查

```bash
# 检查端口
nc -z localhost 50051

# 或使用 Python 客户端
python3 -c "
import grpc
import sys
sys.path.insert(0, 'src')
import classifier_pb2
import classifier_pb2_grpc

channel = grpc.insecure_channel('localhost:50051')
stub = classifier_pb2_grpc.SemanticClassifierServiceStub(channel)
response = stub.HealthCheck(classifier_pb2.HealthCheckRequest(check_type='detailed'))
print(f'状态: {response.status}')
print(f'详情: {response.details}')
"
```

#### 运行单元测试

```bash
# 启动服务后，在另一个终端运行测试
python3 test_classifier.py
```

## 项目结构

```
classifier-service/
├── main.py                    # 主入口
├── requirements.txt           # 依赖列表
├── Dockerfile                 # Docker 构建文件
├── k8s-deployment.yaml        # K8s 部署配置
│
├── src/                       # 源代码
│   ├── __init__.py
│   ├── config.py              # 配置管理
│   ├── classifier.py          # 分类器实现
│   ├── server.py              # gRPC 服务
│   ├── classifier_pb2.py      # 生成的 protobuf 代码
│   └── classifier_pb2_grpc.py # 生成的 gRPC 代码
│
├── models/                    # 模型文件
│   ├── category_classifier/
│   │   ├── config.json
│   │   └── pytorch_model.bin
│   ├── create_model.py        # 模型创建脚本
│   └── train_classifier.py    # 模型训练脚本（示例）
│
└── test_classifier.py         # 单元测试
```

## 配置说明

### ModelConfig (模型配置)

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| model_path | string | "./models/category_classifier" | 模型路径 |
| device | string | "auto" | 设备选择 (auto/cpu/cuda) |
| max_length | int | 512 | 最大序列长度 |
| batch_size | int | 8 | 批处理大小 |

### ServerConfig (服务器配置)

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| host | string | "0.0.0.0" | 监听地址 |
| port | int | 50051 | 监听端口 |
| max_workers | int | 10 | 最大工作线程 |
| enable_cache | bool | true | 启用缓存 |
| cache_size | int | 1000 | 缓存大小 |
| enable_redis | bool | false | 启用 Redis |

### MonitoringConfig (监控配置)

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| enabled | bool | true | 启用监控 |
| metrics_port | int | 8080 | Prometheus 指标端口 |
| log_level | string | "INFO" | 日志级别 |

## gRPC API

### 接口定义

#### 1. Classify (单条分类)

```protobuf
message ClassificationRequest {
  string text = 1;
  string request_id = 2;
  bool cache_enabled = 3;
  map<string, string> metadata = 4;
  int32 timeout_ms = 5;
}

message ClassificationResponse {
  string category = 1;
  double confidence = 2;
  map<string, double> scores = 3;
  double latency_ms = 4;
  string method = 5;
  string model_version = 6;
  int64 timestamp = 7;
  string cache_key = 8;
}
```

#### 2. BatchClassify (批量分类)

```protobuf
message BatchClassificationRequest {
  repeated ClassificationRequest requests = 1;
}

message BatchClassificationResponse {
  repeated ClassificationResponse responses = 1;
}
```

#### 3. HealthCheck (健康检查)

```protobuf
message HealthCheckRequest {
  string check_type = 1;
}

message HealthCheckResponse {
  string status = 1;
  map<string, string> stats = 2;
  int64 timestamp = 3;
  string details = 4;
}
```

### 使用示例

#### Python 客户端

```python
import grpc
import classifier_pb2
import classifier_pb2_grpc

# 建立连接
channel = grpc.insecure_channel('localhost:50051')
stub = classifier_pb2_grpc.SemanticClassifierServiceStub(channel)

# 单条分类
request = classifier_pb2.ClassificationRequest(
    text="求解方程 x^2 + 2x - 3 = 0",
    request_id="test_001",
    cache_enabled=True
)
response = stub.Classify(request)

print(f"类别: {response.category}")
print(f"置信度: {response.confidence:.3f}")
print(f"延迟: {response.latency_ms:.1f}ms")

# 批量分类
requests = [
    classifier_pb2.ClassificationRequest(text="1+1等于多少？", request_id="batch_1"),
    classifier_pb2.ClassificationRequest(text="写一个Hello World", request_id="batch_2"),
]
batch_response = stub.BatchClassify(classifier_pb2.BatchClassificationRequest(requests=requests))
```

#### Go 客户端

```go
import (
    "context"
    pb "github.com/alibaba/higress/plugins/golang-filter/semantic-router/proto"
    "google.golang.org/grpc"
)

conn, _ := grpc.Dial("localhost:50051", grpc.WithInsecure())
defer conn.Close()

client := pb.NewSemanticClassifierServiceClient(conn)
resp, _ := client.Classify(context.Background(), &pb.ClassificationRequest{
    Text:        "求解方程 x^2 + 2x - 3 = 0",
    RequestId:   "test_001",
    CacheEnabled: true,
})

fmt.Printf("类别: %s\n", resp.Category)
fmt.Printf("置信度: %.3f\n", resp.Confidence)
```

## 性能

### 延迟目标

- ✅ **分类推理延迟**: < 30ms (p99)
- ✅ **缓存命中延迟**: < 5ms
- ✅ **gRPC 调用延迟**: < 50ms 总延迟

### 性能测试

```bash
# 启动服务后，运行性能测试
python3 -c "
import time
import grpc
import sys
sys.path.insert(0, 'src')
import classifier_pb2
import classifier_pb2_grpc

channel = grpc.insecure_channel('localhost:50051')
stub = classifier_pb2_grpc.SemanticClassifierServiceStub(channel)

# 测试100次分类
times = []
for i in range(100):
    start = time.time()
    resp = stub.Classify(classifier_pb2.ClassificationRequest(
        text=f'测试问题 {i}',
        request_id=f'perf_{i}'
    ))
    times.append((time.time() - start) * 1000)

avg = sum(times) / len(times)
p99 = sorted(times)[int(len(times) * 0.99)]
print(f'平均延迟: {avg:.2f}ms')
print(f'P99延迟: {p99:.2f}ms')
"
```

## 监控

### Prometheus 指标

当监控启用时，服务在 `http://localhost:8080/metrics` 提供指标：

```
# 分类请求计数
classification_requests_total{method="model",category="math"} 100

# 分类延迟（秒）
classification_latency_seconds{method="model"} 0.025

# 缓存命中
cache_hits_total 50
cache_misses_total 10
```

### 健康检查

```bash
# 基本健康检查
curl http://localhost:8080/health

# 或使用 gRPC
python3 -c "
import grpc
import sys
sys.path.insert(0, 'src')
import classifier_pb2
import classifier_pb2_grpc

channel = grpc.insecure_channel('localhost:50051')
stub = classifier_pb2_grpc.SemanticClassifierServiceStub(channel)
resp = stub.HealthCheck(classifier_pb2.HealthCheckRequest(check_type='detailed'))
print(resp.status)
print(resp.details)
print(resp.stats)
"
```

## 部署

### Docker 部署

```bash
# 构建镜像
docker build -t semantic-classifier:latest .

# 运行容器
docker run -d \
    --name classifier-service \
    -p 50051:50051 \
    -p 8080:8080 \
    semantic-classifier:latest
```

### Kubernetes 部署

```bash
# 部署到 K8s
kubectl apply -f k8s-deployment.yaml

# 查看状态
kubectl get pods -l app=semantic-classifier

# 查看日志
kubectl logs -f deployment/semantic-classifier
```

## 故障排除

### 常见问题

#### 1. 模型加载失败

```
ERROR: 无法从模型路径加载分词器
```

**解决方案**:
```bash
# 检查模型文件是否存在
ls -la models/category_classifier/

# 如果缺失，重新创建模型
python3 models/create_model.py
```

#### 2. 端口被占用

```
ERROR: Address already in use
```

**解决方案**:
```bash
# 查看端口占用
lsof -i :50051

# 杀死占用进程
kill -9 <PID>

# 或使用其他端口
python3 main.py --port 50052
```

#### 3. CUDA 不可用

```
WARNING: 无法使用 GPU，自动切换到 CPU
```

**解决方案**:
```bash
# 强制使用 CPU
python3 main.py --device cpu

# 或检查 CUDA 安装
python3 -c "import torch; print(torch.cuda.is_available())"
```

### 日志

默认日志位置：
- 控制台输出（INFO 级别）
- `logs/classifier_service.log`（文件日志）

查看实时日志：
```bash
tail -f logs/classifier_service.log
```

## 开发

### 添加新类别

1. 修改 `src/config.py` 中的 `CategoryConfig`:
```python
categories = ["math", "code", "medical", "finance", "general", "new_category"]
```

2. 重新创建模型：
```bash
python3 models/create_model.py
```

3. 重启服务

### 训练自定义模型

参考 `models/train_classifier.py`，实现以下步骤：

1. 准备训练数据
2. 加载预训练模型
3. 添加分类头
4. 训练模型
5. 保存权重

## 版本历史

- **v1.0** (当前版本)
  - 初始发布
  - 支持 5 类分类
  - gRPC 接口
  - 缓存机制
  - 监控指标

## 许可证

MIT License

## 贡献

欢迎提交 Issue 和 Pull Request！

## 联系方式

- 项目地址: https://github.com/alibaba/higress
- 文档: https://higress.io
