package client

// ClassificationResult 分类结果
type ClassificationResult struct {
	Category   string            `json:"category"`
	Confidence float64           `json:"confidence"`
	Scores     map[string]float64 `json:"scores"`
	Method     string            `json:"method"`
	LatencyMs  float64           `json:"latency_ms"`
}