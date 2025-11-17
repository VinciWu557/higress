#!/usr/bin/env python3
"""
分类服务主入口
"""

import logging
import sys
import argparse
from pathlib import Path

# 添加 src 目录到路径
sys.path.insert(0, str(Path(__file__).parent / "src"))

from src.config import get_config, ClassifierConfig
from src.server import serve


def setup_logging(level: str):
    """设置日志"""
    numeric_level = getattr(logging, level.upper(), None)
    if not isinstance(numeric_level, int):
        raise ValueError(f"无效的日志级别: {level}")

    logging.basicConfig(
        level=numeric_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler('logs/classifier_service.log')
        ]
    )


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(description="语义分类服务")
    parser.add_argument("--config", type=str, help="配置文件路径")
    parser.add_argument("--model-path", type=str, help="模型路径")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="服务主机")
    parser.add_argument("--port", type=int, default=50051, help="服务端口")
    parser.add_argument("--device", type=str, default="auto", help="设备 (auto/cpu/cuda)")
    parser.add_argument("--log-level", type=str, default="INFO", help="日志级别")
    parser.add_argument("--max-workers", type=int, default=10, help="最大工作线程")
    parser.add_argument("--enable-cache", action="store_true", default=True, help="启用缓存")
    parser.add_argument("--enable-monitoring", action="store_true", default=True, help="启用监控")
    parser.add_argument("--metrics-port", type=int, default=8080, help="监控端口")

    return parser.parse_args()


def load_config(args) -> ClassifierConfig:
    """加载配置"""
    if args.config:
        # 从文件加载
        import json
        with open(args.config, "r") as f:
            config_dict = json.load(f)
        config = ClassifierConfig.from_dict(config_dict)
    else:
        # 从环境变量和命令行参数加载
        config = get_config()

        # 覆盖配置
        if args.model_path:
            config.model.model_path = args.model_path
        if args.host:
            config.server.host = args.host
        if args.port:
            config.server.port = args.port
        if args.device:
            config.model.device = args.device
        if args.max_workers:
            config.server.max_workers = args.max_workers
        if args.enable_cache is not None:
            config.server.enable_cache = args.enable_cache
        if args.enable_monitoring is not None:
            config.monitoring.enabled = args.enable_monitoring
        if args.metrics_port:
            config.monitoring.metrics_port = args.metrics_port

        # 日志级别
        config.monitoring.log_level = args.log_level

    return config


def main():
    """主函数"""
    # 解析参数
    args = parse_args()

    try:
        # 加载配置
        config = load_config(args)

        # 设置日志
        setup_logging(config.monitoring.log_level)

        logger = logging.getLogger(__name__)
        logger.info("=" * 80)
        logger.info("  语义分类服务启动")
        logger.info("=" * 80)
        logger.info(f"模型路径: {config.model.model_path}")
        logger.info(f"设备: {config.model.device}")
        logger.info(f"服务器: {config.server.host}:{config.server.port}")
        logger.info(f"工作线程: {config.server.max_workers}")
        logger.info(f"缓存: {config.server.enable_cache}")
        logger.info(f"监控: {config.monitoring.enabled} (端口: {config.monitoring.metrics_port})")
        logger.info("=" * 80)

        # 启动服务
        serve(config)

    except KeyboardInterrupt:
        logging.info("收到停止信号，正在关闭服务...")
        sys.exit(0)
    except Exception as e:
        logging.error(f"服务启动失败: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
