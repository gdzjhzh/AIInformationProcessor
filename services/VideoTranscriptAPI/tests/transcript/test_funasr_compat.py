#!/usr/bin/env python
# coding: utf-8

"""
Test FunASR compatible JSON generation from CapsWriter client
"""

import sys
import json
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

from video_transcript_api.transcriber.capswriter_client import CapsWriterClient, Config


def test_funasr_generation():
    """测试 FunASR 兼容格式生成"""
    print('=' * 80)
    print('TESTING FUNASR COMPATIBLE JSON GENERATION')
    print('=' * 80)

    # 设置测试参数
    audio_file = Path('tests/sample_files/spk_extract.mp3')
    output_dir = Path('tests/output/funasr_compat_test')

    if not audio_file.exists():
        print(f'ERROR: Audio file not found: {audio_file}')
        return False

    # 清理输出目录
    output_dir.mkdir(parents=True, exist_ok=True)

    # 配置格式
    Config.generate_txt = True
    Config.generate_json = False
    Config.generate_merge_txt = False
    Config.generate_funasr_compat = True  # 启用 FunASR 兼容格式

    print(f'\n[CONFIG]')
    print(f'  Audio file: {audio_file}')
    print(f'  Output dir: {output_dir}')
    print(f'  FunASR compat: {Config.generate_funasr_compat}')

    # 创建客户端并转录
    client = CapsWriterClient(output_dir=str(output_dir))

    print(f'\n[TRANSCRIBING]')
    print('Starting transcription...')

    success, generated_files = client.transcribe_file(str(audio_file))

    if not success:
        print('\nERROR: Transcription failed!')
        return False

    print(f'\n[RESULTS]')
    print(f'Generated {len(generated_files)} files:')
    for f in generated_files:
        print(f'  - {f}')

    # 检查 FunASR 兼容文件
    funasr_file = output_dir / 'transcript_capswriter.json'

    if not funasr_file.exists():
        print('\nERROR: FunASR compatible file not generated!')
        return False

    print(f'\n[FUNASR FILE ANALYSIS]')
    print(f'File: {funasr_file}')
    print(f'Size: {funasr_file.stat().st_size} bytes')

    # 读取并验证 JSON 结构
    with open(funasr_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    print(f'\n[JSON STRUCTURE]')
    print(f'  task_id: {data.get("task_id", "N/A")}')
    print(f'  file_name: {data.get("file_name", "N/A")}')
    print(f'  duration: {data.get("duration", 0):.2f}s')
    print(f'  segments: {len(data.get("segments", []))} items')
    print(f'  created_at: {data.get("created_at", "N/A")}')
    print(f'  processing_time: {data.get("processing_time", 0):.2f}s')
    print(f'  error: {data.get("error")}')

    # 验证 segments 结构
    segments = data.get('segments', [])

    if not segments:
        print('\nWARNING: No segments found!')
        return False

    print(f'\n[SEGMENTS DETAILS]')
    for i, seg in enumerate(segments):
        duration = seg.get('end_time', 0) - seg.get('start_time', 0)
        text_len = len(seg.get('text', ''))
        text_preview = seg.get('text', '')[:60]

        print(f'{i+1:2d}. [{seg.get("start_time", 0):6.2f}s - {seg.get("end_time", 0):6.2f}s] '
              f'({duration:5.2f}s) {text_len:3d} chars')
        print(f'    "{text_preview}{"..." if text_len > 60 else ""}"')

    # 统计分析
    print(f'\n[STATISTICS]')
    lengths = [len(seg.get('text', '')) for seg in segments]
    durations = [seg.get('end_time', 0) - seg.get('start_time', 0) for seg in segments]

    print(f'  Length range: {min(lengths)} - {max(lengths)} chars')
    print(f'  Average length: {sum(lengths) / len(lengths):.1f} chars')
    print(f'  Duration range: {min(durations):.2f}s - {max(durations):.2f}s')
    print(f'  Average duration: {sum(durations) / len(durations):.2f}s')

    # 长度分布
    in_range = sum(1 for l in lengths if 80 <= l <= 300)
    below = sum(1 for l in lengths if l < 80)
    above = sum(1 for l in lengths if l > 300)

    print(f'\n  Length distribution:')
    print(f'    < 80 chars:   {below} segments ({below/len(segments)*100:.1f}%)')
    print(f'    80-300 chars: {in_range} segments ({in_range/len(segments)*100:.1f}%)')
    print(f'    > 300 chars:  {above} segments ({above/len(segments)*100:.1f}%)')

    # 验证必需字段
    print(f'\n[VALIDATION]')
    required_fields = ['task_id', 'file_name', 'duration', 'segments', 'created_at', 'processing_time', 'error']
    missing_fields = [f for f in required_fields if f not in data]

    if missing_fields:
        print(f'  Missing fields: {missing_fields}')
        return False
    else:
        print(f'  All required fields present: OK')

    # 验证 segment 字段
    required_seg_fields = ['start_time', 'end_time', 'text']
    for i, seg in enumerate(segments):
        missing = [f for f in required_seg_fields if f not in seg]
        if missing:
            print(f'  Segment {i+1} missing fields: {missing}')
            return False

    print(f'  All segment fields valid: OK')

    print('\n' + '=' * 80)
    print('TEST PASSED!')
    print('=' * 80)

    return True


if __name__ == '__main__':
    success = test_funasr_generation()
    sys.exit(0 if success else 1)
