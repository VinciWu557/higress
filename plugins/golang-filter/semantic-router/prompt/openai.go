package prompt

import (
    "github.com/tidwall/gjson"
)

// ExtractPromptFromOpenAIBody 从OpenAI风格请求体中提取用户的最后一条消息
// 支持 { messages: [{role:"user", content:"..."}, ...] }
func ExtractPromptFromOpenAIBody(body []byte) string {
    messages := gjson.GetBytes(body, "messages")
    if !messages.Exists() || !messages.IsArray() {
        // 兼容：如果没有messages，尝试从"input"或"prompt"字段获取
        if p := gjson.GetBytes(body, "prompt"); p.Exists() {
            return p.String()
        }
        if i := gjson.GetBytes(body, "input"); i.Exists() {
            return i.String()
        }
        return ""
    }
    var last string
    messages.ForEach(func(_, v gjson.Result) bool {
        role := v.Get("role").String()
        content := v.Get("content").String()
        if role == "user" && content != "" {
            last = content
        }
        return true
    })
    return last
}