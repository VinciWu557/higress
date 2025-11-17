package semantic_router

import (
    xds "github.com/cncf/xds/go/xds/type/v3"
    "github.com/envoyproxy/envoy/contrib/golang/common/go/api"
    "google.golang.org/protobuf/types/known/anypb"
)

// 插件名称与版本
const (
    Name    = "semantic-router"
    Version = "1.0.0"
)

// ClassifierServiceConfig 分类器服务配置
type ClassifierServiceConfig struct {
    ServiceHost     string
    ServicePort     int
    TimeoutMs       int
    EnableTLS       bool
    ConnectionPool  ConnectionPoolConfig
    Retry           RetryConfig
}

// ConnectionPoolConfig 连接池配置
type ConnectionPoolConfig struct {
    MaxConnections  int
    MaxIdleTimeMs   int
}

// RetryConfig 重试配置
type RetryConfig struct {
    MaxRetries         int
    InitialIntervalMs  int
    MaxIntervalMs      int
    BackoffMultiplier  float64
}

// RoutingConfig 路由策略配置
type RoutingConfig struct {
    ModelMapping        map[string]string
    DefaultModel        string
    ConfidenceThreshold float64
}

// CacheConfig 缓存配置
type CacheConfig struct {
    Enabled    bool
    TTLSeconds int
    MaxSize    int
}

// DataCollectionConfig 数据收集配置
type DataCollectionConfig struct {
    Enabled         bool
    SamplingRate    float64 // 0.0 - 1.0
    StorageEndpoint string  // 例如 http://data-collector:8080/collect
    BatchSize       int
    FlushInterval   int // 秒
}

// MonitoringConfig 监控配置
type MonitoringConfig struct {
    Enabled             bool
    MetricsEndpoint     string
    HealthCheckInterval int
}

// PluginConfig 插件总配置
type PluginConfig struct {
    ClassifierService ClassifierServiceConfig
    Routing           RoutingConfig
    Cache             CacheConfig
    LogLevel          string
    DataCollection    DataCollectionConfig
    Monitoring        MonitoringConfig
}

// configWrapper 内部运行时配置包装
type configWrapper struct {
    cfg PluginConfig
}

// Parser 配置解析器
type Parser struct{}

