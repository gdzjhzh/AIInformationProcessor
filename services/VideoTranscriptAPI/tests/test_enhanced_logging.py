#!/usr/bin/env python
# coding: utf-8

"""
Test enhanced logging for FunASR conversion
"""

import sys
import json
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

from video_transcript_api.transcriber.capswriter_client import (
    _create_segments_from_capswriter
)
from loguru import logger


def test_enhanced_logging():
    """测试增强后的日志输出"""
    print('=' * 80)
    print('TESTING ENHANCED LOGGING')
    print('=' * 80)

    # 使用测试数据
    json_file = Path('tests/output/capswriter_format_test/json/spk_extract.json')
    txt_file = Path('tests/output/capswriter_format_test/all/spk_extract.merge.txt')

    if not json_file.exists() or not txt_file.exists():
        print('ERROR: Test data not found')
        print('Please run: python tests/test_capswriter_formats.py first')
        return False

    # 加载数据
    with open(json_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    with open(txt_file, 'r', encoding='utf-8') as f:
        text = f.read().strip()

    tokens = data.get('tokens', [])
    timestamps = data.get('timestamps', [])

    print('\n[TEST 1] Normal case - should succeed')
    print('-' * 80)

    segments = _create_segments_from_capswriter(
        text=text,
        tokens=tokens,
        timestamps=timestamps,
        min_len=80,
        max_len=300
    )

    print(f'\nResult: {len(segments)} segments generated')

    print('\n[TEST 2] Empty text - should fail gracefully')
    print('-' * 80)

    try:
        segments = _create_segments_from_capswriter(
            text="",
            tokens=tokens,
            timestamps=timestamps,
            min_len=80,
            max_len=300
        )
        print(f'\nResult: {len(segments)} segments generated')
    except Exception as e:
        print(f'\nCaught exception: {e}')

    print('\n[TEST 3] Length mismatch - should handle gracefully')
    print('-' * 80)

    segments = _create_segments_from_capswriter(
        text=text,
        tokens=tokens[:100],  # 故意不匹配
        timestamps=timestamps,
        min_len=80,
        max_len=300
    )

    print(f'\nResult: {len(segments)} segments generated')

    print('\n[TEST 4] Empty tokens - should fail gracefully')
    print('-' * 80)

    segments = _create_segments_from_capswriter(
        text=text,
        tokens=[],
        timestamps=[],
        min_len=80,
        max_len=300
    )

    print(f'\nResult: {len(segments)} segments generated')

    print('\n' + '=' * 80)
    print('LOGGING TEST COMPLETED')
    print('=' * 80)

    return True


if __name__ == '__main__':
    # 配置日志级别以显示 debug 信息
    logger.remove()
    logger.add(
        sys.stderr,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
        level="DEBUG"
    )

    success = test_enhanced_logging()
    sys.exit(0 if success else 1)
