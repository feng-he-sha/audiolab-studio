"""Command line interface for AudioLab Studio."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from audiolab import __version__, config


def cmd_doctor(_: argparse.Namespace) -> int:
    from audiolab.server.app import _doctor

    result = _doctor()
    print(f"AudioLab Studio {result['version']}")
    for check in result["checks"]:
        mark = "OK  " if check["ok"] else "FAIL"
        print(f"[{mark}] {check['name']}: {check['detail']}")
        if not check["ok"] and check.get("hint"):
            print(f"       -> {check['hint']}")
    return 0 if result["ok"] else 1


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from audiolab.server.app import app

    uvicorn.run(app, host=args.host, port=args.port, log_level=args.log_level)
    return 0


def cmd_studio(args: argparse.Namespace) -> int:
    from audiolab import studio

    return studio.main(port=args.port, host=args.host, no_window=args.no_window)


def cmd_analyze(args: argparse.Namespace) -> int:
    from audiolab.core import media
    from audiolab.core.pipeline import analyze

    source = Path(args.input).expanduser().resolve()
    info = media.probe(source)
    out_dir = Path(args.output).resolve() if args.output else config.outputs_dir() / f"{source.stem}_{info.sha256[:8]}"
    out_dir.mkdir(parents=True, exist_ok=True)

    def progress(stage: str, pct: float, message: str = "") -> None:
        print(f"\r[{pct:5.1f}%] {stage:<12} {message[:60]:<60}", end="", flush=True)

    result = analyze(
        project_id=out_dir.name,
        source_path=str(source),
        out_dir=out_dir,
        params={
            "quality": args.quality,
            "clusters": args.clusters,
            "skip_tagging": args.no_tagging,
            "skip_asr": args.skip_asr,
            "asr_language": args.asr_language,
            "asr_model_dir": args.asr_model_dir,
            "force": args.force,
        },
        progress=progress,
    )
    print()
    print(json.dumps(result.timeline.summary, ensure_ascii=False, indent=2))
    if result.transcript is not None:
        print(f"转写: {len(result.transcript.segments)} 段 / {len(result.transcript.text)} 字")
    print(f"输出: {out_dir}")
    print(f"报告: {out_dir / 'report.html'}")
    return 0


def cmd_process(args: argparse.Namespace) -> int:
    from audiolab.core.pipeline import process

    source = Path(args.input).expanduser().resolve()
    out_dir = Path(args.output).resolve() if args.output else config.outputs_dir() / f"{source.stem}_processed"
    out_dir.mkdir(parents=True, exist_ok=True)

    def progress(stage: str, pct: float, message: str = "") -> None:
        print(f"\r[{pct:5.1f}%] {stage:<12} {message[:60]:<60}", end="", flush=True)

    result = process(
        project_id=out_dir.name,
        source_path=str(source),
        out_dir=out_dir,
        preset=args.preset,
        params={"mux_video": args.mux_video},
        progress=progress,
    )
    print()
    print(f"输出: {result.output_path}")
    return 0


def cmd_models(args: argparse.Namespace) -> int:
    from audiolab.engines import models

    if args.action == "list":
        from audiolab.engines.registry import refresh_model_rows

        for row in refresh_model_rows():
            print(f"{row['status']:<9} {row['id']:<26} {row['label']}  ({row['size'] / 1048576:.0f} MB)")
        return 0
    if args.action == "fetch":
        if args.model:
            models.download_model(args.model, lambda pct, msg: print(f"\r{pct:5.1f}% {msg[:80]}", end="", flush=True))
            print()
        else:
            results = models.download_all(
                lambda pct, msg: print(f"\r{pct:5.1f}% {msg[:80]}", end="", flush=True)
            )
            print()
            for key, value in results.items():
                print(f"{key}: {value}")
        return 0
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="audiolab", description="AudioLab Studio 音频人声工作台")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("doctor", help="检查环境")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("studio", help="启动桌面工作台")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=7861)
    p.add_argument("--no-window", action="store_true", help="只启动本地服务，不打开窗口")
    p.set_defaults(func=cmd_studio)

    p = sub.add_parser("serve", help="启动 FastAPI 服务（开发用）")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=7861)
    p.add_argument("--log-level", default="info")
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("analyze", help="命令行分析一个文件")
    p.add_argument("input")
    p.add_argument("--output", "-o")
    p.add_argument("--quality", default="balanced", choices=["fast", "balanced", "hq"])
    p.add_argument("--clusters", type=int)
    p.add_argument("--no-tagging", action="store_true")
    p.add_argument("--skip-asr", action="store_true", help="跳过 SenseVoice 语音转写")
    p.add_argument("--asr-language", default="auto", choices=["auto", "zh", "en", "ja", "ko", "yue"])
    p.add_argument("--asr-model-dir", default="", help="SenseVoice ONNX 模型目录（含 model.int8.onnx + tokens.txt）")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_analyze)

    p = sub.add_parser("process", help="命令行处理一个文件")
    p.add_argument("input")
    p.add_argument("--output", "-o")
    p.add_argument("--preset", default="douyin", choices=["douyin", "podcast", "movie", "music", "clean"])
    p.add_argument("--mux-video", action="store_true")
    p.set_defaults(func=cmd_process)

    p = sub.add_parser("models", help="模型管理")
    p.add_argument("action", choices=["list", "fetch"])
    p.add_argument("--model")
    p.set_defaults(func=cmd_models)
    return parser


def main(argv: list[str] | None = None) -> int:
    config.ensure_dirs()
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
