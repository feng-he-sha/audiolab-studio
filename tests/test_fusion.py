from __future__ import annotations

import numpy as np

from audiolab.core.fusion import fuse


def test_fusion_labels_and_coverage() -> None:
    duration = 10.0
    hop = 0.02
    n = int(duration / hop) + 1
    vocal = np.zeros(n)
    music = np.zeros(n)
    vocal[int(1 / hop) : int(4 / hop)] = 1
    music[int(2 / hop) : int(7 / hop)] = 1
    timeline = fuse(duration, vocal, music)
    assert timeline.duration == duration
    labels = [seg.label for seg in timeline.segments]
    assert "vocals" in labels
    assert "music" in labels
    assert "vocals+music" in labels
    assert abs(sum(seg.stop - seg.start for seg in timeline.segments) - duration) < 0.1
    assert timeline.summary


def test_fusion_silence_is_other() -> None:
    duration = 5.0
    n = int(duration / 0.02) + 1
    timeline = fuse(duration, np.zeros(n), np.zeros(n))
    assert timeline.segments
    assert all(seg.label == "other" for seg in timeline.segments)


def test_fusion_min_gap_merges() -> None:
    duration = 6.0
    hop = 0.02
    n = int(duration / hop) + 1
    vocal = np.zeros(n)
    vocal[int(1 / hop) : int(2 / hop)] = 1
    vocal[int(2.1 / hop) : int(3 / hop)] = 1
    timeline = fuse(duration, vocal, np.zeros(n), min_gap=0.3)
    vocals = [s for s in timeline.segments if s.label == "vocals"]
    assert len(vocals) == 1
