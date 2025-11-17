package routing

// 路由引擎：根据分类与置信度选择模型

type Config struct {
    ModelMapping        map[string]string
    DefaultModel        string
    ConfidenceThreshold float64
}

type Engine struct {
    cfg Config
}

func New(cfg Config) *Engine { return &Engine{cfg: cfg} }

// SelectModel 根据分类结果选择模型
func (e *Engine) SelectModel(category string, confidence float64) string {
    if confidence < e.cfg.ConfidenceThreshold {
        return e.cfg.DefaultModel
    }
    if m, ok := e.cfg.ModelMapping[category]; ok && m != "" {
        return m
    }
    return e.cfg.DefaultModel
}