#!/usr/bin/env python3
"""
创建初始化的分类模型文件
用于演示和启动分类服务
"""

import torch
import torch.nn as nn
import json
import os

# 类别定义
CATEGORIES = ["math", "code", "medical", "finance", "general"]
NUM_LABELS = len(CATEGORIES)
HIDDEN_SIZE = 768
MODEL_PATH = "./models/category_classifier"

def create_model():
    """创建初始化的分类模型"""
    # 创建分类头
    classifier_head = nn.Linear(HIDDEN_SIZE, NUM_LABELS)

    # 使用正态分布初始化权重
    nn.init.normal_(classifier_head.weight, mean=0.0, std=0.02)
    nn.init.zeros_(classifier_head.bias)

    # 保存模型状态字典
    os.makedirs(MODEL_PATH, exist_ok=True)
    torch.save(classifier_head.state_dict(), f"{MODEL_PATH}/pytorch_model.bin")

    print(f"分类头权重已保存到: {MODEL_PATH}/pytorch_model.bin")
    print("注意: 这是初始化的权重，未经过训练")
    print("分类服务将使用此权重进行预测，但准确率较低")
    print("要获得准确的分类结果，请使用真实数据进行训练")

if __name__ == "__main__":
    print("创建初始化分类模型...")
    create_model()
    print("模型创建完成！")
