"""
Mac GPU (MPS) 加速性能测试脚本

基于 GitHub Issue #1802 的解决方案，测试 FunASR 在 Apple Silicon 上的 GPU 加速效果
"""
import os
import sys
import time
import torch
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from loguru import logger

# 配置日志
logger.remove()
logger.add(sys.stdout, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}")


def patch_funasr_mps_support():
    """
    临时修复 FunASR 的 MPS 支持问题

    根据 GitHub Issue #1802，FunASR 会强制回退到 CPU，需要修改 build_model 方法
    """
    from funasr.auto import auto_model

    original_build_model = auto_model.AutoModel.build_model

    @staticmethod
    def patched_build_model(**kwargs):
        """修复后的 build_model 方法，支持 MPS"""
        assert "model" in kwargs
        if "model_conf" not in kwargs:
            from funasr.download.download_model_from_hub import download_model
            import logging
            logging.info("download models from model hub: {}".format(kwargs.get("hub", "ms")))
            kwargs = download_model(**kwargs)

        from funasr.train_utils.set_all_random_seed import set_all_random_seed
        set_all_random_seed(kwargs.get("seed", 0))

        # 修复：支持 MPS 设备
        device = kwargs.get("device", "cuda")

        # 检查 CUDA
        if device == "cuda" and not torch.cuda.is_available():
            # 尝试使用 MPS
            if torch.backends.mps.is_available() and torch.backends.mps.is_built():
                device = "mps"
                logger.info("CUDA 不可用，切换到 MPS 设备")
            else:
                device = "cpu"
                logger.info("GPU 不可用，使用 CPU")

        # 如果显式指定了 MPS，不要回退到 CPU
        elif device == "mps":
            if not torch.backends.mps.is_available() or not torch.backends.mps.is_built():
                logger.warning("MPS 不可用，回退到 CPU")
                device = "cpu"
            else:
                logger.info("使用 MPS 设备进行加速")

        # 只有在 CPU 模式下才强制 batch_size=1
        if device == "cpu" and kwargs.get("ngpu", 1) == 0:
            kwargs["batch_size"] = 1

        kwargs["device"] = device
        torch.set_num_threads(kwargs.get("ncpu", 4))

        # 继续原始逻辑（构建 tokenizer, frontend, model）
        from funasr.register import tables
        from funasr.utils.misc import deep_update
        from funasr.train_utils.load_pretrained_model import load_pretrained_model
        from omegaconf import ListConfig

        # build tokenizer
        tokenizer = kwargs.get("tokenizer", None)
        kwargs["tokenizer"] = tokenizer
        kwargs["vocab_size"] = -1

        if tokenizer is not None:
            tokenizers = (
                tokenizer.split(",") if isinstance(tokenizer, str) else tokenizer
            )
            tokenizers_conf = kwargs.get("tokenizer_conf", {})
            tokenizers_build = []
            vocab_sizes = []
            token_lists = []

            token_list_files = kwargs.get("token_lists", [])
            seg_dicts = kwargs.get("seg_dicts", [])

            if not isinstance(tokenizers_conf, (list, tuple, ListConfig)):
                tokenizers_conf = [tokenizers_conf] * len(tokenizers)

            for i, tokenizer in enumerate(tokenizers):
                tokenizer_class = tables.tokenizer_classes.get(tokenizer)
                tokenizer_conf = tokenizers_conf[i]

                if len(token_list_files) > 1:
                    tokenizer_conf["token_list"] = token_list_files[i]
                if len(seg_dicts) > 1:
                    tokenizer_conf["seg_dict"] = seg_dicts[i]

                tokenizer = tokenizer_class(**tokenizer_conf)
                tokenizers_build.append(tokenizer)
                token_list = tokenizer.token_list if hasattr(tokenizer, "token_list") else None
                token_list = (
                    tokenizer.get_vocab() if hasattr(tokenizer, "get_vocab") else token_list
                )
                vocab_size = -1
                if token_list is not None:
                    vocab_size = len(token_list)

                if vocab_size == -1 and hasattr(tokenizer, "get_vocab_size"):
                    vocab_size = tokenizer.get_vocab_size()
                token_lists.append(token_list)
                vocab_sizes.append(vocab_size)

            if len(tokenizers_build) <= 1:
                tokenizers_build = tokenizers_build[0]
                token_lists = token_lists[0]
                vocab_sizes = vocab_sizes[0]

            kwargs["tokenizer"] = tokenizers_build
            kwargs["vocab_size"] = vocab_sizes
            kwargs["token_list"] = token_lists

        # build frontend
        frontend = kwargs.get("frontend", None)
        kwargs["input_size"] = None
        if frontend is not None:
            frontend_class = tables.frontend_classes.get(frontend)
            frontend = frontend_class(**kwargs.get("frontend_conf", {}))
            kwargs["input_size"] = (
                frontend.output_size() if hasattr(frontend, "output_size") else None
            )
        kwargs["frontend"] = frontend

        # build model
        model_class = tables.model_classes.get(kwargs["model"])
        assert model_class is not None, f'{kwargs["model"]} is not registered'
        model_conf = {}
        deep_update(model_conf, kwargs.get("model_conf", {}))
        deep_update(model_conf, kwargs)
        model = model_class(**model_conf)

        # init_param
        init_param = kwargs.get("init_param", None)
        if init_param is not None:
            if os.path.exists(init_param):
                import logging
                logging.info(f"Loading pretrained params from {init_param}")
                load_pretrained_model(
                    model=model,
                    path=init_param,
                    ignore_init_mismatch=kwargs.get("ignore_init_mismatch", True),
                    oss_bucket=kwargs.get("oss_bucket", None),
                    scope_map=kwargs.get("scope_map", []),
                    excludes=kwargs.get("excludes", None),
                )
            else:
                print(f"error, init_param does not exist!: {init_param}")

        # fp16
        if kwargs.get("fp16", False):
            model.to(torch.float16)
        elif kwargs.get("bf16", False):
            model.to(torch.bfloat16)
        model.to(device)

        if not kwargs.get("disable_log", True):
            tables.print()

        return model, kwargs

    # 应用补丁
    auto_model.AutoModel.build_model = patched_build_model
    logger.success("✅ FunASR MPS 支持补丁已应用")


