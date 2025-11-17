#!/bin/bash

# Python protobuf代码生成脚本
# 用于生成Python语言的gRPC客户端和服务端代码

set -e

# 检查python是否安装
if ! command -v python3 &> /dev/null; then
    echo "错误: python3 未安装"
    exit 1
fi

# 检查grpcio-tools是否安装
if ! python3 -c "import grpc_tools" &> /dev/null; then
    echo "错误: grpcio-tools 未安装，请先安装"
    echo "pip install grpcio-tools"
    exit 1
fi

# 创建输出目录
mkdir -p ../src

# 生成Python代码
echo "正在生成protobuf Python代码..."
python3 -m grpc_tools.protoc \
    --python_out=../src \
    --grpc_python_out=../src \
    --proto_path=. \
    classifier.proto

echo "protobuf Python代码生成完成！"
echo "生成的文件:"
echo "  - ../src/classifier_pb2.py"
echo "  - ../src/classifier_pb2_grpc.py"