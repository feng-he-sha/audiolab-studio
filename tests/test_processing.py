from __future__ import annotations

import numpy as np
import soundfile as sf

from audiolab.core import media, processing


def _tone(path) -> None:
    sr = 48000
    t = np.arange(sr * 2) / sr
    wav = (0.2 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    sf.write(path, wav, sr)


def test_probe_peaks_and_presets(tmp_path) -> None:
    source = tmp_path / "tone.wav"
    _tone(source)
    info = media.probe(source)
    assert info.duration > 1.9
    peaks = media.compute_peaks(source, buckets=200)
    assert len(peaks["peaks"]) == 200
    assert abs(peaks["duration"] - info.duration) < 0.1

    for preset, target in (("clean", -14.0), ("douyin", -14.0), ("podcast", -16.0)):
        out = tmp_path / f"{preset}.wav"
        result = processing.render(source, out, preset)
        assert out.exists()
        assert abs(media.duration(out) - info.duration) < 0.3
        if result.loudness.integrated_lufs is not None:
            assert abs(result.loudness.integrated_lufs - target) < 1.0