def get_audio_duration(audio_path: str) -> float:
    """获取音频时长"""
    import subprocess
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
             '-of', 'default=noprint_wrappers=1:nokey=1', audio_path],
            capture_output=True,
            text=True
        )
        return float(result.stdout.strip())
    except Exception as e:
        logger.error(f"获取音频时长失败: {e}")
        return 0


def test_device_performance(audio_path: str, device: str, use_speaker: bool = True):
    """
    测试指定设备的性能

    Args:
        audio_path: 音频文件路径
        device: 设备类型 (cpu, mps, cuda)
        use_speaker: 是否启用说话人识别
    """
    from funasr import AutoModel

    logger.info(f"\n{'='*60}")
    logger.info(f"测试设备: {device.upper()}")
    logger.info(f"说话人识别: {'启用' if use_speaker else '禁用'}")
    logger.info(f"{'='*60}\n")

    try:
        # 检查音频文件
        if not os.path.exists(audio_path):
            logger.error(f"音频文件不存在: {audio_path}")
            return None

        audio_duration = get_audio_duration(audio_path)
        logger.info(f"音频文件: {os.path.basename(audio_path)}")
        logger.info(f"音频时长: {audio_duration:.2f} 秒")

        # 初始化模型
        logger.info(f"正在初始化模型...")
        start_init = time.time()

        if use_speaker:
            # 包含说话人识别的完整模型
            model = AutoModel(
                model="paraformer-zh",
                model_revision="v2.0.4",
                vad_model="fsmn-vad",
                vad_model_revision="v2.0.4",
                punc_model="ct-punc-c",
                punc_model_revision="v2.0.4",
                spk_model="cam++",
                spk_model_revision="v2.0.2",
                device=device,
                disable_update=True,
                disable_pbar=True
            )
        else:
            # 仅 ASR 模型（不含说话人识别）
            model = AutoModel(
                model="paraformer-zh",
                model_revision="v2.0.4",
                vad_model="fsmn-vad",
                vad_model_revision="v2.0.4",
                punc_model="ct-punc-c",
                punc_model_revision="v2.0.4",
                device=device,
                disable_update=True,
                disable_pbar=True
            )

        init_time = time.time() - start_init
        logger.info(f"模型初始化耗时: {init_time:.2f} 秒")

        # 检查实际使用的设备
        actual_device = next(model.model.parameters()).device
        logger.info(f"实际使用的设备: {actual_device}")

        # 预热（第一次运行可能较慢）
        logger.info("预热中...")
        _ = model.generate(input=audio_path, batch_size_s=300, hotword='')

        # 正式测试（运行3次取平均值）
        logger.info("开始性能测试...")
        inference_times = []

        for i in range(3):
            start_time = time.time()
            result = model.generate(input=audio_path, batch_size_s=300, hotword='')
            inference_time = time.time() - start_time
            inference_times.append(inference_time)

            rtf = inference_time / audio_duration if audio_duration > 0 else 0
            logger.info(f"  第 {i+1} 次: {inference_time:.2f}s (RTF: {rtf:.4f})")

        # 计算统计数据
        avg_time = sum(inference_times) / len(inference_times)
        avg_rtf = avg_time / audio_duration if audio_duration > 0 else 0

        logger.success(f"\n{'='*60}")
        logger.success(f"测试结果汇总 ({device.upper()})")
        logger.success(f"{'='*60}")
        logger.success(f"平均推理时间: {avg_time:.2f} 秒")
        logger.success(f"平均 RTF: {avg_rtf:.4f}")
        logger.success(f"速度倍率: {1/avg_rtf:.2f}x (相对实时)")

        # 提取转录结果
        if result and len(result) > 0:
            text = result[0].get('text', '')
            logger.info(f"\n转录结果预览:\n{text[:200]}...")

            if 'sentence_info' in result[0]:
                sentence_count = len(result[0]['sentence_info'])
                logger.info(f"句子数量: {sentence_count}")

        return {
            'device': device,
            'use_speaker': use_speaker,
            'audio_duration': audio_duration,
            'init_time': init_time,
            'inference_times': inference_times,
            'avg_inference_time': avg_time,
            'avg_rtf': avg_rtf,
            'speedup': 1/avg_rtf if avg_rtf > 0 else 0,
            'actual_device': str(actual_device)
        }

    except Exception as e:
        logger.error(f"测试失败 ({device}): {e}")
        import traceback
        traceback.print_exc()
        return None


