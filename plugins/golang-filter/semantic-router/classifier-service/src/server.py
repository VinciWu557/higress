#!/usr/bin/env python3
"""
Semantic Router gRPC Classification Service

基于ModernBERT的语义分类服务，提供gRPC接口供Higress插件调用。
"""

import asyncio
import hashlib
import json
import logging
import time
from concurrent import futures
from typing import Dict, List, Optional, Tuple

import grpc
import numpy as np
import redis
import torch
from loguru import logger
from prometheus_client import Counter, Histogram, start_http_server
from transformers import AutoModel, AutoTokenizer

# 导入生成的protobuf类
import classifier_pb2
import classifier_pb2_grpc


# 监控指标
CLASSIFICATION_REQUESTS = Counter('classification_requests_total', 'Total classification requests', ['method', 'category'])
CLASSIFICATION_LATENCY = Histogram('classification_latency_seconds', 'Classification latency', ['method'])
CACHE_HITS = Counter('cache_hits_total', 'Cache hits')
CACHE_MISSES = Counter('cache_misses_total', 'Cache misses')


class ModernBERTClassifier:
    """基于ModernBERT的文本分类器"""
    
    def __init__(self, model_name: str = "answerdotai/ModernBERT-base", device: str = "auto"):
        """
        初始化ModernBERT分类器
        
        Args:
            model_name: 模型名称
            device: 设备类型 (auto/cpu/cuda)
        """
        self.model_name = model_name
        self.device = self._get_device(device)
        self.model_version = "modernbert-v1.0"
        
        logger.info(f"正在加载ModernBERT模型: {model_name}")
        logger.info(f"使用设备: {self.device}")
        
        # 加载tokenizer和模型
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        self.model = AutoModel.from_pretrained(model_name)
        self.model.to(self.device)
        self.model.eval()
        
        # 分类头 - 简单的线性分类器
        self.num_classes = 5  # math, code, medical, finance, general
        self.classifier_head = torch.nn.Linear(self.model.config.hidden_size, self.num_classes)
        self.classifier_head.to(self.device)
        
        # 类别映射
        self.id_to_label = {
            0: "math",
            1: "code", 
            2: "medical",
            3: "finance",
            4: "general"
        }
        self.label_to_id = {v: k for k, v in self.id_to_label.items()}
        
        # 初始化分类头权重（实际应用中应该从训练好的模型加载）
        self._init_classifier_weights()
        
        logger.info("ModernBERT分类器初始化完成")
    
    def _get_device(self, device: str) -> str:
        """获取计算设备"""
        if device == "auto":
            return "cuda" if torch.cuda.is_available() else "cpu"
        return device
    
    def _init_classifier_weights(self):
        """初始化分类头权重（模拟训练好的权重）"""
        with torch.no_grad():
            # 使用正态分布初始化
            torch.nn.init.normal_(self.classifier_head.weight, mean=0.0, std=0.02)
            torch.nn.init.zeros_(self.classifier_head.bias)
    
    def classify(self, text: str) -> Tuple[str, float, Dict[str, float]]:
        """
        对文本进行分类
        
        Args:
            text: 待分类的文本
            
        Returns:
            Tuple[category, confidence, scores]: 分类结果
        """
        start_time = time.time()
        
        try:
            # Tokenize输入文本
            inputs = self.tokenizer(
                text,
                return_tensors="pt",
                truncation=True,
                padding=True,
                max_length=512
            )
            inputs = {k: v.to(self.device) for k, v in inputs.items()}
            
            # 模型推理
            with torch.no_grad():
                outputs = self.model(**inputs)
                # 使用[CLS] token的表示
                cls_embedding = outputs.last_hidden_state[:, 0, :]
                
                # 分类预测
                logits = self.classifier_head(cls_embedding)
                probabilities = torch.softmax(logits, dim=-1)
                
                # 获取预测结果
                predicted_id = torch.argmax(probabilities, dim=-1).item()
                confidence = probabilities[0, predicted_id].item()
                
                # 构建所有类别的得分
                scores = {}
                for i, prob in enumerate(probabilities[0]):
                    label = self.id_to_label[i]
                    scores[label] = prob.item()
                
                category = self.id_to_label[predicted_id]
                
                latency = time.time() - start_time
                logger.debug(f"分类完成: {category} (置信度: {confidence:.3f}, 延迟: {latency:.3f}s)")
                
                return category, confidence, scores
                
        except Exception as e:
            logger.error(f"分类过程中发生错误: {e}")
            # 返回默认分类
            return "general", 0.5, {"general": 0.5}


