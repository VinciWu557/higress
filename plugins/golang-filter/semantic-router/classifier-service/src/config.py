#!/usr/bin/env python3
"""
分类服务配置管理
"""

from dataclasses import dataclass
from typing import Dict, List, Optional
import os


@dataclass
class ModelConfig:
    """模型配置"""
    model_path: str = "./models/category_classifier"
    device: str = "auto"
    max_length: int = 512
    batch_size: int = 8
    num_labels: int = 5


@dataclass
class ServerConfig:
    """服务器配置"""
    host: str = "0.0.0.0"
    port: int = 50051
    max_workers: int = 10
    enable_cache: bool = True
    cache_size: int = 1000
    cache_ttl: int = 3600
    enable_redis: bool = False
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0


@dataclass
class CategoryConfig:
    """类别配置"""
    categories: List[str] = None

    def __post_init__(self):
        if self.categories is None:
            self.categories = [
                "math",
                "code",
                "medical",
                "finance",
                "general"
            ]


@dataclass
class MonitoringConfig:
    """监控配置"""
    enabled: bool = True
    metrics_port: int = 8080
    log_level: str = "INFO"


@dataclass
class ClassifierConfig:
    """完整配置"""
    model: ModelConfig
    server: ServerConfig
    category: CategoryConfig
    monitoring: MonitoringConfig

    @classmethod
    def from_env(cls) -> "ClassifierConfig":
        """从环境变量加载配置"""
        return cls(
            model=ModelConfig(
                model_path=os.getenv("MODEL_PATH", "./models/category_classifier"),
                device=os.getenv("DEVICE", "auto"),
                max_length=int(os.getenv("MAX_LENGTH", "512")),
            ),
            server=ServerConfig(
                host=os.getenv("SERVER_HOST", "0.0.0.0"),
                port=int(os.getenv("SERVER_PORT", "50051")),
                max_workers=int(os.getenv("MAX_WORKERS", "10")),
                enable_cache=os.getenv("ENABLE_CACHE", "true").lower() == "true",
            ),
            category=CategoryConfig(),
            monitoring=MonitoringConfig(
                enabled=os.getenv("MONITORING_ENABLED", "true").lower() == "true",
                metrics_port=int(os.getenv("METRICS_PORT", "8080")),
                log_level=os.getenv("LOG_LEVEL", "INFO"),
            ),
        )

    @classmethod
    def from_dict(cls, config_dict: dict) -> "ClassifierConfig":
        """从字典加载配置"""
        return cls(
            model=ModelConfig(**config_dict.get("model", {})),
            server=ServerConfig(**config_dict.get("server", {})),
            category=CategoryConfig(**config_dict.get("category", {})),
            monitoring=MonitoringConfig(**config_dict.get("monitoring", {})),
        )


def get_config() -> ClassifierConfig:
    """获取配置实例"""
    return ClassifierConfig.from_env()


# 预定义配置常量
CATEGORY_ID_MAPPING = {
    "math": 0,
    "code": 1,
    "medical": 2,
    "finance": 3,
    "general": 4,
}

ID_CATEGORY_MAPPING = {v: k for k, v in CATEGORY_ID_MAPPING.items()}
