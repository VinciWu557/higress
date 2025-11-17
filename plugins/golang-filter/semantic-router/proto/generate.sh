#!/bin/bash
set -e

# 生成Go语言的protobuf与gRPC代码

if ! command -v protoc >/dev/null 2>&1; then
  echo "ERROR: protoc 未安装。macOS可执行: brew install protobuf" >&2
  exit 1
fi
if ! command -v protoc-gen-go >/dev/null 2>&1; then
  echo "ERROR: protoc-gen-go 未安装。执行: go install google.golang.org/protobuf/cmd/protoc-gen-go@latest" >&2
  exit 1
fi
if ! command -v protoc-gen-go-grpc >/dev/null 2>&1; then
  echo "ERROR: protoc-gen-go-grpc 未安装。执行: go install google.golang.org/grpc/cmd/protoc-gen-go-grpc@latest" >&2
  exit 1
fi

echo "正在生成protobuf Go代码..."
protoc --go_out=. --go_opt=paths=source_relative \
       --go-grpc_out=. --go-grpc_opt=paths=source_relative \
       classifier.proto
echo "生成完成：semantic-router/proto/*.pb.go"