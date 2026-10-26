"""Vendored timbre/speaker encoder.

The network definition and mel preprocessing are unchanged from Resemblyzer
(MIT, https://github.com/resemble-ai/Resemblyzer) and ColorSplitter (MIT,
https://github.com/KakaruHayate/ColorSplitter). Only the minimum code needed by
AudioLab is kept, so the workbench does not require the ColorSplitter package
(whose git install can be unreliable on Windows).

Checkpoint compatibility: ``models/colorsplitter/timbre-v1.pt``.
"""

from __future__ import annotations

import pickle
from collections.abc import Callable, Sequence
from pathlib import Path

import numpy as np
import torch
from torch import nn

# --- hparams (must stay identical to the checkpoint) -----------------------
SAMPLING_RATE = 16000
MEL_WINDOW_LENGTH = 25  # ms
MEL_WINDOW_STEP = 10  # ms
MEL_N_CHANNELS = 40
PARTIALS_N_FRAMES = 160
AUDIO_NORM_TARGET_DBFS = -30
MODEL_HIDDEN_SIZE = 256
MODEL_EMBEDDING_SIZE = 256
MODEL_NUM_LAYERS = 3
INT16_MAX = (2**15) - 1

ProgressFn = Callable[[int, int], None]


def normalize_volume(
    wav: np.ndarray,
    target_db: float = AUDIO_NORM_TARGET_DBFS,
    increase_only: bool = False,
    decrease_only: bool = False,
) -> np.ndarray:
    if increase_only and decrease_only:
        raise ValueError("Both increase only and decrease only are set")
    rms = np.sqrt(np.mean((wav * INT16_MAX) ** 2))
    if rms <= 1e-9:
        return np.asarray(wav, dtype=np.float32)
    wave_dbfs = 20 * np.log10(rms / INT16_MAX)
    change = target_db - wave_dbfs
    if (change < 0 and increase_only) or (change > 0 and decrease_only):
        return np.asarray(wav, dtype=np.float32)
    return np.asarray(wav * (10 ** (change / 20)), dtype=np.float32)


def wav_to_mel_spectrogram(wav: np.ndarray) -> np.ndarray:
    import librosa

    frames = librosa.feature.melspectrogram(
        y=np.asarray(wav, dtype=np.float32),
        sr=SAMPLING_RATE,
        n_fft=int(SAMPLING_RATE * MEL_WINDOW_LENGTH / 1000),
        hop_length=int(SAMPLING_RATE * MEL_WINDOW_STEP / 1000),
        n_mels=MEL_N_CHANNELS,
    )
    return frames.astype(np.float32).T


def resample_waveform(wav: np.ndarray, orig_sr: int, target_sr: int = SAMPLING_RATE) -> np.ndarray:
    if int(orig_sr) == int(target_sr):
        return np.asarray(wav, dtype=np.float32)
    import librosa

    out = librosa.resample(
        np.asarray(wav, dtype=np.float32), orig_sr=int(orig_sr), target_sr=int(target_sr)
    )
    return np.asarray(out, dtype=np.float32)


def load_waveform(path: str | Path) -> tuple[np.ndarray, int]:
    import librosa

    wav, sr = librosa.load(str(path), sr=None, mono=True)
    return np.asarray(wav, dtype=np.float32), int(sr)


def preprocess_wav(
    path_or_wav: str | Path | np.ndarray,
    source_sr: int | None = None,
    *,
    trim_silences: bool | str = False,
) -> np.ndarray:
    """Resample to 16k, peak-RMS normalise to -30 dBFS.

    Silence trimming is intentionally not implemented (we already cut clean
    vocal clips); passing True would require webrtcvad and is ignored.
    """
    if isinstance(path_or_wav, (str, Path)):
        wav, source_sr = load_waveform(path_or_wav)
    else:
        wav = np.asarray(path_or_wav, dtype=np.float32)
    if source_sr is not None and int(source_sr) != SAMPLING_RATE:
        wav = resample_waveform(wav, int(source_sr), SAMPLING_RATE)
    return normalize_volume(wav, AUDIO_NORM_TARGET_DBFS, increase_only=True)


