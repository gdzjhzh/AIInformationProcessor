import types
import shutil
from pathlib import Path

import pytest

import video_transcript_api.api.services.transcription as transcription
from video_transcript_api.downloaders.models import VideoMetadata, DownloadInfo


class DummyQueue:
    def __init__(self):
        self.items = []

    def put(self, item):
        self.items.append(item)


class DummyNotifier:
    def __init__(self, webhook=None):
        self.webhook = webhook
        self.messages = []

    def notify_task_status(self, *args, **kwargs):
        self.messages.append(("notify", args, kwargs))

    def send_text(self, text, **kwargs):
        self.messages.append(("send_text", text, kwargs))

    def _clean_url(self, url):
        return url


class DummyCacheManager:
    def __init__(self, cache_data=None, artifact_dir=None):
        self.cache_data = cache_data
        self.artifact_dir = Path(artifact_dir) if artifact_dir else None
        self.artifacts = []
        self.saved = []
        self.status_updates = []
        self.tasks = {}

    def get_cache(self, platform, media_id, use_speaker_recognition):
        return self.cache_data

    def save_cache(self, **kwargs):
        self.saved.append(kwargs)
        return True

    def save_download_artifact(self, platform, media_id, source_file, filename=None):
        if not self.artifact_dir:
            return None
        source_path = Path(source_file)
        target_dir = self.artifact_dir / platform / media_id
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / (filename or source_path.name)
        shutil.copy2(source_path, target_path)
        result = {
            "download_file_path": str(target_path),
            "download_file_relative_path": str(target_path.relative_to(self.artifact_dir)).replace("\\", "/"),
            "download_file_name": target_path.name,
            "download_file_size": target_path.stat().st_size,
        }
        self.artifacts.append(result)
        return result

    def update_task_status(self, task_id, status, **kwargs):
        self.status_updates.append((task_id, status, kwargs))

    def get_task_by_id(self, task_id):
        return self.tasks.get(task_id)


class DummyTranscriber:
    def __init__(self, *args, **kwargs):
        pass

    def transcribe(self, local_file, output_base):
        return {"transcript": "transcribed text"}


class DummyFunASR:
    def __init__(self, *args, **kwargs):
        pass

    def transcribe_sync(self, local_file):
        return {
            "formatted_text": "funasr text",
            "transcription_result": [{"speaker": "spk_0", "text": "hello"}],
        }

    def format_transcript_with_speakers(self, data):
        return "funasr formatted"


class YoutubeDownloader:
    def __init__(
        self,
        subtitle=None,
        download_url="http://example.com/audio.mp3",
        filename="test.mp3",
        local_file=None,
    ):
        self._subtitle = subtitle
        self._download_url = download_url
        self._filename = filename
        self._local_file = local_file
        self.use_api_server = False

    def get_metadata(self, url):
        return VideoMetadata(
            video_id="abc123",
            platform="youtube",
            title="test title",
            author="test author",
            description="test desc",
        )

    def get_download_info(self, url):
        return DownloadInfo(
            download_url=self._download_url,
            file_ext="mp3",
            filename=self._filename,
        )

    def get_subtitle(self, url):
        return self._subtitle

    def download_file(self, url, filename):
        return self._local_file or "C:/tmp/test.mp3"

    def fetch_for_transcription(self, *args, **kwargs):
        raise AssertionError("fetch_for_transcription should not be called in this test")


class GenericDownloader:
    def __init__(self):
        self.calls = []

    def download_file(self, url, filename):
        self.calls.append((url, filename))
        return "C:/tmp/direct.mp3"


@pytest.fixture
def patch_runtime(monkeypatch):
    queue = DummyQueue()
    monkeypatch.setattr(transcription, "llm_task_queue", queue)
    monkeypatch.setattr(transcription, "WechatNotifier", DummyNotifier)
    monkeypatch.setattr(transcription, "send_long_text_wechat", lambda *args, **kwargs: None)
    monkeypatch.setattr(transcription, "Transcriber", DummyTranscriber)
    monkeypatch.setattr(transcription, "FunASRSpeakerClient", DummyFunASR)
    monkeypatch.setattr(transcription, "get_base_url", lambda: "http://test")
    return queue