// Parse 解析 TypedStruct 到内部配置结构
func (p *Parser) Parse(any *anypb.Any, callbacks api.ConfigCallbackHandler) (interface{}, error) {
    ts := &xds.TypedStruct{}
    if err := any.UnmarshalTo(ts); err != nil {
        return nil, err
    }
    v := ts.Value.AsMap()

    // 初始化默认配置
    cfg := PluginConfig{
        ClassifierService: ClassifierServiceConfig{
            ServiceHost: "semantic-classifier-service.default.svc.cluster.local",
            ServicePort: 50051,
            TimeoutMs:   3000,
            EnableTLS:   false,
            ConnectionPool: ConnectionPoolConfig{
                MaxConnections: 16,
                MaxIdleTimeMs:  300000,
            },
            Retry: RetryConfig{
                MaxRetries:        3,
                InitialIntervalMs: 100,
                MaxIntervalMs:     5000,
                BackoffMultiplier: 2.0,
            },
        },
        Routing: RoutingConfig{
            ModelMapping: map[string]string{
                "math":    "qwen-math-7b",
                "code":    "qwen-code-7b",
                "medical": "qwen-medical-7b",
                "finance": "qwen-finance-7b",
                "general": "qwen-turbo",
            },
            DefaultModel:        "qwen-turbo",
            ConfidenceThreshold: 0.8,
        },
        Cache: CacheConfig{
            Enabled:    true,
            TTLSeconds: 3600,
            MaxSize:    10000,
        },
        LogLevel: "INFO",
        DataCollection: DataCollectionConfig{
            Enabled:         false,
            SamplingRate:    0.1,
            StorageEndpoint: "",
            BatchSize:       100,
            FlushInterval:   60,
        },
        Monitoring: MonitoringConfig{
            Enabled:             false,
            MetricsEndpoint:     "/metrics",
            HealthCheckInterval: 30,
        },
    }

    // 解析 classifier_service
    if csRaw, ok := v["classifier_service"].(map[string]interface{}); ok {
        if s, ok := csRaw["service_host"].(string); ok && s != "" { cfg.ClassifierService.ServiceHost = s }
        if p, ok := toInt(csRaw["service_port"]); ok && p > 0 { cfg.ClassifierService.ServicePort = p }
        if t, ok := toInt(csRaw["timeout_ms"]); ok && t > 0 { cfg.ClassifierService.TimeoutMs = t }
        if tls, ok := csRaw["enable_tls"].(bool); ok { cfg.ClassifierService.EnableTLS = tls }
        if poolRaw, ok := csRaw["connection_pool"].(map[string]interface{}); ok {
            if mc, ok := toInt(poolRaw["max_connections"]); ok && mc > 0 { cfg.ClassifierService.ConnectionPool.MaxConnections = mc }
            if mi, ok := toInt(poolRaw["max_idle_time_ms"]); ok && mi > 0 { cfg.ClassifierService.ConnectionPool.MaxIdleTimeMs = mi }
        }
        if retryRaw, ok := csRaw["retry"].(map[string]interface{}); ok {
            if mr, ok := toInt(retryRaw["max_retries"]); ok && mr >= 0 { cfg.ClassifierService.Retry.MaxRetries = mr }
            if ii, ok := toInt(retryRaw["initial_interval_ms"]); ok && ii >= 0 { cfg.ClassifierService.Retry.InitialIntervalMs = ii }
            if mi, ok := toInt(retryRaw["max_interval_ms"]); ok && mi >= 0 { cfg.ClassifierService.Retry.MaxIntervalMs = mi }
            if bm, ok := toFloat(retryRaw["backoff_multiplier"]); ok && bm > 0 { cfg.ClassifierService.Retry.BackoffMultiplier = bm }
        }
    }

    // 解析 routing
    if rRaw, ok := v["routing"].(map[string]interface{}); ok {
        if mmRaw, ok := rRaw["model_mapping"].(map[string]interface{}); ok {
            mm := make(map[string]string, len(mmRaw))
            for k, val := range mmRaw {
                if vs, ok := val.(string); ok { mm[k] = vs }
            }
            if len(mm) > 0 { cfg.Routing.ModelMapping = mm }
        }
        if dm, ok := rRaw["default_model"].(string); ok && dm != "" { cfg.Routing.DefaultModel = dm }
        if ct, ok := toFloat(rRaw["confidence_threshold"]); ok && ct > 0 { cfg.Routing.ConfidenceThreshold = ct }
    }

    // 解析 cache
    if cRaw, ok := v["cache"].(map[string]interface{}); ok {
        if en, ok := cRaw["enabled"].(bool); ok { cfg.Cache.Enabled = en }
        if ttl, ok := toInt(cRaw["ttl_seconds"]); ok && ttl >= 0 { cfg.Cache.TTLSeconds = ttl }
        if ms, ok := toInt(cRaw["max_size"]); ok && ms >= 0 { cfg.Cache.MaxSize = ms }
    }

    // 解析 log_level
    if lv, ok := v["log_level"].(string); ok && lv != "" { cfg.LogLevel = lv }

    // 解析 data_collection
    if dcRaw, ok := v["data_collection"].(map[string]interface{}); ok {
        if en, ok := dcRaw["enabled"].(bool); ok { cfg.DataCollection.Enabled = en }
        if sr, ok := toFloat(dcRaw["sampling_rate"]); ok { cfg.DataCollection.SamplingRate = sr }
        if se, ok := dcRaw["storage_endpoint"].(string); ok { cfg.DataCollection.StorageEndpoint = se }
        if bs, ok := toInt(dcRaw["batch_size"]); ok { cfg.DataCollection.BatchSize = bs }
        if fi, ok := toInt(dcRaw["flush_interval"]); ok { cfg.DataCollection.FlushInterval = fi }
    }

    // 解析 monitoring
    if moRaw, ok := v["monitoring"].(map[string]interface{}); ok {
        if en, ok := moRaw["enabled"].(bool); ok { cfg.Monitoring.Enabled = en }
        if me, ok := moRaw["metrics_endpoint"].(string); ok { cfg.Monitoring.MetricsEndpoint = me }
        if hi, ok := toInt(moRaw["health_check_interval"]); ok { cfg.Monitoring.HealthCheckInterval = hi }
    }

    api.LogInfof("semantic-router config loaded: host=%s port=%d default_model=%s", cfg.ClassifierService.ServiceHost, cfg.ClassifierService.ServicePort, cfg.Routing.DefaultModel)
    return &configWrapper{cfg: cfg}, nil
}

// Merge 合并父子配置
func (p *Parser) Merge(parent interface{}, child interface{}) interface{} {
    pc := parent.(*configWrapper)
    cc := child.(*configWrapper)
    // 子级覆盖父级
    merged := pc.cfg
    merged = cc.cfg
    return &configWrapper{cfg: merged}
}

// FilterFactory 创建过滤器实例
func FilterFactory(c interface{}, callbacks api.FilterCallbackHandler) api.StreamFilter {
    conf, ok := c.(*configWrapper)
    if !ok {
        panic("unexpected config type for semantic-router")
    }
    return newFilter(conf.cfg, callbacks)
}

// 辅助类型转换
func toInt(v interface{}) (int, bool) {
    switch x := v.(type) {
    case int:
        return x, true
    case int32:
        return int(x), true
    case int64:
        return int(x), true
    case float64:
        return int(x), true
    default:
        return 0, false
    }
}

func toFloat(v interface{}) (float64, bool) {
    switch x := v.(type) {
    case float32:
        return float64(x), true
    case float64:
        return x, true
    case int:
        return float64(x), true
    case int32:
        return float64(x), true
    case int64:
        return float64(x), true
    default:
        return 0, false
    }
}