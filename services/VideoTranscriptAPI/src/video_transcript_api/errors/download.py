"""下载相关错误"""

from .base import TranscriptAPIError


class DownloadFailedError(TranscriptAPIError):
    """文件下载失败（可重试）

    下载过程中发生错误，如文件大小为 0、下载中断等。
    """

    def __init__(self, message: str = "File download failed"):
        super().__init__(message, retryable=True)


class InvalidMediaError(TranscriptAPIError):
    """无效的媒体文件（不可重试）

    下载的文件无法被 ffprobe 识别为有效的音视频文件。
    """

    def __init__(self, message: str = "Invalid media file"):
        super().__init__(message, retryable=False)
