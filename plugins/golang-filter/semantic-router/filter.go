package semantic_router

import (
	"context"
	"encoding/json"
	"fmt"
	"hash/fnv"
	"math/rand"
	"net/http"
	"strings"
	"time"

	"github.com/alibaba/higress/plugins/golang-filter/semantic-router/cache"
	"github.com/alibaba/higress/plugins/golang-filter/semantic-router/client"
	prpt "github.com/alibaba/higress/plugins/golang-filter/semantic-router/prompt"
	rengine "github.com/alibaba/higress/plugins/golang-filter/semantic-router/routing"
	"github.com/envoyproxy/envoy/contrib/golang/common/go/api"
)

// filter 语义路由过滤器
type filter struct {
	api.PassThroughStreamFilter

	callbacks api.FilterCallbackHandler
	config    PluginConfig

	// 请求体缓存
	bodyBuf  []byte
	needBody bool

	// 运行时组件
	grpc  *client.GRPCClassifierClient
	cache *cache.Manager

	// 请求头引用（在DecodeHeaders阶段获取，供后续修改）
	reqHeaders api.RequestHeaderMap

	// 路由引擎
	engine *rengine.Engine
}

// newFilter 构造过滤器实例
func newFilter(cfg PluginConfig, cb api.FilterCallbackHandler) api.StreamFilter {
	f := &filter{
		callbacks: cb,
		config:    cfg,
	}
	// 路由引擎
	f.engine = rengine.New(rengine.Config{
		ModelMapping:        cfg.Routing.ModelMapping,
		DefaultModel:        cfg.Routing.DefaultModel,
		ConfidenceThreshold: cfg.Routing.ConfidenceThreshold,
	})
	// 初始化分类客户端（占位实现，后续替换为真实gRPC）
	cli, err := client.New(cfg.ClassifierService.ServiceHost, cfg.ClassifierService.ServicePort, cfg.ClassifierService.TimeoutMs, cfg.ClassifierService.EnableTLS)
	if err != nil {
		api.LogErrorf("semantic-router: init grpc client failed: %v", err)
	} else {
		f.grpc = cli
	}
	// 初始化缓存
	f.cache = cache.New(cfg.Cache.Enabled, cfg.Cache.TTLSeconds, cfg.Cache.MaxSize)
	return f
}

// DecodeHeaders 拦截请求头，决定是否读取请求体
func (f *filter) DecodeHeaders(header api.RequestHeaderMap, endStream bool) api.StatusType {
	method := header.Method()
	// 保存请求头引用，便于后续写入路由头
	f.reqHeaders = header
	// Content-Type需通过Get读取
	ctype, _ := header.Get("content-type")

	// 仅对可能包含prompt的POST JSON请求进行处理
	if method == http.MethodPost && strings.Contains(strings.ToLower(ctype), "json") {
		f.needBody = true
		if endStream {
			// 没有body，直接继续
			return api.Continue
		}
		return api.StopAndBuffer
	}
	return api.Continue
}

// DecodeData 累积请求体并在endStream时执行分类与路由决策
func (f *filter) DecodeData(buffer api.BufferInstance, endStream bool) api.StatusType {
	if !f.needBody {
		return api.Continue
	}
	// 累积请求体
	f.bodyBuf = append(f.bodyBuf, buffer.Bytes()...)
	if !endStream {
		return api.StopAndBuffer
	}

	// 解析prompt
	prompt := prpt.ExtractPromptFromOpenAIBody(f.bodyBuf)
	if prompt == "" {
		// 无有效prompt，直接继续
		return api.Continue
	}

	// 缓存命中检查
	cacheKey := fmt.Sprintf("sr:%s", hashText(prompt))
	if v, ok := f.cache.Get(cacheKey); ok {
		if res, ok2 := v.(*client.ClassificationResult); ok2 {
			f.applyRouting(res)
			f.needBody = false
			return api.Continue
		}
	}

	// 调用分类（占位实现）
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	res, err := f.grpc.Classify(ctx, prompt, f.config.Cache.Enabled)
	if err != nil {
		api.LogWarnf("semantic-router: classify failed: %v", err)
		// 降级：使用默认模型
		f.setHeaders("general", f.config.Routing.ConfidenceThreshold-0.1, f.config.Routing.DefaultModel, "fallback")
		f.needBody = false
		return api.Continue
	}

	// 缓存保存
	f.cache.Set(cacheKey, res)
	// 应用路由
	f.applyRouting(res)
	f.needBody = false
	return api.Continue
}

// EncodeHeaders 这里不做响应方向处理
func (f *filter) EncodeHeaders(header api.ResponseHeaderMap, endStream bool) api.StatusType {
	return api.Continue
}

// EncodeData 不改动响应体
func (f *filter) EncodeData(buffer api.BufferInstance, endStream bool) api.StatusType {
	return api.Continue
}

// applyRouting 根据分类结果选择模型并写入请求头
func (f *filter) applyRouting(res *client.ClassificationResult) {
	// 选择模型
	model := f.engine.SelectModel(res.Category, res.Confidence)
	// 写头
	f.setHeaders(res.Category, res.Confidence, model, res.Method)
	// 数据收集（异步）
	f.maybeCollect(model, res)
}


// setHeaders 设置路由相关头部
func (f *filter) setHeaders(category string, confidence float64, model string, method string) {
	if f.reqHeaders == nil {
		return
	}
	f.reqHeaders.Set("X-Target-Model", model)
	f.reqHeaders.Set("X-Classification", category)
	f.reqHeaders.Set("X-Confidence", fmt.Sprintf("%.3f", confidence))
	f.reqHeaders.Set("X-Classification-Method", method)
	f.reqHeaders.Set("X-Routing-Method", "semantic")
}

// 数据收集：满足采样率时将分类结果与prompt概要上报到外部端点
func (f *filter) maybeCollect(model string, res *client.ClassificationResult) {
	dc := f.config.DataCollection
	if !dc.Enabled || dc.StorageEndpoint == "" {
		return
	}
	// 采样
	rand.Seed(time.Now().UnixNano())
	if rand.Float64() > dc.SamplingRate {
		return
	}
	// 构造上报数据（不包含原始全文，避免隐私泄露；附上分类与模型选择）
	payload := map[string]interface{}{
		"category":   res.Category,
		"confidence": res.Confidence,
		"scores":     res.Scores,
		"model":      model,
		"method":     res.Method,
		"timestamp":  time.Now().Unix(),
	}
	b, _ := json.Marshal(payload)
	go func(url string, body []byte) {
		req, _ := http.NewRequest(http.MethodPost, url, strings.NewReader(string(body)))
		req.Header.Set("Content-Type", "application/json")
		client := &http.Client{Timeout: 2 * time.Second}
		if resp, err := client.Do(req); err != nil {
			api.LogWarnf("semantic-router: data collection failed: %v", err)
		} else {
			_ = resp.Body.Close()
		}
	}(dc.StorageEndpoint, b)
}

// hashText 使用 FNV-1a 算法计算文本哈希
func hashText(text string) string {
	h := fnv.New64a()
	h.Write([]byte(text))
	return fmt.Sprintf("%x", h.Sum64())
}
