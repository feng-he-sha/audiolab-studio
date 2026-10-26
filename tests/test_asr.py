from __future__ import annotations

import pytest

from audiolab.core import asr
from audiolab.core.schemas import TranscriptResult, TranscriptSegment


def _result() -> TranscriptResult:
    return TranscriptResult(
        backend="sensevoice",
        language="zh",
        text="你好世界",
        segments=[
            TranscriptSegment(id=1, start=0.0, stop=1.25, text="你好", language="zh", emotion="NEUTRAL", event="Speech"),
            TranscriptSegment(id=2, start=1.25, stop=2.5, text="世界", language="zh"),
        ],
    )


def test_subtitle_exports() -> None:
    result = _result()
    srt = asr.to_srt(result)
    assert "00:00:00,000 --> 00:00:01,250" in srt
    assert "你好" in srt

    vtt = asr.to_vtt(result)
    assert vtt.startswith("WEBVTT")
    assert "00:00:01.250 --> 00:00:02.500" in vtt

    txt = asr.to_txt(result)
    assert "[00:00:00] 你好" in txt


def test_sensevoice_model_discovery() -> None:
    # This machine has a local DSH SenseVoice bundle; CI may not, so only assert
    # that discovery is non-throwing and, when found, has the expected files.
    model_dir = asr.resolve_model_dir()
    if model_dir is None:
        pytest.skip("SenseVoice model not installed")
    assert (model_dir / "tokens.txt").is_file()
    assert (model_dir / "model.int8.onnx").is_file() or (model_dir / "model.onnx").is_file()