class CacheManager:
    """Redis缓存管理器"""
    
    def __init__(self, redis_host: str = "localhost", redis_port: int = 6379, 
                 redis_db: int = 0, ttl: int = 3600):
        """
        初始化缓存管理器
        
        Args:
            redis_host: Redis主机地址
            redis_port: Redis端口
            redis_db: Redis数据库编号
            ttl: 缓存过期时间（秒）
        """
        self.ttl = ttl
        try:
            self.redis_client = redis.Redis(
                host=redis_host,
                port=redis_port,
                db=redis_db,
                decode_responses=True,
                socket_timeout=5,
                socket_connect_timeout=5
            )
            # 测试连接
            self.redis_client.ping()
            self.enabled = True
            logger.info(f"Redis缓存已启用: {redis_host}:{redis_port}/{redis_db}")
        except Exception as e:
            logger.warning(f"Redis连接失败，缓存已禁用: {e}")
            self.redis_client = None
            self.enabled = False
    
    def _generate_cache_key(self, text: str, model_version: str) -> str:
        """生成缓存键"""
        content = f"{text}:{model_version}"
        return f"classify:{hashlib.md5(content.encode()).hexdigest()}"
    
    def get(self, text: str, model_version: str) -> Optional[Dict]:
        """从缓存获取分类结果"""
        if not self.enabled:
            return None
            
        try:
            cache_key = self._generate_cache_key(text, model_version)
            cached_result = self.redis_client.get(cache_key)
            
            if cached_result:
                CACHE_HITS.inc()
                result = json.loads(cached_result)
                logger.debug(f"缓存命中: {cache_key}")
                return result
            else:
                CACHE_MISSES.inc()
                return None
                
        except Exception as e:
            logger.error(f"缓存读取失败: {e}")
            return None
    
    def set(self, text: str, model_version: str, result: Dict):
        """设置缓存"""
        if not self.enabled:
            return
            
        try:
            cache_key = self._generate_cache_key(text, model_version)
            self.redis_client.setex(
                cache_key,
                self.ttl,
                json.dumps(result)
            )
            logger.debug(f"缓存设置: {cache_key}")
            
        except Exception as e:
            logger.error(f"缓存写入失败: {e}")


