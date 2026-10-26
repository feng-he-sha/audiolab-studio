from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from audiolab import config


def test_timbre_encoder_loads_local_checkpoint(tmp_path) -> None:
    weight = Path(config.MODELS) / "colorsplitter" / "timbre-v1.pt"
    if not weight.exists():
        pytest.skip("timbre-v1.pt not downloaded")
    from audiolab.core.timbre_encoder import VoiceEncoder, preprocess_wav

    sr = 16000
    t = np.arange(sr * 3) / sr
    wav = (0.1 * np.sin(2 * np.pi * 180 * t) + 0.05 * np.sin(2 * np.pi * 360 * t)).astype(np.float32)
    clip = tmp_path / "clip.wav"
    sf.write(clip, wav, sr)
    encoder = VoiceEncoder(device="cpu", weights_fpath=weight)
    prepared = preprocess_wav(clip, trim_silences=False)
    emb = encoder.embed_utterance(prepared)
    assert emb.shape == (256,)
    assert abs(float(np.linalg.norm(emb)) - 1.0) < 1e-4
