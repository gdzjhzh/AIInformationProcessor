#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
pytest 全局配置文件

用于管理测试环境的全局资源，包括企业微信通知器的单例实例。
"""

import os
import sys
import pytest

# 添加src目录到Python路径
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'src'))

from video_transcript_api.utils.notifications.wechat import init_global_notifier, shutdown_global_notifier


@pytest.fixture(scope="session", autouse=True)
def setup_global_wechat_notifier():
    """
    在所有测试开始前初始化全局 WeComNotifier 实例

    这是一个 session 级别的 fixture，确保：
    1. 在整个测试会话中只创建一个全局 WeComNotifier 实例
    2. 所有测试共享同一个实例，实现正确的频率控制和消息顺序保证
    3. 测试结束时自动清理资源

    参考：docs/api/企微通知器-USAGE_GUIDE.md 最佳实践章节
    """
    # 测试开始前：初始化全局实例
    init_global_notifier()

    # 执行所有测试
    yield

    # 测试结束后：清理全局实例
    shutdown_global_notifier()
