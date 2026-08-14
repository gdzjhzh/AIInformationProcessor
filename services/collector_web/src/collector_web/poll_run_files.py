from collections.abc import Iterator
from pathlib import Path


POLL_RUN_FILE_PATTERN = "*_01_rss_to_obsidian_raw.json"


def _modified_at_ns(path: Path) -> int:
    """读取文件修改时间；文件并发消失时返回最小排序值。"""
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return -1


def _numeric_directories(parent: Path) -> list[Path]:
    """按数字目录名倒序列出直接子目录，忽略并发删除等文件系统异常。"""
    try:
        directories = [
            item for item in parent.iterdir() if item.is_dir() and item.name.isdigit()
        ]
    except OSError:
        return []
    return sorted(directories, key=lambda item: int(item.name), reverse=True)


def _files_by_mtime_desc(directory: Path) -> list[Path]:
    """按修改时间倒序列出单个目录中的轮询摘要文件。"""
    try:
        files = list(directory.glob(POLL_RUN_FILE_PATTERN))
    except OSError:
        return []
    return sorted(files, key=_modified_at_ns, reverse=True)


def _canonical_poll_run_directories(poll_runs_dir: Path) -> Iterator[Path]:
    """按年、月从新到旧遍历标准的 poll_runs/YYYY/MM 目录。"""
    for year_dir in _numeric_directories(poll_runs_dir):
        yield from _numeric_directories(year_dir)


def iter_poll_run_files_newest_first(poll_runs_dir: Path) -> Iterator[Path]:
    """优先按标准年月目录从新到旧遍历轮询摘要，并兼容旧的非标准目录。"""
    if not poll_runs_dir.exists():
        return

    found_canonical_file = False
    for directory in _canonical_poll_run_directories(poll_runs_dir):
        for path in _files_by_mtime_desc(directory):
            found_canonical_file = True
            yield path

    for path in _files_by_mtime_desc(poll_runs_dir):
        found_canonical_file = True
        yield path

    if found_canonical_file:
        return

    try:
        fallback_files = list(poll_runs_dir.rglob(POLL_RUN_FILE_PATTERN))
    except OSError:
        return
    yield from sorted(
        fallback_files,
        key=_modified_at_ns,
        reverse=True,
    )


def find_latest_poll_run_file(poll_runs_dir: Path) -> Path | None:
    """返回最新轮询摘要，避免每次请求递归扫描全部历史文件。"""
    return next(iter_poll_run_files_newest_first(poll_runs_dir), None)
