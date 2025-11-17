#!/usr/bin/env python3
"""
分类服务单元测试脚本
测试 gRPC 接口的完整功能
"""

import grpc
import sys
import os
import time

# 添加 src 目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

# 导入生成的 protobuf 代码
import classifier_pb2
import classifier_pb2_grpc

def test_classify():
    """测试分类接口"""
    print("=" * 80)
    print("  分类服务单元测试")
    print("=" * 80)

    # 连接服务
    channel = grpc.insecure_channel('localhost:50051')
    stub = classifier_pb2_grpc.SemanticClassifierServiceStub(channel)

    # 测试用例
    test_cases = [
        ("求解方程 x^2 + 2x - 3 = 0", "math", "数学问题分类"),
        ("写一个 Python 函数实现快速排序", "code", "代码问题分类"),
        ("头痛的常见原因有哪些？", "medical", "医学问题分类"),
        ("如何计算投资回报率？", "finance", "金融问题分类"),
        ("今天天气怎么样？", "general", "通用问题分类"),
    ]

    passed = 0
    failed = 0

    for text, expected_category, description in test_cases:
        print(f"\n测试: {description}")
        print(f"输入: {text}")
        print(f"期望类别: {expected_category}")

        try:
            # 发送分类请求
            request = classifier_pb2.ClassificationRequest(
                text=text,
                request_id=f"test_{int(time.time())}",
                cache_enabled=False,
                timeout_ms=3000
            )
            response = stub.Classify(request)

            # 打印响应
            print(f"预测类别: {response.category}")
            print(f"置信度: {response.confidence:.3f}")
            print(f"方法: {response.method}")
            print(f"延迟: {response.latency_ms:.1f}ms")
            print(f"模型版本: {response.model_version}")

            # 验证结果
            if response.category == expected_category:
                print("✓ 测试通过")
                passed += 1
            else:
                print(f"✗ 测试失败: 期望 {expected_category}, 得到 {response.category}")
                failed += 1

        except Exception as e:
            print(f"✗ 请求失败: {e}")
            failed += 1

        print("-" * 80)

    # 测试健康检查
    print("\n测试: 健康检查")
    try:
        health_request = classifier_pb2.HealthCheckRequest(check_type="detailed")
        health_response = stub.HealthCheck(health_request)

        print(f"状态: {health_response.status}")
        print(f"详细信息: {health_response.details}")
        print(f"统计: {health_response.stats}")
        print("✓ 健康检查通过")
        passed += 1

    except Exception as e:
        print(f"✗ 健康检查失败: {e}")
        failed += 1

    # 打印总结
    print("\n" + "=" * 80)
    print(f"  测试总结: {passed} 通过, {failed} 失败")
    print("=" * 80)

    return failed == 0

def test_batch_classify():
    """测试批量分类接口"""
    print("\n" + "=" * 80)
    print("  批量分类测试")
    print("=" * 80)

    channel = grpc.insecure_channel('localhost:50051')
    stub = classifier_pb2_grpc.SemanticClassifierServiceStub(channel)

    # 批量请求
    requests = [
        classifier_pb2.ClassificationRequest(
            text="1+1等于多少？",
            request_id="batch_1",
            cache_enabled=False
        ),
        classifier_pb2.ClassificationRequest(
            text="写一个Hello World程序",
            request_id="batch_2",
            cache_enabled=False
        ),
    ]

    batch_request = classifier_pb2.BatchClassificationRequest(requests=requests)

    try:
        batch_response = stub.BatchClassify(batch_request)
        print(f"批量分类完成，处理了 {len(batch_response.responses)} 个请求")

        for i, response in enumerate(batch_response.responses):
            print(f"\n请求 {i+1}:")
            print(f"  类别: {response.category}")
            print(f"  置信度: {response.confidence:.3f}")
            print(f"  方法: {response.method}")

        print("\n✓ 批量分类测试通过")
        return True

    except Exception as e:
        print(f"\n✗ 批量分类测试失败: {e}")
        return False

if __name__ == '__main__':
    print("启动分类服务测试...")

    # 测试单条分类
    success1 = test_classify()

    # 测试批量分类
    success2 = test_batch_classify()

    # 退出
    if success1 and success2:
        print("\n所有测试通过！✓")
        sys.exit(0)
    else:
        print("\n部分测试失败！✗")
        sys.exit(1)
