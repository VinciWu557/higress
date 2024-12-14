package provider

import (
	"errors"
	"github.com/alibaba/higress/plugins/wasm-go/extensions/ai-proxy/util"
	"github.com/alibaba/higress/plugins/wasm-go/pkg/wrapper"
	"github.com/higress-group/proxy-wasm-go-sdk/proxywasm/types"
	"net/http"
	"strings"
)

// 调用豆包大模型对话 API
const (
	doubaoDomain             = "ark.cn-beijing.volces.com"
	doubaoChatCompletionPath = "/api/v3/chat/completions"
)

// 豆包初始化
type doubaoProviderInitializer struct{}

// ValidateConfig 配置验证
func (m *doubaoProviderInitializer) ValidateConfig(config ProviderConfig) error {
	// 验证 API Token 是否存在
	if config.apiTokens == nil || len(config.apiTokens) == 0 {
		return errors.New("no apiToken found in provider config")
	}
	return nil
}

// CreateProvider 根据传入的配置创建豆包
func (m *doubaoProviderInitializer) CreateProvider(config ProviderConfig) (Provider, error) {
	return &doubaoProvider{
		config:       config,
		contextCache: createContextCache(&config),
	}, nil
}

type doubaoProvider struct {
	config       ProviderConfig
	contextCache *contextCache
}

// GetProviderType 获取供应商类型
func (m *doubaoProvider) GetProviderType() string {
	return providerTypeDoubao
}

// OnRequestHeaders 处理请求头
func (m *doubaoProvider) OnRequestHeaders(ctx wrapper.HttpContext, apiName ApiName, log wrapper.Log) (types.Action, error) {
	// 校验是否为对话补全 API
	if apiName != ApiNameChatCompletion {
		return types.ActionContinue, errUnsupportedApiName
	}
	m.config.handleRequestHeaders(m, ctx, apiName, log)
	return types.ActionContinue, nil
}

// OnRequestBody 处理请求体
func (m *doubaoProvider) OnRequestBody(ctx wrapper.HttpContext, apiName ApiName, body []byte, log wrapper.Log) (types.Action, error) {
	// 校验是否为对话补全 API
	if apiName != ApiNameChatCompletion {
		return types.ActionContinue, errUnsupportedApiName
	}
	return m.config.handleRequestBody(m, m.contextCache, ctx, apiName, body, log)
}

// TransformRequestHeaders 对请求头进行转换
func (m *doubaoProvider) TransformRequestHeaders(ctx wrapper.HttpContext, apiName ApiName, headers http.Header, log wrapper.Log) {
	// 重写路径头
	util.OverwriteRequestPathHeader(headers, doubaoChatCompletionPath)
	// 重写主机头
	util.OverwriteRequestHostHeader(headers, doubaoDomain)
	// 重写授权头
	util.OverwriteRequestAuthorizationHeader(headers, "Bearer "+m.config.GetApiTokenInUse(ctx))
	// 删除内容长度字段
	headers.Del("Content-Length")
}

func (m *doubaoProvider) GetApiName(path string) ApiName {
	if strings.Contains(path, doubaoChatCompletionPath) {
		return ApiNameChatCompletion
	}
	return ""
}
