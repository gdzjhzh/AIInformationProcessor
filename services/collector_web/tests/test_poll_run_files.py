import os

from collector_web.poll_run_files import find_latest_poll_run_file


def test_find_latest_poll_run_file_skips_empty_future_directories(tmp_path):
    """未来空目录不应阻止从最近的有效年月目录找到最新摘要。"""
    poll_runs_dir = tmp_path / "poll_runs"
    month_dir = poll_runs_dir / "2026" / "08"
    month_dir.mkdir(parents=True)
    (poll_runs_dir / "2028" / "01").mkdir(parents=True)
    older_file = month_dir / "execution-1_01_rss_to_obsidian_raw.json"
    latest_file = month_dir / "execution-2_01_rss_to_obsidian_raw.json"
    older_file.write_text("{}", encoding="utf-8")
    latest_file.write_text("{}", encoding="utf-8")
    os.utime(older_file, (100, 100))
    os.utime(latest_file, (200, 200))

    assert find_latest_poll_run_file(poll_runs_dir) == latest_file


def test_find_latest_poll_run_file_supports_legacy_nested_directories(tmp_path):
    """不存在标准年月文件时仍应兼容旧的非标准嵌套目录。"""
    poll_runs_dir = tmp_path / "poll_runs"
    legacy_dir = poll_runs_dir / "archive" / "legacy"
    legacy_dir.mkdir(parents=True)
    legacy_file = legacy_dir / "execution-1_01_rss_to_obsidian_raw.json"
    legacy_file.write_text("{}", encoding="utf-8")

    assert find_latest_poll_run_file(poll_runs_dir) == legacy_file
