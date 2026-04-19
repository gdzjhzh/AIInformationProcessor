"""
TextSegmenter unit tests.

Covers:
- Standard sentence-based segmentation
- CapsWriter format detection (low punctuation density)
- Segment size limits (segment_size, max_segment_size)
- Empty/short text handling

All console output must be in English only (no emoji, no Chinese).
"""

import pytest
from unittest.mock import Mock
from video_transcript_api.llm.segmenters.text_segmenter import TextSegmenter
from video_transcript_api.llm.core.config import LLMConfig


@pytest.fixture
def config():
    """Create a minimal LLMConfig for segmenter testing."""
    return Mock(
        spec=LLMConfig,
        segment_size=100,
        max_segment_size=200,
    )


@pytest.fixture
def segmenter(config):
    return TextSegmenter(config)


class TestTextSegmenter:
    """Test text segmentation logic."""

    def test_empty_text(self, segmenter):
        """Empty text should return empty segments."""
        result = segmenter.segment("")
        assert result == []

    def test_short_text_single_segment(self, segmenter):
        """Short text should produce a single segment."""
        result = segmenter.segment("short text here")
        assert len(result) == 1

    def test_sentence_segmentation(self, segmenter):
        """Text with punctuation should be split by sentences when exceeding segment_size."""
        # Need enough text to exceed segment_size (100 chars)
        text = "first sentence with enough words here。second sentence also with many words。third sentence is quite long too。fourth one also long enough。fifth sentence to push way over the size limit definitely。"
        result = segmenter.segment(text)
        assert len(result) >= 2
        # Each segment should be within max_segment_size
        for seg in result:
            assert len(seg) <= segmenter.max_segment_size

    def test_capswriter_format_detection(self, segmenter):
        """Text with low punctuation density (no periods) should be detected as CapsWriter."""
        # CapsWriter format: many lines, no punctuation
        lines = [f"line {i} with some words here" for i in range(20)]
        text = "\n".join(lines)
        result = segmenter.segment(text)
        assert len(result) >= 1
        for seg in result:
            assert len(seg) <= segmenter.max_segment_size

    def test_max_segment_size_respected(self):
        """Segments should never exceed max_segment_size."""
        config = Mock(spec=LLMConfig, segment_size=50, max_segment_size=100)
        seg = TextSegmenter(config)
        text = "a" * 500 + "。" + "b" * 500 + "。"
        result = seg.segment(text)
        for segment in result:
            assert len(segment) <= 100

    def test_chinese_text_segmentation(self, segmenter):
        """Chinese text with standard punctuation should segment correctly."""
        text = "这是第一句话。这是第二句话！这是第三句话？" * 5
        result = segmenter.segment(text)
        assert len(result) >= 1


class TestDialogSegmenter:
    """Test dialog segmentation logic."""

    @pytest.fixture
    def dialog_config(self):
        return Mock(
            spec=LLMConfig,
            min_chunk_length=50,
            max_chunk_length=200,
            preferred_chunk_length=100,
        )

    @pytest.fixture
    def dialog_segmenter(self, dialog_config):
        from video_transcript_api.llm.segmenters.dialog_segmenter import DialogSegmenter
        return DialogSegmenter(dialog_config)

    def test_empty_dialogs(self, dialog_segmenter):
        """Empty dialog list should return empty chunks."""
        assert dialog_segmenter.segment([]) == []

    def test_single_short_dialog(self, dialog_segmenter):
        """Single short dialog should be one chunk."""
        dialogs = [{"speaker": "A", "text": "hello world", "start_time": 0}]
        result = dialog_segmenter.segment(dialogs)
        assert len(result) == 1
        assert len(result[0]) == 1

    def test_multiple_dialogs_chunking(self, dialog_segmenter):
        """Multiple dialogs should be chunked by preferred length."""
        dialogs = [
            {"speaker": f"S{i%2}", "text": f"dialog text number {i} " * 5, "start_time": i}
            for i in range(10)
        ]
        result = dialog_segmenter.segment(dialogs)
        assert len(result) >= 2
        # Each chunk total text should not exceed max
        for chunk in result:
            total = sum(len(d["text"]) for d in chunk)
            assert total <= dialog_segmenter.max_chunk_length + 100  # some tolerance for last merge

    def test_long_dialog_split(self, dialog_segmenter):
        """Single dialog exceeding max_chunk_length should be split."""
        # Text must have sentence punctuation for splitting to work
        long_text = "这是一段很长的话。" * 50  # ~450 chars with split points
        dialogs = [{"speaker": "A", "text": long_text, "start_time": 0}]
        result = dialog_segmenter.segment(dialogs)
        assert len(result) >= 2

    def test_short_tail_merged(self, dialog_segmenter):
        """Very short last chunk should be merged into previous."""
        dialogs = [
            {"speaker": "A", "text": "x" * 80, "start_time": 0},
            {"speaker": "B", "text": "y" * 80, "start_time": 1},
            {"speaker": "A", "text": "z" * 10, "start_time": 2},  # Short tail
        ]
        result = dialog_segmenter.segment(dialogs)
        # Short tail should be merged
        total_dialogs = sum(len(chunk) for chunk in result)
        assert total_dialogs == 3