def test_flow_cache_hit(monkeypatch, patch_runtime):
    cache_data = {
        "platform": "youtube",
        "media_id": "abc123",
        "title": "cached title",
        "author": "cached author",
        "description": "cached desc",
        "transcript_type": "capswriter",
        "transcript_data": "cached transcript",
        "use_speaker_recognition": False,
        "llm_calibrated": "calibrated",
        "llm_summary": "summary",
    }
    cache_manager = DummyCacheManager(cache_data=cache_data)
    monkeypatch.setattr(transcription, "cache_manager", cache_manager)

    def fail_create_downloader(url):
        raise AssertionError("create_downloader should not be called on cache hit")

    monkeypatch.setattr(transcription, "create_downloader", fail_create_downloader)

    result = transcription.process_transcription(
        task_id="task_cache_hit",
        url="https://www.youtube.com/watch?v=abc123",
        use_speaker_recognition=False,
        wechat_webhook=None,
        download_url=None,
        metadata_override=None,
    )

    assert result["status"] == "success"
    assert result["data"]["cached"] is True
    assert len(patch_runtime.items) == 0


def test_flow_subtitle_preferred(monkeypatch, patch_runtime):
    cache_manager = DummyCacheManager(cache_data=None)
    monkeypatch.setattr(transcription, "cache_manager", cache_manager)

    downloader = YoutubeDownloader(subtitle="subtitle text")
    monkeypatch.setattr(transcription, "create_downloader", lambda url: downloader)

    result = transcription.process_transcription(
        task_id="task_subtitle",
        url="https://www.youtube.com/watch?v=abc123",
        use_speaker_recognition=False,
        wechat_webhook=None,
        download_url=None,
        metadata_override=None,
    )

    assert result["status"] == "processing"
    assert result["data"]["transcript"] == "subtitle text"
    assert cache_manager.saved
    saved = cache_manager.saved[0]
    assert saved["transcript_type"] == "capswriter"
    assert saved["transcript_data"] == "subtitle text"


def test_flow_download_capswriter(monkeypatch, patch_runtime):
    cache_manager = DummyCacheManager(cache_data=None)
    monkeypatch.setattr(transcription, "cache_manager", cache_manager)

    downloader = YoutubeDownloader(subtitle=None, download_url="http://example.com/audio.mp3", filename="audio.mp3")
    monkeypatch.setattr(transcription, "create_downloader", lambda url: downloader)

    result = transcription.process_transcription(
        task_id="task_download_caps",
        url="https://www.youtube.com/watch?v=abc123",
        use_speaker_recognition=False,
        wechat_webhook=None,
        download_url=None,
        metadata_override=None,
    )

    assert result["status"] == "processing"
    assert result["data"]["transcript"] == "transcribed text"
    assert cache_manager.saved
    saved = cache_manager.saved[0]
    assert saved["transcript_type"] == "capswriter"
    assert saved["use_speaker_recognition"] is False


def test_flow_download_funasr(monkeypatch, patch_runtime):
    cache_manager = DummyCacheManager(cache_data=None)
    monkeypatch.setattr(transcription, "cache_manager", cache_manager)

    downloader = YoutubeDownloader(subtitle=None, download_url="http://example.com/audio.mp3", filename="audio.mp3")
    monkeypatch.setattr(transcription, "create_downloader", lambda url: downloader)

    result = transcription.process_transcription(
        task_id="task_download_funasr",
        url="https://www.youtube.com/watch?v=abc123",
        use_speaker_recognition=True,
        wechat_webhook=None,
        download_url=None,
        metadata_override=None,
    )

    assert result["status"] == "processing"
    assert result["data"]["speaker_recognition"] is True
    assert cache_manager.saved
    saved = cache_manager.saved[0]
    assert saved["transcript_type"] == "funasr"
    assert saved["use_speaker_recognition"] is True


def test_flow_separate_download_url(monkeypatch, patch_runtime):
    cache_manager = DummyCacheManager(cache_data=None)
    monkeypatch.setattr(transcription, "cache_manager", cache_manager)

    metadata_downloader = YoutubeDownloader(subtitle=None)
    monkeypatch.setattr(transcription, "create_downloader", lambda url: metadata_downloader)

    generic_downloader = GenericDownloader()
    import video_transcript_api.downloaders.generic as generic_module
    monkeypatch.setattr(generic_module, "GenericDownloader", lambda: generic_downloader)

    result = transcription.process_transcription(
        task_id="task_separate_url",
        url="https://www.youtube.com/watch?v=abc123",
        use_speaker_recognition=False,
        wechat_webhook=None,
        download_url="http://example.com/file.mp3",
        metadata_override=None,
    )

    assert result["status"] == "processing"
    assert generic_downloader.calls
    assert generic_downloader.calls[0][0] == "http://example.com/file.mp3"
    assert generic_downloader.calls[0][1] == "file.mp3"