class VoiceEncoder(nn.Module):
    """Maps mel spectrograms to L2-normalised timbre embeddings."""

    def __init__(
        self,
        device: str | torch.device | None = None,
        weights_fpath: str | Path | None = None,
        amp: bool = False,
        load_weights: bool = True,
    ) -> None:
        super().__init__()
        self.lstm = nn.LSTM(MEL_N_CHANNELS, MODEL_HIDDEN_SIZE, MODEL_NUM_LAYERS, batch_first=True)
        self.linear = nn.Linear(MODEL_HIDDEN_SIZE, MODEL_EMBEDDING_SIZE)
        self.relu = nn.ReLU()
        self.amp = bool(amp)
        if device is None:
            device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        elif isinstance(device, str):
            device = torch.device(device)
        self.device = device

        if load_weights:
            if weights_fpath is None:
                weights_fpath = Path("models/colorsplitter/timbre-v1.pt")
            path = Path(weights_fpath)
            if not path.exists():
                raise FileNotFoundError(f"timbre checkpoint not found: {path}")
            try:
                checkpoint = torch.load(path, map_location="cpu", weights_only=True)
            except Exception:
                checkpoint = torch.load(path, map_location="cpu", weights_only=False)
            state = checkpoint.get("model_state", checkpoint) if isinstance(checkpoint, dict) else checkpoint
            self.load_state_dict(state, strict=False)
        self.to(device)

    def forward(self, mels: torch.FloatTensor) -> torch.FloatTensor:
        _, (hidden, _) = self.lstm(mels)
        raw = self.relu(self.linear(hidden[-1]))
        return raw / torch.norm(raw, dim=1, keepdim=True)

    @staticmethod
    def compute_partial_slices(
        n_samples: int, rate: float = 1.3, min_coverage: float = 0.75
    ) -> tuple[list[slice], list[slice]]:
        assert 0 < min_coverage <= 1
        samples_per_frame = int(SAMPLING_RATE * MEL_WINDOW_STEP / 1000)
        n_frames = int(np.ceil((n_samples + 1) / samples_per_frame))
        frame_step = int(np.round((SAMPLING_RATE / rate) / samples_per_frame))
        if frame_step <= 0:
            frame_step = 1
        wav_slices: list[slice] = []
        mel_slices: list[slice] = []
        steps = max(1, n_frames - PARTIALS_N_FRAMES + frame_step + 1)
        for i in range(0, steps, frame_step):
            mel_range = np.array([i, i + PARTIALS_N_FRAMES])
            wav_range = mel_range * samples_per_frame
            mel_slices.append(slice(*mel_range))
            wav_slices.append(slice(*wav_range))
        last = wav_slices[-1]
        coverage = (n_samples - last.start) / max(1, last.stop - last.start)
        if coverage < min_coverage and len(mel_slices) > 1:
            mel_slices, wav_slices = mel_slices[:-1], wav_slices[:-1]
        return wav_slices, mel_slices

    def _mel_partials(self, wav: np.ndarray, rate: float, min_coverage: float) -> np.ndarray:
        wav_slices, mel_slices = self.compute_partial_slices(len(wav), rate, min_coverage)
        max_wave_length = wav_slices[-1].stop
        if max_wave_length >= len(wav):
            wav = np.pad(wav, (0, max_wave_length - len(wav)), "constant")
        mel = wav_to_mel_spectrogram(wav)
        return np.array([mel[s] for s in mel_slices], dtype=np.float32)

    @torch.no_grad()
    def embed_utterance(
        self,
        wav: np.ndarray,
        return_partials: bool = False,
        rate: float = 1.3,
        min_coverage: float = 0.75,
    ):
        wav_slices, mel_slices = self.compute_partial_slices(len(wav), rate, min_coverage)
        max_wave_length = wav_slices[-1].stop
        if max_wave_length >= len(wav):
            wav = np.pad(wav, (0, max_wave_length - len(wav)), "constant")
        mel = wav_to_mel_spectrogram(wav)
        mels = torch.from_numpy(np.array([mel[s] for s in mel_slices])).to(self.device)
        partial = self(mels).float().cpu().numpy()
        raw = np.mean(partial, axis=0)
        norm = np.linalg.norm(raw, 2)
        embed = raw / norm if norm > 0 else raw
        if return_partials:
            return embed, partial, wav_slices
        return embed

    @torch.no_grad()
    def embed_utterances(
        self,
        wavs: Sequence[np.ndarray],
        rate: float = 1.3,
        min_coverage: float = 0.75,
        batch_size: int = 64,
        progress: ProgressFn | None = None,
    ) -> np.ndarray:
        if not wavs:
            return np.zeros((0, MODEL_EMBEDDING_SIZE), dtype=np.float32)
        parts: list[np.ndarray] = []
        counts: list[int] = []
        for wav in wavs:
            m = self._mel_partials(np.asarray(wav, dtype=np.float32), rate, min_coverage)
            parts.append(m)
            counts.append(int(m.shape[0]))
        all_mels = np.concatenate(parts, axis=0)
        partial = self._forward_batched(all_mels, batch_size, progress)
        out = np.empty((len(wavs), MODEL_EMBEDDING_SIZE), dtype=np.float32)
        start = 0
        for i, count in enumerate(counts):
            raw = partial[start : start + count].mean(axis=0)
            norm = np.linalg.norm(raw, 2)
            out[i] = raw / norm if norm > 0 else raw
            start += count
        return out

    def _forward_batched(
        self, mels: np.ndarray, batch_size: int, progress: ProgressFn | None = None
    ) -> np.ndarray:
        total = int(mels.shape[0])
        batch_size = max(1, int(batch_size))
        chunks: list[np.ndarray] = []
        use_amp = self.amp and self.device.type == "cuda"
        for start in range(0, total, batch_size):
            chunk = torch.from_numpy(mels[start : start + batch_size]).to(self.device)
            if use_amp:
                with torch.autocast(device_type="cuda", dtype=torch.float16):
                    embeds = self(chunk)
            else:
                embeds = self(chunk)
            chunks.append(embeds.float().cpu().numpy())
            if progress is not None:
                progress(min(start + batch_size, total), total)
        return np.concatenate(chunks, axis=0) if chunks else np.zeros((0, MODEL_EMBEDDING_SIZE), np.float32)