def compare_performance(results: dict):
    """对比不同设备的性能"""
    if not results:
        return

    logger.info(f"\n{'='*80}")
    logger.info("性能对比分析")
    logger.info(f"{'='*80}\n")

    # 创建对比表格
    header = f"{'设备':<15} {'说话人':<10} {'平均耗时':<15} {'RTF':<15} {'加速比':<15}"
    logger.info(header)
    logger.info("-" * 80)

    baseline_time = None
    for key, result in results.items():
        if result:
            device_name = result['device'].upper()
            use_spk = "✓" if result['use_speaker'] else "✗"
            avg_time = result['avg_inference_time']
            rtf = result['avg_rtf']
            speedup = result['speedup']

            # 计算相对于 CPU 的加速比
            if baseline_time is None:
                baseline_time = avg_time
                relative_speedup = "1.00x (baseline)"
            else:
                relative_speedup = f"{baseline_time / avg_time:.2f}x"

            row = f"{device_name:<15} {use_spk:<10} {avg_time:>10.2f}s    {rtf:>10.4f}    {relative_speedup:<15}"

            if device_name == "MPS" and relative_speedup != "1.00x (baseline)":
                logger.success(row)  # MPS 加速结果用绿色高亮
            else:
                logger.info(row)

    logger.info("\n" + "="*80)


def main():
    """主测试函数"""
    # 应用 MPS 支持补丁
    patch_funasr_mps_support()

    # 测试文件路径
    audio_file = os.path.join(project_root, "temp", "test.m4a")

    if not os.path.exists(audio_file):
        logger.error(f"测试文件不存在: {audio_file}")
        logger.info("请将测试音频文件放置在 temp/test.m4a")
        return

    # 检查设备支持
    logger.info("检查设备支持情况...")
    logger.info(f"  CUDA 可用: {torch.cuda.is_available()}")
    logger.info(f"  MPS 可用: {torch.backends.mps.is_available()}")
    logger.info(f"  MPS 已构建: {torch.backends.mps.is_built()}")

    results = {}

    # 测试 1: CPU (不含说话人识别) - 基准测试
    logger.info("\n" + "🔵 测试 1/4: CPU 模式（不含说话人识别）")
    results['cpu_no_spk'] = test_device_performance(audio_file, "cpu", use_speaker=False)

    # 测试 2: CPU (含说话人识别)
    logger.info("\n" + "🔵 测试 2/4: CPU 模式（含说话人识别）")
    results['cpu_with_spk'] = test_device_performance(audio_file, "cpu", use_speaker=True)

    # 测试 3: MPS (不含说话人识别)
    if torch.backends.mps.is_available():
        logger.info("\n" + "🟢 测试 3/4: MPS 模式（不含说话人识别）")
        results['mps_no_spk'] = test_device_performance(audio_file, "mps", use_speaker=False)

        # 测试 4: MPS (含说话人识别) - 注意: spk_model 可能不兼容
        logger.info("\n" + "🟢 测试 4/4: MPS 模式（含说话人识别）")
        logger.warning("⚠️  根据 Issue #1802，说话人模型可能不兼容 MPS")
        results['mps_with_spk'] = test_device_performance(audio_file, "mps", use_speaker=True)
    else:
        logger.warning("⚠️  MPS 不可用，跳过 MPS 测试")

    # 性能对比
    compare_performance(results)

    # 建议
    logger.info("\n" + "="*80)
    logger.info("💡 优化建议")
    logger.info("="*80)

    if 'mps_with_spk' in results and results['mps_with_spk']:
        cpu_time = results['cpu_with_spk']['avg_inference_time']
        mps_time = results['mps_with_spk']['avg_inference_time']
        speedup = cpu_time / mps_time

        if speedup > 1.3:
            logger.success(f"✅ MPS 加速有效！相比 CPU 提升 {speedup:.2f}x")
            logger.info("建议：修改 config.json，设置 \"device\": \"mps\"")
        elif speedup > 1.0:
            logger.info(f"⚠️  MPS 有小幅提升 ({speedup:.2f}x)，但提升不明显")
            logger.info("建议：根据实际场景决定是否启用 MPS")
        else:
            logger.warning("❌ MPS 反而更慢，建议继续使用 CPU")

    logger.info("\n如需应用 MPS 加速，请参考以下步骤:")
    logger.info("1. 备份 FunASR 源码文件")
    logger.info("2. 修改 auto_model.py 中的设备检测逻辑")
    logger.info("3. 更新 config.json: \"device\": \"mps\"")


if __name__ == "__main__":
    main()
