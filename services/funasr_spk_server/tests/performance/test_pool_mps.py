"""
测试 pool 模式下的 MPS 加速 - 并发转录测试

验证：
1. worker 进程能否正确检测和使用 MPS 设备
2. 并发转录多个文件的性能表现
3. 转录结果是否正确（包含说话人信息）
4. 保存生成的 JSON 和 SRT 文件
"""
import os
import sys
import time
import json
import asyncio
from pathlib import Path
from datetime import datetime
from collections import Counter

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from loguru import logger
from src.core.funasr_transcriber import FunASRTranscriber

# 配置日志
logger.remove()
logger.add(
    sys.stdout,
    level="INFO",
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}"
)

# 输出目录
OUTPUT_DIR = project_root / "tests" / "performance" / "output"
OUTPUT_DIR.mkdir(exist_ok=True)


def save_transcription_results(result, audio_file: Path, output_format: str):
    """
    保存转录结果到文件

    Args:
        result: 转录结果对象（JSON 格式）或字典（SRT 格式）
        audio_file: 音频文件路径
        output_format: 输出格式（json 或 srt）

    Returns:
        保存的文件路径
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = audio_file.stem

    if output_format == "json":
        # 保存 JSON 格式
        output_file = OUTPUT_DIR / f"{base_name}_{timestamp}.json"
        with open(output_file, 'w', encoding='utf-8') as f:
            # 使用 model_dump(mode='json') 来正确序列化 datetime 等类型
            result_dict = result.model_dump(mode='json')
            json.dump(result_dict, f, ensure_ascii=False, indent=2)
        logger.info(f"💾 已保存 JSON 结果: {output_file.name}")
    else:
        # 保存 SRT 格式
        output_file = OUTPUT_DIR / f"{base_name}_{timestamp}.srt"
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(result['content'])
        logger.info(f"💾 已保存 SRT 结果: {output_file.name}")

    return output_file


async def transcribe_single_file(transcriber, audio_file: Path, output_format: str = "json"):
    """
    转录单个文件

    Args:
        transcriber: FunASRTranscriber 实例
        audio_file: 音频文件路径
        output_format: 输出格式（json 或 srt）

    Returns:
        包含转录结果和性能指标的字典
    """
    if not audio_file.exists():
        logger.error(f"❌ 文件不存在: {audio_file}")
        return None

    logger.info(f"📁 开始转录: {audio_file.name} ({output_format.upper()} 格式)")
    start_time = time.time()

    try:
        # 执行转录
        task_id = f"task_{audio_file.stem}_{int(time.time())}"
        transcribe_result = await transcriber.transcribe(
            audio_path=str(audio_file),
            task_id=task_id,
            enable_speaker=True,
            output_format=output_format
        )

        transcribe_time = time.time() - start_time

        # 处理不同格式的返回值
        if output_format == "json":
            # JSON 格式返回 (TranscriptionResult, raw_result) 元组
            result, raw_result = transcribe_result

            # 保存结果
            output_file = save_transcription_results(result, audio_file, output_format)

            # 提取性能指标
            duration = result.duration
            processing_time = result.processing_time
            segment_count = len(result.segments)
            speaker_count = len(result.speakers)
            speakers = result.speakers

            # 统计说话人分布
            speaker_distribution = Counter(seg.speaker for seg in result.segments)
        else:
            # SRT 格式返回字典
            result = transcribe_result

            # 保存结果
            output_file = save_transcription_results(result, audio_file, output_format)

            # 提取性能指标
            duration = result.get('duration', 0)
            processing_time = result.get('processing_time', transcribe_time)

            # 从 raw_result 中获取片段信息
            raw_result = result.get('raw_result', {})
            if isinstance(raw_result, list) and len(raw_result) > 0:
                raw_result = raw_result[0]

            sentences = raw_result.get('sentence_info', []) if isinstance(raw_result, dict) else []
            segment_count = len(sentences)

            # 统计说话人
            speakers_set = set()
            for sentence in sentences:
                speaker_id = sentence.get('spk', 0)
                speakers_set.add(f"Speaker{speaker_id + 1}")

            speakers = sorted(list(speakers_set))
            speaker_count = len(speakers)
            speaker_distribution = {}

        rtf = processing_time / duration if duration > 0 else 0
        speed_multiplier = 1 / rtf if rtf > 0 else 0

        return {
            'file_name': audio_file.name,
            'file_path': str(audio_file),
            'output_file': str(output_file),
            'output_format': output_format,
            'duration': duration,
            'transcribe_time': transcribe_time,
            'processing_time': processing_time,
            'segment_count': segment_count,
            'speaker_count': speaker_count,
            'speakers': speakers,
            'speaker_distribution': speaker_distribution,
            'rtf': rtf,
            'speed_multiplier': speed_multiplier,
            'success': True
        }

    except Exception as e:
        logger.error(f"❌ 转录失败 ({audio_file.name}, {output_format.upper()}): {e}")
        import traceback
        traceback.print_exc()
        return {
            'file_name': audio_file.name,
            'file_path': str(audio_file),
            'output_format': output_format,
            'success': False,
            'error': str(e)
        }


def print_result_summary(result_info: dict):
    """打印单个文件的转录结果摘要"""
    logger.info("─" * 60)
    logger.info(f"📄 文件: {result_info['file_name']}")
    logger.info(f"   格式: {result_info['output_format'].upper()}")
    logger.info(f"   音频时长: {result_info['duration']:.2f} 秒 ({result_info['duration']/60:.2f} 分钟)")
    logger.info(f"   转录时间: {result_info['transcribe_time']:.2f} 秒")
    logger.info(f"   处理时间: {result_info['processing_time']:.2f} 秒")
    logger.info(f"   片段数量: {result_info['segment_count']}")
    logger.info(f"   说话人数: {result_info['speaker_count']} - {result_info['speakers']}")

    # 说话人分布（仅 JSON 格式有）
    if result_info.get('speaker_distribution'):
        logger.info("   说话人分布:")
        for speaker, count in result_info['speaker_distribution'].items():
            logger.info(f"     • {speaker}: {count} 个片段")

    logger.info(f"   RTF: {result_info['rtf']:.4f}")
    logger.info(f"   速度倍率: {result_info['speed_multiplier']:.2f}x")
    logger.info(f"   保存至: {Path(result_info['output_file']).name}")


def print_overall_summary(results: list, total_time: float, init_time: float):
    """打印总体统计信息"""
    logger.info("=" * 60)
    logger.info("📊 整体性能统计")
    logger.info("=" * 60)

    # 统计成功和失败的任务
    success_count = sum(1 for r in results if r['success'])
    failed_count = len(results) - success_count

    logger.info(f"任务总数: {len(results)}")
    logger.info(f"成功: {success_count} | 失败: {failed_count}")
    logger.info(f"初始化时间: {init_time:.2f} 秒")
    logger.info(f"总转录时间: {total_time:.2f} 秒")

    # 只统计成功的任务
    success_results = [r for r in results if r['success']]
    if success_results:
        total_audio_duration = sum(r['duration'] for r in success_results)
        total_processing_time = sum(r['processing_time'] for r in success_results)
        avg_rtf = total_processing_time / total_audio_duration if total_audio_duration > 0 else 0
        avg_speed = 1 / avg_rtf if avg_rtf > 0 else 0

        logger.info(f"总音频时长: {total_audio_duration:.2f} 秒 ({total_audio_duration/60:.2f} 分钟)")
        logger.info(f"总处理时间: {total_processing_time:.2f} 秒")
        logger.info(f"平均 RTF: {avg_rtf:.4f}")
        logger.info(f"平均速度倍率: {avg_speed:.2f}x")
        logger.info(f"并发效率: {total_audio_duration/total_time:.2f}x")

    logger.info("=" * 60)


async def test_concurrent_transcription():
    """测试并发转录多个文件"""
    # 测试音频文件
    test_files = [
        project_root / "temp" / "test.m4a",
        project_root / "temp" / "podcast_en.mp3"
    ]

    # 检查文件是否存在
    existing_files = [f for f in test_files if f.exists()]
    if not existing_files:
        logger.error("❌ 没有找到测试文件")
        logger.info("请确保以下文件存在：")
        for f in test_files:
            logger.info(f"  - {f}")
        return

    if len(existing_files) < len(test_files):
        logger.warning("⚠️ 部分测试文件不存在，将只测试以下文件：")
        for f in existing_files:
            logger.info(f"  ✓ {f.name}")

    logger.info("=" * 60)
    logger.info("🚀 Pool 模式 + MPS 加速 - 并发转录测试")
    logger.info("=" * 60)

    # 创建转录器（pool 模式）
    transcriber = FunASRTranscriber(config_path="config.json")
    logger.info(f"并发模式: {transcriber.concurrency_mode}")
    logger.info(f"测试文件数: {len(existing_files)}")

    try:
        # 初始化（会启动 worker 进程）
        logger.info("\n🔧 初始化转录器（启动 worker 进程）...")
        start_init = time.time()
        await transcriber.initialize()
        init_time = time.time() - start_init
        logger.success(f"✅ 初始化完成，耗时: {init_time:.2f} 秒")

        # 等待一下，确保 worker 完全就绪
        await asyncio.sleep(2)

        # 并发转录所有文件（JSON 和 SRT 格式）
        logger.info("\n" + "=" * 60)
        logger.info("📝 开始并发转录...")
        logger.info("=" * 60)

        start_time = time.time()

        # 创建所有转录任务（同时转录 JSON 和 SRT 格式）
        tasks = []
        for audio_file in existing_files:
            tasks.append(transcribe_single_file(transcriber, audio_file, "json"))
            tasks.append(transcribe_single_file(transcriber, audio_file, "srt"))

        # 并发执行所有任务
        results = await asyncio.gather(*tasks)

        total_time = time.time() - start_time

        # 打印每个文件的结果
        logger.info("\n" + "=" * 60)
        logger.info("📋 转录结果详情")
        logger.info("=" * 60)

        success_results = [r for r in results if r['success']]
        for result_info in success_results:
            print_result_summary(result_info)

        # 打印总体统计
        logger.info("")
        print_overall_summary(results, total_time, init_time)

        # 检查是否全部成功
        if all(r['success'] for r in results):
            logger.success("\n✅ 所有测试成功！Pool 模式 + MPS 加速并发转录工作正常")
        else:
            logger.warning("\n⚠️ 部分测试失败")

        # 输出文件位置
        logger.info(f"\n📂 所有结果已保存至: {OUTPUT_DIR}")

    except Exception as e:
        logger.error(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()

    finally:
        # 清理资源
        if transcriber.model_pool:
            logger.info("\n🧹 清理 worker 进程...")
            transcriber.model_pool.cleanup()
            logger.success("✅ 清理完成")


if __name__ == "__main__":
    asyncio.run(test_concurrent_transcription())
