#!/usr/bin/env python
# coding: utf-8

"""
Unit test for FunASR conversion functions (without running CapsWriter server)
"""

import sys
import json
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

from video_transcript_api.transcriber.capswriter_client import (
    _create_segments_from_capswriter,
    _clean_token,
    _build_token_position_map,
    _split_text_by_punctuation
)


def test_conversion_functions():
    """测试转换函数（使用已有的测试数据）"""
    print('=' * 80)
    print('TESTING FUNASR CONVERSION FUNCTIONS')
    print('=' * 80)

    # 使用之前测试生成的数据
    json_file = Path('tests/output/capswriter_format_test/json/spk_extract.json')
    txt_file = Path('tests/output/capswriter_format_test/all/spk_extract.merge.txt')

    if not json_file.exists():
        print(f'ERROR: Test data not found: {json_file}')
        print('Please run: python tests/test_capswriter_formats.py first')
        return False

    if not txt_file.exists():
        print(f'ERROR: Test data not found: {txt_file}')
        return False

    # 加载测试数据
    with open(json_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    with open(txt_file, 'r', encoding='utf-8') as f:
        text = f.read().strip()

    tokens = data.get('tokens', [])
    timestamps = data.get('timestamps', [])

    print(f'\n[INPUT DATA]')
    print(f'  Text length: {len(text)} chars')
    print(f'  Tokens count: {len(tokens)}')
    print(f'  Timestamps count: {len(timestamps)}')

    # 测试辅助函数
    print(f'\n[TEST 1] Testing helper functions...')

    # Test _clean_token
    assert _clean_token('l@@') == 'l', 'Failed: _clean_token'
    assert _clean_token('ily') == 'ily', 'Failed: _clean_token'
    print('  _clean_token: OK')

    # Test _build_token_position_map
    test_tokens = ['好', '欢', 'l@@', 'ily']
    positions, reconstructed = _build_token_position_map(test_tokens)
    assert reconstructed == '好欢lily', f'Failed: reconstructed = {reconstructed}'
    # 位置: 好(0), 欢(1), l(2), ily(3), 结束(6)
    assert positions == [0, 1, 2, 3, 6], f'Failed: positions = {positions}'
    print('  _build_token_position_map: OK')

    # Test _split_text_by_punctuation
    test_text = "你好。我是主持人。欢迎！"
    sentences = _split_text_by_punctuation(test_text)
    assert len(sentences) == 3, f'Failed: expected 3 sentences, got {len(sentences)}'
    print('  _split_text_by_punctuation: OK')

    # 测试主转换函数
    print(f'\n[TEST 2] Testing main conversion function...')

    segments = _create_segments_from_capswriter(
        text=text,
        tokens=tokens,
        timestamps=timestamps,
        min_len=80,
        max_len=300
    )

    print(f'  Generated segments: {len(segments)}')

    if not segments:
        print('ERROR: No segments generated!')
        return False

    # 验证 segments 结构
    print(f'\n[TEST 3] Validating segment structure...')

    required_fields = ['start_time', 'end_time', 'text']
    for i, seg in enumerate(segments):
        for field in required_fields:
            if field not in seg:
                print(f'ERROR: Segment {i+1} missing field: {field}')
                return False

        # 验证时间合理性
        if seg['start_time'] < 0:
            print(f'ERROR: Segment {i+1} has negative start_time')
            return False

        if seg['end_time'] <= seg['start_time']:
            print(f'ERROR: Segment {i+1} end_time <= start_time')
            return False

        # 验证文本非空
        if not seg['text']:
            print(f'ERROR: Segment {i+1} has empty text')
            return False

    print('  All segments valid: OK')

    # 显示 segments 详情
    print(f'\n[SEGMENTS]')
    for i, seg in enumerate(segments):
        duration = seg['end_time'] - seg['start_time']
        text_len = len(seg['text'])
        text_preview = seg['text'][:60]

        print(f'{i+1}. [{seg["start_time"]:6.2f}s - {seg["end_time"]:6.2f}s] '
              f'({duration:5.2f}s) {text_len:3d} chars')
        print(f'   "{text_preview}{"..." if text_len > 60 else ""}"')

    # 统计分析
    print(f'\n[STATISTICS]')
    lengths = [len(seg['text']) for seg in segments]
    durations = [seg['end_time'] - seg['start_time'] for seg in segments]

    print(f'  Segments count: {len(segments)}')
    print(f'  Length range: {min(lengths)} - {max(lengths)} chars')
    print(f'  Average length: {sum(lengths) / len(lengths):.1f} chars')
    print(f'  Duration range: {min(durations):.2f}s - {max(durations):.2f}s')

    in_range = sum(1 for l in lengths if 80 <= l <= 300)
    print(f'  Segments in 80-300 range: {in_range}/{len(segments)} ({in_range/len(segments)*100:.1f}%)')

    # 测试 FunASR 格式构建
    print(f'\n[TEST 4] Building FunASR format...')

    funasr_data = {
        'task_id': 'test-task-123',
        'file_name': 'test_audio.mp3',
        'duration': timestamps[-1] if timestamps else 0,
        'segments': [
            {
                'start_time': seg['start_time'],
                'end_time': seg['end_time'],
                'text': seg['text']
            }
            for seg in segments
        ],
        'created_at': '2025-10-27T12:00:00',
        'processing_time': 10.5,
        'error': None
    }

    # 保存到临时文件
    output_file = Path('tests/output/test_funasr_conversion.json')
    output_file.parent.mkdir(parents=True, exist_ok=True)

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(funasr_data, f, ensure_ascii=False, indent=2)

    print(f'  Saved to: {output_file}')
    print(f'  File size: {output_file.stat().st_size} bytes')

    # 验证 JSON 可以正确读取
    with open(output_file, 'r', encoding='utf-8') as f:
        loaded = json.load(f)

    assert len(loaded['segments']) == len(segments), 'JSON load/save mismatch'
    print('  JSON serialization: OK')

    print('\n' + '=' * 80)
    print('ALL TESTS PASSED!')
    print('=' * 80)

    return True


if __name__ == '__main__':
    success = test_conversion_functions()
    sys.exit(0 if success else 1)
