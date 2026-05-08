"""
Logger - 统一日志模块
替代项目中的 print 语句，提供统一的日志格式和级别控制
"""

import logging
import os
import sys
from typing import Optional


def setup_logging(level: Optional[str] = None) -> None:
    """
    初始化全局日志配置
    
    应在应用启动时调用一次，配置 root logger。
    后续各模块使用 get_logger() 获取子 logger。
    
    Args:
        level: 日志级别（DEBUG, INFO, WARNING, ERROR, CRITICAL），默认从环境变量 LOG_LEVEL 读取
    """
    log_level = (level or os.environ.get("LOG_LEVEL", "INFO")).upper()
    numeric_level = getattr(logging, log_level, logging.INFO)

    # 配置 root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)

    # 清除已有 handler（避免重复）
    if root_logger.handlers:
        root_logger.handlers.clear()

    # 控制台 handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)

    # 统一格式
    formatter = logging.Formatter(
        fmt="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # 设置第三方库日志级别，避免过多噪音
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def get_logger(name: str, level: Optional[str] = None) -> logging.Logger:
    """
    获取日志器实例

    Args:
        name: 日志器名称（通常为模块名，如 "agent.executor"）
        level: 日志级别（DEBUG, INFO, WARNING, ERROR, CRITICAL），默认从环境变量读取

    Returns:
        配置好的 Logger 实例
    """
    logger = logging.getLogger(name)

    # 避免重复添加 handler
    if logger.handlers:
        return logger

    # 设置日志级别
    log_level = level or os.environ.get("LOG_LEVEL", "INFO").upper()
    logger.setLevel(getattr(logging, log_level, logging.INFO))

    # 控制台 handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)

    # 格式：[时间] [级别] [模块名] 消息
    formatter = logging.Formatter(
        fmt="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # 防止日志向上传播到 root logger 导致重复输出
    logger.propagate = False

    return logger