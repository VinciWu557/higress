#!/usr/bin/env python3
"""
ModernBERT 分类器实现
封装模型加载、推理和缓存逻辑
"""

import time
import logging
from typing import Dict, Tuple, Optional
import torch
import torch.nn as nn
import numpy as np
from transformers import AutoTokenizer, AutoModel

from .config import ModelConfig, CategoryConfig, CATEGORY_ID_MAPPING, ID_CATEGORY_MAPPING

logger = logging.getLogger(__name__)


class SemanticClassifier:
    """语义分类器"""

    def __init__(self, model_config: ModelConfig, category_config: CategoryConfig):
        self.config = model_config
        self.categories = category_config.categories
        self.num_labels = len(self.categories)

        # 设备选择
        if model_config.device == "auto":
            self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        else:
            self.device = torch.device(model_config.device)

        logger.info(f"使用设备: {self.device}")

        # 模型版本
        self.model_version = "modernbert-v1.0"

        # 初始化组件
        self.tokenizer = None
        self.model = None
        self.classifier_head = None

        # 缓存
        self._cache = {}

        self._load_model()

    def _load_model(self):
        """加载模型和分词器"""
        try:
            logger.info(f"正在加载模型: {self.config.model_path}")

            # 加载分词器
            try:
                self.tokenizer = AutoTokenizer.from_pretrained(self.config.model_path)
                logger.info("分词器加载成功")
            except Exception as e:
                logger.warning(f"无法从模型路径加载分词器: {e}")
                logger.info("使用默认分词器 (bert-base-uncased)")
                self.tokenizer = AutoTokenizer.from_pretrained("bert-base-uncased")

            # 加载基础模型
            try:
                self.model = AutoModel.from_pretrained(self.config.model_path)
                self.model.to(self.device)
                self.model.eval()
                logger.info("基础模型加载成功")
            except Exception as e:
                logger.warning(f"无法从模型路径加载模型: {e}")
                logger.info("使用默认模型 (bert-base-uncased)")
                self.model = AutoModel.from_pretrained("bert-base-uncased")
                self.model.to(self.device)
                self.model.eval()

            # 创建分类头
            hidden_size = self.model.config.hidden_size
            self.classifier_head = nn.Linear(hidden_size, self.num_labels).to(self.device)

            # 尝试加载训练好的权重
            try:
                state_dict = torch.load(
                    f"{self.config.model_path}/pytorch_model.bin",
                    map_location=self.device
                )
                self.classifier_head.load_state_dict(state_dict)
                logger.info("分类头权重加载成功")
            except Exception as e:
                logger.warning(f"无法加载分类头权重: {e}")
                logger.info("使用初始化权重")

            logger.info("模型加载完成")

        except Exception as e:
            logger.error(f"模型加载失败: {e}")
            raise

    def classify(self, text: str) -> Tuple[str, float, Dict[str, float]]:
        """
        分类单个文本

        Args:
            text: 待分类文本

        Returns:
            Tuple[category, confidence, scores]:
                category: 预测类别
                confidence: 置信度
                scores: 所有类别的得分
        """
        start_time = time.time()

        # 检查缓存
        cache_key = hash(text)
        if cache_key in self._cache:
            cached_result = self._cache[cache_key]
            # 检查是否过期 (1小时)
            if time.time() - cached_result["timestamp"] < 3600:
                cached_result["method"] = "cache"
                cached_result["latency_ms"] = (time.time() - start_time) * 1000
                logger.debug(f"缓存命中: {text[:50]}...")
                return (
                    cached_result["category"],
                    cached_result["confidence"],
                    cached_result["scores"]
                )

        # 关键词匹配（作为快速路径）
        scores = self._keyword_scoring(text)

        # 使用预训练模型进行推理（如果有可用模型）
        if self.tokenizer and self.model and self.classifier_head:
            try:
                # Tokenize
                inputs = self.tokenizer(
                    text,
                    return_tensors="pt",
                    truncation=True,
                    padding=True,
                    max_length=self.config.max_length
                ).to(self.device)

                # 推理
                with torch.no_grad():
                    outputs = self.model(**inputs)
                    # 使用[CLS] token的表示
                    cls_embedding = outputs.last_hidden_state[:, 0, :]

                    # 分类预测
                    logits = self.classifier_head(cls_embedding)
                    probabilities = torch.softmax(logits, dim=-1)

                    # 获取预测结果
                    probs = probabilities[0].cpu().numpy()
                    predicted_id = int(np.argmax(probs))
                    confidence = float(probs[predicted_id])

                    # 构建所有类别的得分
                    for i, prob in enumerate(probs):
                        category = ID_CATEGORY_MAPPING[i]
                        scores[category] = max(scores.get(category, 0), float(prob))

            except Exception as e:
                logger.warning(f"模型推理失败: {e}")

        # 归一化得分
        total_score = sum(scores.values())
        if total_score > 0:
            for category in scores:
                scores[category] /= total_score
        else:
            # 如果没有匹配，使用均匀分布
            scores = {cat: 1.0/self.num_labels for cat in self.categories}

        # 获取最终预测
        category = max(scores, key=scores.get)
        confidence = scores[category]

        latency = (time.time() - start_time) * 1000

        # 缓存结果
        self._cache[cache_key] = {
            "category": category,
            "confidence": confidence,
            "scores": scores,
            "timestamp": time.time()
        }

        logger.debug(f"分类完成: {category} (置信度: {confidence:.3f}, 延迟: {latency:.1f}ms)")

        return category, confidence, scores

    def _keyword_scoring(self, text: str) -> Dict[str, float]:
        """基于关键词的快速评分"""
        text_lower = text.lower()
        scores = {}

        # 关键词词典
        keywords = {
            "math": ["方程", "求解", "计算", "数学", "x^2", "+", "=", "算", "formula", "calculate"],
            "code": ["代码", "函数", "python", "java", "编程", "实现", "程序", "code", "function"],
            "medical": ["病", "症", "药", "医生", "医学", "头痛", "症状", "disease", "medical"],
            "finance": ["投资", "回报率", "金融", "银行", "利息", "股票", "finance", "investment"],
            "general": ["天气", "怎么样", "什么", "如何", "今天", "how", "what", "weather"]
        }

        for category in self.categories:
            score = 0.0
            if category in keywords:
                for keyword in keywords[category]:
                    if keyword in text_lower:
                        score += 0.2
            scores[category] = score

        return scores

    def get_stats(self) -> Dict:
        """获取统计信息"""
        return {
            "model_version": self.model_version,
            "device": str(self.device),
            "cache_size": len(self._cache),
            "categories": self.categories,
        }

    def clear_cache(self):
        """清空缓存"""
        self._cache.clear()
        logger.info("缓存已清空")