class SemanticClassifierServicer(classifier_pb2_grpc.SemanticClassifierServiceServicer):
    """语义分类gRPC服务实现"""
    
    def __init__(self):
        """初始化分类服务"""
        logger.info("正在初始化语义分类服务...")
        
        # 初始化分类器
        self.classifier = ModernBERTClassifier()
        
        # 初始化缓存
        self.cache = CacheManager()
        
        # 服务统计
        self.start_time = time.time()
        self.request_count = 0
        
        logger.info("语义分类服务初始化完成")
    
    def Classify(self, request, context):
        """单个文本分类"""
        start_time = time.time()
        self.request_count += 1
        
        try:
            logger.debug(f"收到分类请求: {request.request_id}, 文本长度: {len(request.text)}")
            
            # 检查缓存
            if request.cache_enabled:
                cached_result = self.cache.get(request.text, self.classifier.model_version)
                if cached_result:
                    response = classifier_pb2.ClassificationResponse(
                        category=cached_result["category"],
                        confidence=cached_result["confidence"],
                        scores=cached_result["scores"],
                        latency_ms=(time.time() - start_time) * 1000,
                        method="cache",
                        model_version=self.classifier.model_version,
                        timestamp=int(time.time()),
                        cache_key=cached_result.get("cache_key", "")
                    )
                    
                    CLASSIFICATION_REQUESTS.labels(method="cache", category=cached_result["category"]).inc()
                    CLASSIFICATION_LATENCY.labels(method="cache").observe(time.time() - start_time)
                    
                    return response
            
            # 执行分类
            category, confidence, scores = self.classifier.classify(request.text)
            
            # 构建响应
            response = classifier_pb2.ClassificationResponse(
                category=category,
                confidence=confidence,
                scores=scores,
                latency_ms=(time.time() - start_time) * 1000,
                method="model",
                model_version=self.classifier.model_version,
                timestamp=int(time.time()),
                cache_key=""
            )
            
            # 缓存结果
            if request.cache_enabled:
                cache_data = {
                    "category": category,
                    "confidence": confidence,
                    "scores": scores,
                    "cache_key": response.cache_key
                }
                self.cache.set(request.text, self.classifier.model_version, cache_data)
            
            # 记录指标
            CLASSIFICATION_REQUESTS.labels(method="model", category=category).inc()
            CLASSIFICATION_LATENCY.labels(method="model").observe(time.time() - start_time)
            
            logger.debug(f"分类完成: {request.request_id} -> {category} ({confidence:.3f})")
            
            return response
            
        except Exception as e:
            logger.error(f"分类请求处理失败: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(f"分类处理失败: {str(e)}")
            return classifier_pb2.ClassificationResponse()
    
    def BatchClassify(self, request, context):
        """批量文本分类"""
        start_time = time.time()
        
        try:
            logger.debug(f"收到批量分类请求，数量: {len(request.requests)}")
            
            responses = []
            for req in request.requests:
                # 复用单个分类逻辑
                response = self.Classify(req, context)
                responses.append(response)
            
            batch_response = classifier_pb2.BatchClassificationResponse(
                responses=responses
            )
            
            logger.debug(f"批量分类完成，处理了 {len(responses)} 个请求，总耗时: {time.time() - start_time:.3f}s")
            
            return batch_response
            
        except Exception as e:
            logger.error(f"批量分类请求处理失败: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(f"批量分类处理失败: {str(e)}")
            return classifier_pb2.BatchClassificationResponse()
    
    def StreamClassify(self, request_iterator, context):
        """流式分类"""
        try:
            for request in request_iterator:
                response = self.Classify(request, context)
                yield response
                
        except Exception as e:
            logger.error(f"流式分类处理失败: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(f"流式分类处理失败: {str(e)}")
    
    def HealthCheck(self, request, context):
        """健康检查"""
        try:
            current_time = int(time.time())
            uptime = current_time - int(self.start_time)
            
            # 基础统计信息
            stats = {
                "uptime_seconds": str(uptime),
                "total_requests": str(self.request_count),
                "model_version": self.classifier.model_version,
                "cache_enabled": str(self.cache.enabled),
                "device": self.classifier.device
            }
            
            # 详细检查
            if request.check_type == "detailed":
                try:
                    # 测试模型推理
                    test_text = "Hello world"
                    category, confidence, scores = self.classifier.classify(test_text)
                    stats["model_test"] = "passed"
                    stats["test_category"] = category
                    stats["test_confidence"] = f"{confidence:.3f}"
                except Exception as e:
                    stats["model_test"] = f"failed: {str(e)}"
                
                # 测试缓存连接
                if self.cache.enabled:
                    try:
                        self.cache.redis_client.ping()
                        stats["cache_test"] = "passed"
                    except Exception as e:
                        stats["cache_test"] = f"failed: {str(e)}"
            
            # 确定健康状态
            status = "healthy"
            details = "服务运行正常"
            
            if request.check_type == "detailed":
                if stats.get("model_test", "").startswith("failed"):
                    status = "degraded"
                    details = "模型推理异常"
                elif stats.get("cache_test", "").startswith("failed"):
                    status = "degraded" 
                    details = "缓存连接异常"
            
            response = classifier_pb2.HealthCheckResponse(
                status=status,
                stats=stats,
                timestamp=current_time,
                details=details
            )
            
            logger.debug(f"健康检查完成: {status}")
            return response
            
        except Exception as e:
            logger.error(f"健康检查失败: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(f"健康检查失败: {str(e)}")
            return classifier_pb2.HealthCheckResponse(
                status="unhealthy",
                stats={"error": str(e)},
                timestamp=int(time.time()),
                details=f"健康检查异常: {str(e)}"
            )


def serve():
    """启动gRPC服务器"""
    # 配置日志
    logger.add("logs/classifier_service.log", rotation="100 MB", retention="7 days")
    logger.info("正在启动语义分类gRPC服务...")
    
    # 启动Prometheus监控服务器
    start_http_server(8080)
    logger.info("Prometheus监控服务已启动: http://0.0.0.0:8080")
    
    # 创建gRPC服务器
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    
    # 注册服务
    classifier_pb2_grpc.add_SemanticClassifierServiceServicer_to_server(
        SemanticClassifierServicer(), server
    )
    
    # 监听端口
    listen_addr = '[::]:50051'
    server.add_insecure_port(listen_addr)
    
    # 启动服务器
    server.start()
    logger.info(f"语义分类gRPC服务已启动，监听地址: {listen_addr}")
    
    try:
        server.wait_for_termination()
    except KeyboardInterrupt:
        logger.info("收到停止信号，正在关闭服务...")
        server.stop(0)


# 新版本：支持配置参数的 serve 函数
def serve_with_config(config):
    """
    启动 gRPC 服务器（支持配置参数）

    Args:
        config: ClassifierConfig 实例
    """
    from .config import get_config
    from .classifier import SemanticClassifier

    # 如果没有提供配置，使用默认配置
    if config is None:
        config = get_config()

    # 配置日志
    log_level = config.monitoring.log_level
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)

    # 使用标准 logging（替代 loguru）
    logging.basicConfig(
        level=numeric_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler('logs/classifier_service.log')
        ]
    )

    logger = logging.getLogger(__name__)
    logger.info("=" * 80)
    logger.info("正在启动语义分类 gRPC 服务（配置驱动模式）...")

    # 启动 Prometheus 监控服务器
    if config.monitoring.enabled:
        start_http_server(config.monitoring.metrics_port)
        logger.info(f"Prometheus 监控服务已启动: http://0.0.0.0:{config.monitoring.metrics_port}")

    # 初始化分类器
    classifier = SemanticClassifier(config.model, config.category)

    # 创建 gRPC 服务器
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=config.server.max_workers))

    # 注册服务
    classifier_pb2_grpc.add_SemanticClassifierServiceServicer_to_server(
        SemanticClassifierServicer(classifier), server
    )

    # 监听端口
    listen_addr = f'[::]:{config.server.port}'
    server.add_insecure_port(listen_addr)

    # 启动服务器
    server.start()
    logger.info(f"语义分类 gRPC 服务已启动，监听地址: {listen_addr}")
    logger.info(f"模型版本: {classifier.model_version}")
    logger.info(f"设备: {classifier.device}")
    logger.info("=" * 80)

    try:
        server.wait_for_termination()
    except KeyboardInterrupt:
        logger.info("收到停止信号，正在关闭服务...")
        server.stop(0)


if __name__ == '__main__':
    serve()