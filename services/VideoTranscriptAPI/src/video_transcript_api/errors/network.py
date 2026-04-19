"""网络相关错误"""

from .base import TranscriptAPIError


class NetworkError(TranscriptAPIError):
    """通用网络错误（可重试）

    包括连接超时、DNS 解析失败、连接被重置等。
    """

    def __init__(self, message: str = "Network error"):
        super().__init__(message, retryable=True)


class DownloadTimeoutError(NetworkError):
    """下载超时错误（可重试）"""

    def __init__(self, message: str = "Download timed out"):
        super().__init__(message)


class HTTPForbiddenError(TranscriptAPIError):
    """HTTP 403 禁止访问（不可重试）

    通常表示 API key 无效、IP 被封禁或资源需要付费。
    """

    def __init__(self, message: str = "HTTP 403 Forbidden"):
        super().__init__(message, retryable=False)