def test_flow_download_capswriter_deletes_audio_after_transcription(
    monkeypatch, patch_runtime, tmp_path
):
    temp_dir = tmp_path / "temp"
    cache_dir = tmp_path / "cache"
    temp_dir.mkdir()
    cache_dir.mkdir()
    local_audio = temp_dir / "audio.mp3"
    local_audio.write_bytes(b"audio bytes")

    monkeypatch.setattr(
        transcription,
        "config",
        {
            "storage": {
                "temp_dir": str(temp_dir),
                "cache_dir": str(cache_dir),
            }
        },
    )
    cache_manager = DummyCacheManager(cache_data=None, artifact_dir=cache_dir)
    monkeypatch.setattr(transcription, "cache_manager", cache_manager)

    downloader = YoutubeDownloader(
        subtitle=None,
        download_url="http://example.com/audio.mp3",
        filename="audio.mp3",
        local_file=str(local_audio),
    )
    monkeypatch.setattr(transcription, "create_downloader", lambda url: downloader)

    result = transcription.process_transcription(
        task_id="task_delete_audio",
        url="https://www.youtube.com/watch?v=abc123",
        use_speaker_recognition=False,
        wechat_webhook=None,
        download_url=None,
        metadata_override=None,
    )

    assert result["status"] == "processing"
    assert not local_audio.exists()
    assert cache_manager.artifacts
    artifact_path = Path(cache_manager.artifacts[0]["download_file_path"])
    assert not artifact_path.exists()
    cleanup = result["data"]["audio_cleanup"]
    assert cleanup["deleted_count"] == 2
    assert cleanup["deleted_bytes"] == len(b"audio bytes") * 2


def test_flow_youtube_api_deletes_audio_after_transcription(
    monkeypatch, patch_runtime, tmp_path
):
    temp_dir = tmp_path / "temp"
    cache_dir = tmp_path / "cache"
    temp_dir.mkdir()
    cache_dir.mkdir()
    local_audio = temp_dir / "api-audio.m4a"
    local_audio.write_bytes(b"api audio bytes")

    monkeypatch.setattr(
        transcription,
        "config",
        {
            "storage": {
                "temp_dir": str(temp_dir),
                "cache_dir": str(cache_dir),
            }
        },
    )
    cache_manager = DummyCacheManager(cache_data=None)
    monkeypatch.setattr(transcription, "cache_manager", cache_manager)

    downloader = YoutubeDownloader(subtitle=None)
    downloader.use_api_server = True
    downloader.fetch_for_transcription = lambda url, use_speaker_recognition=False: {
        "video_id": "abc123",
        "video_title": "api title",
        "author": "api author",
        "description": "api desc",
        "platform": "youtube",
        "transcript": None,
        "audio_path": str(local_audio),
        "need_transcription": True,
    }
    monkeypatch.setattr(transcription, "create_downloader", lambda url: downloader)

    result = transcription.process_transcription(
        task_id="task_delete_youtube_api_audio",
        url="https://www.youtube.com/watch?v=abc123",
        use_speaker_recognition=False,
        wechat_webhook=None,
        download_url=None,
        metadata_override=None,
    )

    assert result["status"] == "processing"
    assert not local_audio.exists()
    cleanup = result["data"]["audio_cleanup"]
    assert cleanup["deleted_count"] == 1
    assert cleanup["deleted_bytes"] == len(b"api audio bytes")


def test_flow_download_url_skips_youtube_api(monkeypatch, patch_runtime):
    cache_manager = DummyCacheManager(cache_data=None)
    monkeypatch.setattr(transcription, "cache_manager", cache_manager)

    downloader = YoutubeDownloader(subtitle=None)
    downloader.use_api_server = True
    monkeypatch.setattr(transcription, "create_downloader", lambda url: downloader)

    generic_downloader = GenericDownloader()
    import video_transcript_api.downloaders.generic as generic_module
    monkeypatch.setattr(generic_module, "GenericDownloader", lambda: generic_downloader)

    result = transcription.process_transcription(
        task_id="task_download_url_skip_api",
        url="https://www.youtube.com/watch?v=abc123",
        use_speaker_recognition=False,
        wechat_webhook=None,
        download_url="http://example.com/file.mp3",
        metadata_override=None,
    )

    assert result["status"] == "processing"
    assert generic_downloader.calls
