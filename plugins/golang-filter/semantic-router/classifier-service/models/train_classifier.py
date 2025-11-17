#!/usr/bin/env python3
"""
训练分类器脚本示例
用于训练 ModernBERT 分类头

实际使用时请根据需要修改训练逻辑和数据路径
"""

import torch
import torch.nn as nn
from transformers import AutoModel, AutoTokenizer, AutoConfig
import json
import os

# 类别定义
CATEGORIES = ["math", "code", "medical", "finance", "general"]
NUM_LABELS = len(CATEGORIES)
MODEL_PATH = "./models/category_classifier"
PRETRAINED_MODEL = "bert-base-uncased"

def create_model():
    """创建分类模型"""
    # 加载预训练模型
    print(f"加载预训练模型: {PRETRAINED_MODEL}")
    config = AutoConfig.from_pretrained(PRETRAINED_MODEL)
    tokenizer = AutoTokenizer.from_pretrained(PRETRAINED_MODEL)
    base_model = AutoModel.from_pretrained(PRETRAINED_MODEL)

    # 创建分类头
    classifier_head = nn.Linear(config.hidden_size, NUM_LABELS)
    classifier_head.weight.data.normal_(mean=0.0, std=0.02)
    classifier_head.bias.data.zero_()

    # 保存配置
    os.makedirs(MODEL_PATH, exist_ok=True)
    with open(f"{MODEL_PATH}/config.json", "w") as f:
        json.dump({
            "model_type": "bert",
            "num_labels": NUM_LABELS,
            "id2label": {i: cat for i, cat in enumerate(CATEGORIES)},
            "label2id": {cat: i for i, cat in enumerate(CATEGORIES)},
            "hidden_size": config.hidden_size,
            "pretrain_model": PRETRAINED_MODEL,
        }, f, indent=2)

    print(f"模型配置已保存到: {MODEL_PATH}/config.json")
    print("注意: 这是一个初始化的模型权重，未经过训练")
    print("要获得准确的分类结果，请使用真实数据进行训练")

    return classifier_head, tokenizer

if __name__ == "__main__":
    print("创建分类器模型...")
    classifier_head, tokenizer = create_model()
    print("模型创建完成！")
    print("\n要训练模型，请:")
    print("1. 准备训练数据")
    print("2. 实现训练循环")
    print("3. 保存训练后的权重")
