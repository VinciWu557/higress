package client

import (
    "context"
    "crypto/tls"
    "fmt"
    "time"

    pb "github.com/alibaba/higress/plugins/golang-filter/semantic-router/proto"
    "google.golang.org/grpc"
    "google.golang.org/grpc/credentials"
    "google.golang.org/grpc/credentials/insecure"
)

// 使用真实的 gRPC 客户端实现，需要在构建时开启构建标签：semantic_router_grpc

// GRPCClassifierClient 真实gRPC分类器客户端
type GRPCClassifierClient struct {
    addr      string
    timeout   time.Duration
    enableTLS bool
    conn      *grpc.ClientConn
    stub      pb.SemanticClassifierServiceClient
}

// New 创建客户端并建立连接
func New(host string, port int, timeoutMs int, enableTLS bool) (*GRPCClassifierClient, error) {
    if host == "" || port <= 0 {
        return nil, fmt.Errorf("invalid classifier service address")
    }
    addr := fmt.Sprintf("%s:%d", host, port)
    var creds credentials.TransportCredentials
    if enableTLS {
        // 简单TLS，如需自签名证书可扩展CA加载
        creds = credentials.NewTLS(&tls.Config{MinVersion: tls.VersionTLS12})
    } else {
        creds = insecure.NewCredentials()
    }
    conn, err := grpc.Dial(
        addr,
        grpc.WithTransportCredentials(creds),
        grpc.WithDefaultCallOptions(grpc.WaitForReady(true)),
    )
    if err != nil {
        return nil, fmt.Errorf("grpc dial failed: %w", err)
    }
    return &GRPCClassifierClient{
        addr:      addr,
        timeout:   time.Duration(timeoutMs) * time.Millisecond,
        enableTLS: enableTLS,
        conn:      conn,
        stub:      pb.NewSemanticClassifierServiceClient(conn),
    }, nil
}

// Classify 调用分类接口
func (c *GRPCClassifierClient) Classify(ctx context.Context, text string, cacheEnabled bool) (*ClassificationResult, error) {
    var cancel context.CancelFunc
    if c.timeout > 0 {
        ctx, cancel = context.WithTimeout(ctx, c.timeout)
        defer cancel()
    }
    start := time.Now()
    req := &pb.ClassificationRequest{
        Text:         text,
        RequestId:    fmt.Sprintf("req_%d", time.Now().UnixNano()),
        CacheEnabled: cacheEnabled,
        TimeoutMs:    int32(c.timeout.Milliseconds()),
    }
    resp, err := c.stub.Classify(ctx, req)
    if err != nil {
        return nil, err
    }
    return &ClassificationResult{
        Category:   resp.GetCategory(),
        Confidence: resp.GetConfidence(),
        Scores:     resp.GetScores(),
        Method:     resp.GetMethod(),
        LatencyMs:  time.Since(start).Seconds() * 1000,
    }, nil
}

// HealthCheck 健康检查
func (c *GRPCClassifierClient) HealthCheck(ctx context.Context, detailed bool) (string, error) {
    var cancel context.CancelFunc
    if c.timeout > 0 {
        ctx, cancel = context.WithTimeout(ctx, c.timeout)
        defer cancel()
    }
    req := &pb.HealthCheckRequest{CheckType: map[bool]string{true: "detailed", false: "basic"}[detailed]}
    resp, err := c.stub.HealthCheck(ctx, req)
    if err != nil {
        return "", err
    }
    return resp.GetStatus(), nil
}

// Close 关闭连接
func (c *GRPCClassifierClient) Close() error {
    if c.conn != nil {
        return c.conn.Close()
    }
    return nil
}