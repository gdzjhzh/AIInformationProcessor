"""转录相关错误"""

from .base import TranscriptAPIError


class ASRConnectionError(TranscriptAPIError):
    """ASR 服务连接失败（可重试）

    CapsWriter 或 FunASR WebSocket 服务不可用时抛出。
    """

    def __init__(self, message: str = "ASR service connection failed"):
        super().__init__(message, retryable=True)


class EmptyTranscriptError(TranscriptAPIError):
    """转录结果为空（不可重试）

    音频文件有效但转录结果为空，通常表示音频中无语音内容。
    """

    def __init__(self, message: str = "Transcript is empty"):
        super().__init__(message, retryable=False)
