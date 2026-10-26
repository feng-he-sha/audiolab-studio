"""Generate deterministic speech/music/movie samples for smoke tests and demos."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "samples" / "generated"
SR = 48000


def speech(path: Path) -> bool:
    OUT.mkdir(parents=True, exist_ok=True)
    ps1 = OUT / "_tts.ps1"
    ps1.write_text(
        "Add-Type -AssemblyName System.Speech\n"
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer\n"
        "try { $s.SelectVoice('Microsoft Huihui Desktop') } catch {}\n"
        f"$s.SetOutputToWaveFile('{path}')\n"
        "$s.Speak('大家好，欢迎使用音频人声工作台。这是一段用于测试的中文录音，包含背景音乐和人声。')\n"
        "$s.Dispose()\n",
        encoding="utf-8-sig",
    )
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps1)],
            check=True,
            capture_output=True,
            timeout=120,
        )
        return path.exists()
    except Exception as exc:
        print(f"TTS failed: {exc}")
        return False


def synth_music(duration: float = 30.0) -> np.ndarray:
    rng = np.random.default_rng(7)
    n = int(duration * SR)
    t = np.arange(n) / SR
    audio = np.zeros((n, 2), dtype=np.float32)
    chords = [
        [261.63, 329.63, 392.00],
        [196.00, 246.94, 293.66],
        [220.00, 261.63, 329.63],
        [174.61, 220.00, 261.63],
    ]
    beat = 60.0 / 100.0
    bar = beat * 4
    for i in range(int(duration / bar) + 1):
        start = i * bar
        chord = chords[i % len(chords)]
        for note in chord:
            for harmonic, amp in ((1, 0.20), (2, 0.08), (3, 0.04)):
                freq = note * harmonic
                idx = int(start * SR)
                length = int(bar * SR)
                if idx >= n:
                    continue
                tt = np.arange(min(length, n - idx)) / SR
                env = np.exp(-tt * 1.8) * (1 - np.exp(-tt * 80))
                wave = np.sin(2 * np.pi * freq * tt) * env * amp
                audio[idx : idx + len(wave), 0] += wave
                audio[idx : idx + len(wave), 1] += wave * 0.95
        # kick
        idx = int(start * SR)
        length = int(0.18 * SR)
        if idx < n:
            tt = np.arange(min(length, n - idx)) / SR
            kick = np.sin(2 * np.pi * (55 + 60 * np.exp(-tt * 30)) * tt) * np.exp(-tt * 18) * 0.35
            audio[idx : idx + len(kick), 0] += kick
            audio[idx : idx + len(kick), 1] += kick
        # snare on beats 2/4
        for offset in (beat, beat * 3):
            idx = int((start + offset) * SR)
            length = int(0.12 * SR)
            if idx < n:
                noise = rng.normal(0, 0.08, size=(min(length, n - idx),))
                env = np.exp(-np.arange(len(noise)) / SR * 35)
                audio[idx : idx + len(noise), 0] += noise * env
                audio[idx : idx + len(noise), 1] += noise * env * 0.8
    audio /= max(1e-6, np.max(np.abs(audio)) / 0.7)
    return audio


def load_wav(path: Path) -> tuple[np.ndarray, int]:
    import soundfile as sf

    data, sr = sf.read(str(path), always_2d=True, dtype="float32")
    return data, sr


def fit_stereo(data: np.ndarray, sr: int, n: int) -> np.ndarray:
    if data.shape[1] == 1:
        data = np.repeat(data, 2, axis=1)
    if sr != SR:
        import librosa

        data = librosa.resample(data.T, orig_sr=sr, target_sr=SR).T
    if len(data) < n:
        data = np.pad(data, ((0, n - len(data)), (0, 0)))
    return data[:n].astype(np.float32)


def main() -> int:
    import soundfile as sf

    OUT.mkdir(parents=True, exist_ok=True)
    duration = 30.0
    n = int(duration * SR)
    music = synth_music(duration)
    sf.write(OUT / "music.wav", music, SR)

    speech_path = OUT / "speech.wav"
    has_speech = speech(speech_path)
    if has_speech:
        sp, sr = load_wav(speech_path)
        sp = fit_stereo(sp, sr, n)
        # compress speech into the first 24 seconds
        mix = music.copy()
        mix[:, :] *= 0.32
        active = min(n, len(sp))
        mix[:active] += sp[:active] * 0.9
        sf.write(OUT / "mix.wav", mix, SR)
        movie = mix.copy()
        sf.write(OUT / "movie.wav", movie, SR)
    else:
        mix = music * 0.4
        sf.write(OUT / "mix.wav", mix, SR)
        sf.write(OUT / "movie.wav", mix, SR)

    sf.write(OUT / "silence.wav", np.zeros((int(5 * SR), 2), dtype=np.float32), SR)
    (OUT / "expected.json").write_text(
        json.dumps(
            {
                "speech": {"label": "vocals"},
                "music": {"label": "music"},
                "mix": {"label": "vocals+music"},
                "movie": {"label": "vocals+music"},
                "silence": {"label": "other"},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    # a real video container for import tests
    try:
        subprocess.run(
            [
                "ffmpeg", "-y", "-v", "error",
                "-f", "lavfi", "-i", f"color=c=0x1b2433:s=640x360:d={duration}",
                "-i", str(OUT / "movie.wav"),
                "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
                str(OUT / "movie.mp4"),
            ],
            check=True,
            capture_output=True,
            timeout=180,
        )
    except Exception as exc:
        print(f"video generation skipped: {exc}")
    print(f"samples written to {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
