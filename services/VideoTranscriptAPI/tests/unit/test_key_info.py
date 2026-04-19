"""
KeyInfo unit tests.

Covers:
- KeyInfo dataclass creation and serialization
- from_dict with missing fields
- format_for_prompt output format
- Empty KeyInfo formatting

All console output must be in English only (no emoji, no Chinese).
"""

import pytest
from video_transcript_api.llm.core.key_info_extractor import KeyInfo


class TestKeyInfo:
    """Test KeyInfo dataclass."""

    def test_create_with_all_fields(self):
        """Should create KeyInfo with all fields."""
        ki = KeyInfo(
            names=["Zhang San"],
            places=["Beijing"],
            technical_terms=["GPT-4"],
            brands=["OpenAI"],
            abbreviations=["AI"],
            foreign_terms=["machine learning"],
            other_entities=["2024"],
        )
        assert ki.names == ["Zhang San"]
        assert ki.brands == ["OpenAI"]

    def test_to_dict(self):
        """to_dict should return all fields."""
        ki = KeyInfo(
            names=["A"], places=["B"], technical_terms=["C"],
            brands=["D"], abbreviations=["E"], foreign_terms=["F"],
            other_entities=["G"],
        )
        d = ki.to_dict()
        assert d["names"] == ["A"]
        assert d["other_entities"] == ["G"]
        assert len(d) == 7

    def test_from_dict_complete(self):
        """from_dict with all fields should work."""
        data = {
            "names": ["X"], "places": ["Y"], "technical_terms": ["Z"],
            "brands": ["W"], "abbreviations": ["V"], "foreign_terms": ["U"],
            "other_entities": ["T"],
        }
        ki = KeyInfo.from_dict(data)
        assert ki.names == ["X"]
        assert ki.other_entities == ["T"]

    def test_from_dict_missing_fields(self):
        """from_dict with missing fields should use empty lists."""
        ki = KeyInfo.from_dict({"names": ["Alice"]})
        assert ki.names == ["Alice"]
        assert ki.places == []
        assert ki.technical_terms == []
        assert ki.brands == []

    def test_from_dict_empty(self):
        """from_dict with empty dict should have all empty lists."""
        ki = KeyInfo.from_dict({})
        assert ki.names == []
        assert ki.places == []

    def test_roundtrip(self):
        """to_dict -> from_dict should preserve data."""
        original = KeyInfo(
            names=["A", "B"], places=["C"], technical_terms=[],
            brands=["D"], abbreviations=[], foreign_terms=["E"],
            other_entities=[],
        )
        restored = KeyInfo.from_dict(original.to_dict())
        assert restored.names == original.names
        assert restored.brands == original.brands
        assert restored.foreign_terms == original.foreign_terms


class TestKeyInfoFormatForPrompt:
    """Test format_for_prompt output."""

    def test_all_fields_populated(self):
        """All populated fields should appear in output."""
        ki = KeyInfo(
            names=["Alice", "Bob"],
            places=["Tokyo"],
            technical_terms=["PyTorch"],
            brands=["Apple"],
            abbreviations=["AI"],
            foreign_terms=["deep learning"],
            other_entities=["2024"],
        )
        text = ki.format_for_prompt()
        assert "Alice" in text
        assert "Bob" in text
        assert "Tokyo" in text
        assert "PyTorch" in text
        assert "Apple" in text

    def test_partial_fields(self):
        """Only populated fields should appear."""
        ki = KeyInfo(
            names=["Alice"], places=[], technical_terms=["GPT"],
            brands=[], abbreviations=[], foreign_terms=[],
            other_entities=[],
        )
        text = ki.format_for_prompt()
        assert "Alice" in text
        assert "GPT" in text
        assert "brand" not in text.lower()  # Empty field not shown

    def test_empty_returns_default(self):
        """All empty fields should return default message."""
        ki = KeyInfo(
            names=[], places=[], technical_terms=[],
            brands=[], abbreviations=[], foreign_terms=[],
            other_entities=[],
        )
        text = ki.format_for_prompt()
        assert text != ""  # Should return default text

    def test_format_contains_correct_labels(self):
        """Output should contain Chinese labels."""
        ki = KeyInfo(
            names=["X"], places=["Y"], technical_terms=[],
            brands=[], abbreviations=[], foreign_terms=[],
            other_entities=[],
        )
        text = ki.format_for_prompt()
        assert "人名" in text
        assert "地名" in text
