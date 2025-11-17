package cache

import (
    "sync"
    "time"
)

// Manager 简易内存缓存，支持TTL与最大容量
type Manager struct {
    enabled  bool
    ttl      time.Duration
    maxSize  int
    mu       sync.RWMutex
    entries  map[string]*entry
}

type entry struct {
    value      interface{}
    expiresAt  time.Time
    lastAccess time.Time
}

func New(enabled bool, ttlSeconds int, maxSize int) *Manager {
    m := &Manager{
        enabled: enabled,
        ttl:     time.Duration(ttlSeconds) * time.Second,
        maxSize: maxSize,
        entries: make(map[string]*entry),
    }
    return m
}

func (m *Manager) Get(key string) (interface{}, bool) {
    if !m.enabled {
        return nil, false
    }
    m.mu.RLock()
    e, ok := m.entries[key]
    m.mu.RUnlock()
    if !ok {
        return nil, false
    }
    if time.Now().After(e.expiresAt) {
        m.mu.Lock()
        delete(m.entries, key)
        m.mu.Unlock()
        return nil, false
    }
    m.mu.Lock()
    e.lastAccess = time.Now()
    m.mu.Unlock()
    return e.value, true
}

func (m *Manager) Set(key string, val interface{}) {
    if !m.enabled {
        return
    }
    m.mu.Lock()
    defer m.mu.Unlock()
    if len(m.entries) >= m.maxSize {
        // 简易LRU：踢出最久未访问的条目
        var oldestKey string
        var oldestTime time.Time
        for k, v := range m.entries {
            if oldestKey == "" || v.lastAccess.Before(oldestTime) {
                oldestKey = k
                oldestTime = v.lastAccess
            }
        }
        if oldestKey != "" {
            delete(m.entries, oldestKey)
        }
    }
    m.entries[key] = &entry{
        value:      val,
        expiresAt:  time.Now().Add(m.ttl),
        lastAccess: time.Now(),
    }
}