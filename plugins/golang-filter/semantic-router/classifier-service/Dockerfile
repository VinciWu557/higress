# 使用Python 3.11作为基础镜像
FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# 复制requirements文件
COPY requirements.txt .

# 安装Python依赖
RUN pip install --no-cache-dir -r requirements.txt

# 复制源代码
COPY proto/ ./proto/
COPY src/ ./src/
COPY models/ ./models/

# 生成protobuf代码
RUN cd proto && python3 -m grpc_tools.protoc \
    --python_out=../src \
    --grpc_python_out=../src \
    --proto_path=. \
    classifier.proto

# 创建日志目录
RUN mkdir -p logs

# 设置环境变量
ENV PYTHONPATH=/app/src
ENV PYTHONUNBUFFERED=1

# 暴露端口
EXPOSE 50051 8080

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python3 -c "import grpc; import sys; sys.path.append('/app/src'); import classifier_pb2_grpc, classifier_pb2; \
    channel = grpc.insecure_channel('localhost:50051'); \
    stub = classifier_pb2_grpc.SemanticClassifierServiceStub(channel); \
    request = classifier_pb2.HealthCheckRequest(check_type='basic'); \
    response = stub.HealthCheck(request); \
    exit(0 if response.status == 'healthy' else 1)"

# 启动服务
CMD ["python3", "src/server.py"]