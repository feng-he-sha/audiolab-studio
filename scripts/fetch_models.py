"""Pre-download AudioLab Studio models (resumable, mirror-aware)."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from audiolab import config  # noqa: E402
from audiolab.engines import models  # noqa: E402
from audiolab.engines.registry import MODEL_BY_ID, refresh_model_rows  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", help="只下载指定模型 id")
    parser.add_argument("--skip-ast", action="store_true", help="跳过 AST（约 350MB）")
    parser.add_argument(
        "--recommended",
        action="store_true",
        help="只下载推荐模型（MDX HQ4 + 音色 + VAD，约 80MB），跳过 BS-Roformer/AST 大模型",
    )
    parser.add_argument("--mirror", default=os.environ.get("HF_ENDPOINT", "https://hf-mirror.com"))
    args = parser.parse_args()
    if args.mirror:
        os.environ.setdefault("HF_ENDPOINT", args.mirror)
    config.ensure_dirs()
    print(f"模型目录: {config.load_settings().models_dir}")
    print(f"HF 镜像: {os.environ.get('HF_ENDPOINT') or 'https://huggingface.co'}")

    recommended = ["separation.mdx_fast", "timbre.colorsplitter", "vad.silero"]
    targets = [args.model] if args.model else (recommended if args.recommended else list(MODEL_BY_ID))
    if args.skip_ast:
        targets = [m for m in targets if m != "tagging.ast"]
    for model_id in targets:
        spec = MODEL_BY_ID.get(model_id)
        if not spec:
            print(f"未知模型: {model_id}")
            continue
        if model_id == "tagging.ast" and args.skip_ast:
            continue
        print(f"\n=== {spec.label} ({model_id}) ===")
        last = [-1.0]

        def progress(pct: float, msg: str) -> None:
            if pct - last[0] >= 0.5 or pct >= 100:
                last[0] = pct
                print(f"\r{pct:5.1f}% {msg[:90]:<90}", end="", flush=True)

        try:
            models.download_model(model_id, progress)
            print("\nOK")
        except Exception as exc:
            print(f"\n失败: {exc}")
    print("\n=== 状态 ===")
    for row in refresh_model_rows():
        print(f"{row['status']:<9} {row['id']:<26} {row['label']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
