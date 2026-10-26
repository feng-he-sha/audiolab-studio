"""Offline single-file HTML report (Chinese UI, no CDN, inline CSS/JS).

The report embeds the timeline, segment table, waveform, timbre clusters/PCA
scatter and audio players whose ``src`` are relative paths, so the HTML file can
be opened directly from disk (``/api/projects/{id}/report`` serves the same
file).
"""

from __future__ import annotations

import html
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import quote

from audiolab.core.schemas import AnalysisResult, Artifact, Segment, TimbreCluster, TimbreFeatures

__all__ = ["build"]

LABEL_NAMES = {
    "vocals": "人声",
    "music": "音乐",
    "vocals+music": "人声+音乐",
    "other": "其他",
}
LABEL_COLORS = {
    "vocals": "#60a5fa",
    "music": "#34d399",
    "vocals+music": "#a78bfa",
    "other": "#94a3b8",
}
KIND_NAMES = {
    "original": "原始音频",
    "vocals": "人声",
    "instrumental": "伴奏",
    "processed": "处理结果",
    "preview": "预览",
    "report": "报告",
}

_CSS = """
:root{--bg:#0b0e14;--panel:#121722;--panel-2:#171e2b;--line:#263041;--text:#e6edf7;
--muted:#8b9bb4;--accent:#5eead4;--accent-2:#38bdf8;--vocals:#60a5fa;--music:#34d399;
--mixed:#a78bfa;--other:#94a3b8;--danger:#f87171;--warn:#fbbf24}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font-family:"Segoe UI","Microsoft YaHei UI",system-ui,-apple-system,sans-serif;font-size:14px;line-height:1.55}
a{color:var(--accent-2);text-decoration:none}
.wrap{max-width:1180px;margin:0 auto;padding:28px 22px 60px}
header.top{display:flex;flex-wrap:wrap;gap:14px;align-items:flex-end;justify-content:space-between;border-bottom:1px solid var(--line);padding-bottom:16px;margin-bottom:22px}
h1{font-size:24px;margin:0 0 4px}
h2{font-size:18px;margin:34px 0 12px;display:flex;align-items:center;gap:8px}
h2::before{content:"";width:4px;height:18px;border-radius:2px;background:var(--accent);display:inline-block}
.sub{color:var(--muted);font-size:12px}
.chips{display:flex;flex-wrap:wrap;gap:8px}
.chip{border:1px solid var(--line);background:var(--panel-2);border-radius:999px;padding:4px 12px;font-size:12px;color:var(--muted)}
.chip b{color:var(--text);font-weight:600}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
.card .k{color:var(--muted);font-size:12px}
.card .v{font-size:22px;font-weight:650;margin-top:4px;font-variant-numeric:tabular-nums}
.card .v small{font-size:12px;color:var(--muted);font-weight:400}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:16px}
.players{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px}
.player{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:12px 14px}
.player .t{font-size:13px;margin-bottom:8px;color:var(--text)}
.player audio{width:100%;height:34px}
svg{display:block;width:100%;height:auto;background:var(--panel);border:1px solid var(--line);border-radius:12px}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{text-align:left;padding:7px 10px;border-bottom:1px solid var(--line);white-space:nowrap}
th{color:var(--muted);font-weight:600;font-size:12px;position:sticky;top:0;background:var(--panel)}
tr:hover td{background:var(--panel-2);cursor:pointer}
.tag{display:inline-block;border:1px solid var(--line);border-radius:6px;padding:1px 7px;margin:1px 3px 1px 0;font-size:11px;color:var(--muted)}
.dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:6px;vertical-align:middle}
.tablewrap{max-height:520px;overflow:auto;border:1px solid var(--line);border-radius:12px;background:var(--panel)}
.clusters{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:14px}
.cluster{border:1px solid var(--line);border-radius:12px;padding:14px;background:var(--panel)}
.cluster h3{margin:0 0 6px;font-size:15px}
.cluster .meta{color:var(--muted);font-size:12px;margin-bottom:10px}
.grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:16px;align-items:start}
.feat{display:grid;grid-template-columns:repeat(auto-fit,minmax(112px,1fr));gap:8px;margin:10px 0}
.feat div{background:var(--panel-2);border-radius:8px;padding:6px 9px;font-size:12px}
.feat span{display:block;color:var(--muted);font-size:11px}
.warn{color:var(--warn)}
.err{color:var(--danger)}
.rep{display:flex;flex-wrap:wrap;gap:8px;margin-top:8px}
.rep .clip{background:var(--panel-2);border:1px solid var(--line);border-radius:8px;padding:8px 10px;min-width:200px;flex:1}
.rep audio{width:100%;height:30px;margin-top:6px}
.foot{color:var(--muted);font-size:12px;margin-top:36px;border-top:1px solid var(--line);padding-top:14px}
.empty{color:var(--muted);font-size:13px;padding:14px;text-align:center;border:1px dashed var(--line);border-radius:10px}
.legend{display:flex;flex-wrap:wrap;gap:14px;margin-top:8px;font-size:12px;color:var(--muted)}
"""

_JS = """
(function(){
  var main=document.getElementById('main-audio');
  document.querySelectorAll('tr[data-seek]').forEach(function(row){
    row.addEventListener('click',function(){
      var t=parseFloat(row.getAttribute('data-seek')||'0');
      if(main){main.currentTime=t;main.play().catch(function(){});}
      document.querySelectorAll('tr[data-seek]').forEach(function(r){r.style.outline='';});
      row.style.outline='1px solid #5eead4';
    });
  });
  document.querySelectorAll('[data-seek-btn]').forEach(function(btn){
    btn.addEventListener('click',function(){
      var t=parseFloat(btn.getAttribute('data-seek-btn')||'0');
      if(main){main.currentTime=t;main.play().catch(function(){});}
    });
  });
})();
"""


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _fmt_time(seconds: float) -> str:
    seconds = max(0.0, float(seconds or 0.0))
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    if hours:
        return f"{hours}:{minutes:02d}:{secs:04.1f}"
    return f"{minutes:02d}:{secs:04.1f}"


def _fmt_duration(seconds: float) -> str:
    seconds = max(0.0, float(seconds or 0.0))
    if seconds >= 3600:
        return f"{seconds / 3600:.2f} 小时"
    if seconds >= 60:
        return f"{seconds / 60:.1f} 分钟"
    return f"{seconds:.1f} 秒"


def _fmt_bytes(size: float) -> str:
    size = float(size or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{size:.1f} GB"


def _escape(text: Any) -> str:
    return html.escape(str(text), quote=True)


def _href(path: str | Path, base: Path) -> str:
    """Relative, URL-encoded href from the report directory."""
    try:
        relative = os.path.relpath(str(path), str(base))
    except ValueError:  # different drive on Windows
        return Path(path).as_uri()
    return quote(relative.replace(os.sep, "/"), safe="/._-~")


def _rel(path: str | Path, base: Path) -> str:
    try:
        return Path(path).resolve().relative_to(base.resolve()).as_posix()
    except (ValueError, OSError):
        try:
            return os.path.relpath(str(path), str(base)).replace(os.sep, "/")
        except ValueError:
            return str(path)


def _load_peaks(report_dir: Path) -> dict[str, Any] | None:
    peaks_dir = report_dir / "peaks"
    if not peaks_dir.is_dir():
        return None
    preferred = peaks_dir / "original.json"
    candidates = [preferred] if preferred.is_file() else sorted(peaks_dir.glob("*.json"))
    for candidate in candidates:
        try:
            data = json.loads(candidate.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(data, dict) and data.get("peaks"):
            return data
    return None


def _load_meta(report_dir: Path) -> dict[str, Any]:
    """Optional ``meta.json`` written by ``pipeline.analyze`` (models/timings)."""
    try:
        data = json.loads((report_dir / "meta.json").read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _waveform_svg(peaks: Sequence[Sequence[float]], width: int = 1200, height: int = 130) -> str:
    if not peaks:
        return ""
    center = height / 2.0
    scale = height / 2.0 * 0.92
    count = len(peaks)
    top_points: list[str] = []
    bottom_points: list[str] = []
    step = width / max(1, count - 1)
    for index, pair in enumerate(peaks):
        try:
            low = max(-1.0, min(1.0, float(pair[0])))
            high = max(-1.0, min(1.0, float(pair[1])))
        except (TypeError, ValueError, IndexError):
            continue
        x = round(index * step, 2)
        top_points.append(f"{x},{round(center - high * scale, 2)}")
        bottom_points.append(f"{x},{round(center - low * scale, 2)}")
    if not top_points:
        return ""
    polygon = " ".join(top_points + list(reversed(bottom_points)))
    return (
        f'<polygon points="{polygon}" fill="#38bdf8" fill-opacity="0.35" stroke="none"/>'
        f'<line x1="0" y1="{center}" x2="{width}" y2="{center}" stroke="#263041" stroke-width="1"/>'
    )


def _timeline_svg(
    duration: float,
    segments: Sequence[Segment],
    peaks: Sequence[Sequence[float]] | None = None,
    width: int = 1200,
) -> str:
    duration = max(0.001, float(duration or 0.0))
    wave_height = 120
    bar_y = wave_height + 12
    bar_h = 26
    ruler_y = bar_y + bar_h + 8
    height = ruler_y + 30

    def x_of(seconds: float) -> float:
        return round(min(width, max(0.0, seconds / duration * width)), 2)

    parts: list[str] = [
        f'<rect x="0" y="0" width="{width}" height="{height}" fill="#121722"/>',
    ]
    if peaks:
        parts.append(f'<g transform="translate(0,0)">{_waveform_svg(peaks, width, wave_height)}</g>')
    else:
        parts.append(
            f'<text x="12" y="{wave_height / 2}" fill="#8b9bb4" font-size="12">'
            f"（无波形数据，可先运行分析生成 peaks）</text>"
        )

    for index, segment in enumerate(segments):
        x0 = x_of(segment.start)
        x1 = max(x0 + 0.5, x_of(segment.stop))
        color = LABEL_COLORS.get(segment.label, LABEL_COLORS["other"])
        tooltip = (
            f"{LABEL_NAMES.get(segment.label, segment.label)} "
            f"{_fmt_time(segment.start)}–{_fmt_time(segment.stop)} "
            f"置信度 {segment.confidence:.2f}"
        )
        parts.append(
            f'<rect x="{x0}" y="{bar_y}" width="{round(x1 - x0, 2)}" height="{bar_h}" '
            f'fill="{color}" fill-opacity="0.85" rx="2"><title>{_escape(tooltip)}</title></rect>'
        )

    tick_step = 5.0
    for candidate in (1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600):
        if duration / candidate <= 12:
            tick_step = float(candidate)
            break
    tick = 0.0
    while tick <= duration + 1e-6:
        x = x_of(tick)
        parts.append(
            f'<line x1="{x}" y1="{bar_y + bar_h}" x2="{x}" y2="{ruler_y}" stroke="#263041" stroke-width="1"/>'
        )
        parts.append(
            f'<text x="{x + 3}" y="{ruler_y + 18}" fill="#8b9bb4" font-size="11">'
            f"{_escape(_fmt_time(tick))}</text>"
        )
        tick += tick_step
    legend = "".join(
        f'<span><span class="dot" style="background:{color}"></span>{LABEL_NAMES[label]}</span>'
        for label, color in LABEL_COLORS.items()
    )
    return (
        f'<svg viewBox="0 0 {width} {height}" preserveAspectRatio="none" role="img" '
        f'aria-label="时间轴">{ "".join(parts) }</svg>'
        f'<div class="legend">{legend}</div>'
    )


def _tags_html(tags: dict[str, float]) -> str:
    if not tags:
        return '<span class="tag">—</span>'
    items = sorted(tags.items(), key=lambda kv: kv[1], reverse=True)[:3]
    return "".join(f'<span class="tag">{_escape(name)} {value:.2f}</span>' for name, value in items)


def _feature_cards(features: TimbreFeatures) -> str:
    f0 = f"{features.f0_median:.0f} Hz" if features.f0_median else "—"
    items = [
        ("基频 F0", f0),
        ("频谱质心", f"{features.centroid_mean:.0f} Hz"),
        ("滚降点", f"{features.rolloff_mean:.0f} Hz"),
        ("谱平坦度", f"{features.flatness_mean:.3f}"),
        ("过零率", f"{features.zcr_mean:.3f}"),
        ("谐波比", f"{features.harmonic_ratio * 100:.0f}%"),
        ("响度", f"{features.rms_db:.1f} dBFS"),
        ("浊音占比", f"{features.voiced_ratio * 100:.0f}%"),
    ]
    return "".join(f"<div><span>{name}</span>{value}</div>" for name, value in items)


def _scatter_svg(clusters: Sequence[TimbreCluster], points: Sequence[dict[str, Any]], width: int = 560, height: int = 320) -> str:
    if not points:
        return '<div class="empty">没有音色散点数据</div>'
    xs = [float(p.get("x", 0.0)) for p in points]
    ys = [float(p.get("y", 0.0)) for p in points]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    span_x = max(1e-6, max_x - min_x)
    span_y = max(1e-6, max_y - min_y)
    pad = 34.0
    color_by_cluster = {cluster.index: cluster.color for cluster in clusters}

    def sx(value: float) -> float:
        return round(pad + (value - min_x) / span_x * (width - 2 * pad), 2)

    def sy(value: float) -> float:
        return round(height - pad - (value - min_y) / span_y * (height - 2 * pad), 2)

    parts = [
        f'<rect x="0" y="0" width="{width}" height="{height}" fill="#121722"/>',
        f'<line x1="{pad}" y1="{height - pad}" x2="{width - pad}" y2="{height - pad}" stroke="#263041"/>',
        f'<line x1="{pad}" y1="{pad}" x2="{pad}" y2="{height - pad}" stroke="#263041"/>',
    ]
    for point, x, y in zip(points, xs, ys):
        cluster_id = int(point.get("cluster", 0))
        color = color_by_cluster.get(cluster_id, "#94a3b8")
        label = _escape(point.get("clip_id", ""))
        parts.append(
            f'<circle cx="{sx(x)}" cy="{sy(y)}" r="6" fill="{color}" fill-opacity="0.85" '
            f'stroke="#0b0e14" stroke-width="1"><title>{label}</title></circle>'
        )
    legend = "".join(
        f'<span><span class="dot" style="background:{cluster.color}"></span>'
        f"{_escape(cluster.label)}</span>"
        for cluster in clusters
    )
    return (
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="音色 PCA 散点">{ "".join(parts) }</svg>'
        f'<div class="legend">{legend}</div>'
    )


def _player_html(title: str, src: str, player_id: str = "") -> str:
    ident = f' id="{player_id}"' if player_id else ""
    return (
        f'<div class="player"><div class="t">{_escape(title)}</div>'
        f'<audio{ident} controls preload="metadata" src="{_escape(src)}"></audio></div>'
    )


# ---------------------------------------------------------------------------
# Report builder
# ---------------------------------------------------------------------------

def build(result: AnalysisResult, out_html: str | Path, project_title: str = "") -> Path:
    """Write a self-contained HTML report and return its path."""
    out = Path(out_html)
    out.parent.mkdir(parents=True, exist_ok=True)
    report_dir = out.parent
    base = report_dir

    media_info = result.media
    timeline = result.timeline
    timbre = result.timbre
    title = project_title or (media_info.filename if media_info else "音频分析报告")
    duration = float(timeline.duration or media_info.duration or 0.0)
    peaks = _load_peaks(report_dir)
    meta = _load_meta(report_dir)

    # Overview numbers.
    label_seconds = {label: float(timeline.summary.get(label, 0.0)) for label in LABEL_NAMES}
    vocal_seconds = label_seconds.get("vocals", 0.0) + label_seconds.get("vocals+music", 0.0)
    music_seconds = label_seconds.get("music", 0.0) + label_seconds.get("vocals+music", 0.0)
    vocal_pct = (vocal_seconds / duration * 100.0) if duration else 0.0
    music_pct = (music_seconds / duration * 100.0) if duration else 0.0
    cluster_count = len(timbre.clusters)
    warnings = [*result.warnings, *timeline.warnings, *timbre.warnings]

    artifact_map = {artifact.kind: artifact for artifact in result.artifacts}
    player_order = [("original", "原始音频"), ("vocals", "人声轨"), ("instrumental", "伴奏轨"), ("preview", "预览")]
    players: list[str] = []
    for kind, label in player_order:
        artifact = artifact_map.get(kind)
        if artifact is None:
            continue
        path = Path(artifact.path)
        if not path.is_file():
            continue
        players.append(_player_html(label, _href(path, base), "main-audio" if kind == "original" else ""))

    # Segment table.
    row_limit = 800
    rows: list[str] = []
    for index, segment in enumerate(timeline.segments[:row_limit]):
        color = LABEL_COLORS.get(segment.label, LABEL_COLORS["other"])
        rows.append(
            f'<tr data-seek="{segment.start:.3f}">'
            f"<td>{index + 1}</td>"
            f"<td>{_escape(_fmt_time(segment.start))}</td>"
            f"<td>{_escape(_fmt_time(segment.stop))}</td>"
            f"<td>{segment.stop - segment.start:.2f}s</td>"
            f'<td><span class="dot" style="background:{color}"></span>'
            f"{_escape(LABEL_NAMES.get(segment.label, segment.label))}</td>"
            f"<td>{segment.confidence:.2f}</td>"
            f"<td>{_tags_html(segment.tags)}</td>"
            "</tr>"
        )
    if not rows:
        rows.append('<tr><td colspan="7"><div class="empty">没有分段数据</div></td></tr>')
    table_note = (
        f'<div class="sub">共 {len(timeline.segments)} 段，表格显示前 {row_limit} 段；点击行可跳转播放。</div>'
        if len(timeline.segments) > row_limit
        else '<div class="sub">点击任意行可跳转到对应时间播放。</div>'
    )

    # Timbre clusters.
    cluster_cards: list[str] = []
    for cluster in timbre.clusters:
        reps = [
            clip
            for clip in cluster.clips
            if clip.id in set(cluster.representative)
        ]
        rep_html: list[str] = []
        for clip in reps:
            path = Path(clip.path)
            if not path.is_file():
                continue
            rep_html.append(
                f'<div class="clip"><div class="sub">代表片段 {_escape(_fmt_time(clip.start))} – '
                f"{_escape(_fmt_time(clip.stop))}</div>"
                f'<audio controls preload="none" src="{_escape(_href(path, base))}"></audio></div>'
            )
        cluster_cards.append(
            '<div class="cluster">'
            f'<h3><span class="dot" style="background:{cluster.color}"></span>{_escape(cluster.label)}</h3>'
            f'<div class="meta">{cluster.n_clips} 个片段 · 合计 {_fmt_duration(cluster.total_duration)} · '
            f"簇 #{cluster.index}</div>"
            f'<div class="feat">{_feature_cards(cluster.features)}</div>'
            f'<div class="rep">{"".join(rep_html) or "<div class=empty>无可播放代表片段</div>"}</div>'
            "</div>"
        )
    if not cluster_cards:
        cluster_cards.append('<div class="empty">没有音色簇（可能没有检测到有效人声片段）</div>')

    scatter = _scatter_svg(timbre.clusters, timbre.points)

    # Artifacts + warnings + models.
    artifact_rows: list[str] = []
    for artifact in result.artifacts:
        artifact_rows.append(
            "<tr>"
            f"<td>{_escape(KIND_NAMES.get(artifact.kind, artifact.kind))}</td>"
            f'<td><a href="{_escape(_href(artifact.path, base))}">{_escape(Path(artifact.path).name)}</a></td>'
            f"<td>{_escape(_fmt_duration(artifact.duration))}</td>"
            f"<td>{_escape(_fmt_bytes(artifact.size))}</td>"
            "</tr>"
        )
    if not artifact_rows:
        artifact_rows.append('<tr><td colspan="4"><div class="empty">没有产物文件</div></td></tr>')

    warning_items = "".join(f'<li class="warn">{_escape(item)}</li>' for item in warnings if item)
    warning_block = f"<ul>{warning_items}</ul>" if warning_items else '<div class="sub">无警告</div>'

    diagnostics = [
        ("分离/分析", "BS-Roformer 分离 + Silero VAD + AST + 音色编码器"),
        ("音色后端", "音色编码器" if timbre.backend == "colorsplitter" else "MFCC（回退）"),
        ("音色簇代理", "后端不可用时会自动回退 MFCC 嵌入"),
        ("生成时间", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
    ]
    if meta:
        if meta.get("quality"):
            diagnostics.append(("分析质量", str(meta["quality"])))
        if meta.get("separation_model"):
            diagnostics.append(("分离模型", Path(str(meta["separation_model"])).name))
        if meta.get("device"):
            diagnostics.append(("推理设备", str(meta["device"])))
        if meta.get("elapsed_seconds") is not None:
            diagnostics.append(("分析耗时", f"{float(meta['elapsed_seconds']):.1f} 秒"))
        stages = meta.get("stages")
        if isinstance(stages, dict) and stages:
            parts = [f"{name} {float(value):.1f}s" for name, value in stages.items() if isinstance(value, (int, float))]
            if parts:
                diagnostics.append(("阶段耗时", " · ".join(parts)))
    diag_rows = "".join(
        f'<tr><td>{_escape(name)}</td><td>{_escape(value)}</td></tr>' for name, value in diagnostics
    )

    # JSON for future interactivity / debugging.
    payload = {
        "duration": duration,
        "summary": timeline.summary,
        "segments": [
            {
                "start": segment.start,
                "stop": segment.stop,
                "label": segment.label,
                "confidence": segment.confidence,
                "tags": segment.tags,
            }
            for segment in timeline.segments
        ],
        "timbre_backend": timbre.backend,
        "clusters": [
            {"index": cluster.index, "label": cluster.label, "color": cluster.color, "n_clips": cluster.n_clips}
            for cluster in timbre.clusters
        ],
    }
    payload_json = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")

    summary_chips = "".join(
        f'<span class="chip"><b>{_escape(LABEL_NAMES[label])}</b> {_fmt_duration(label_seconds[label])}</span>'
        for label in LABEL_NAMES
        if label_seconds[label] > 0
    )
    media_chip = ""
    if media_info is not None:
        media_chip = (
            f'<span class="chip">{_escape(media_info.codec or "audio")} · '
            f"{media_info.sample_rate} Hz · {media_info.channels} ch</span>"
        )

    html_text = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{_escape(title)} · AudioLab 分析报告</title>
<style>{_CSS}</style>
</head>
<body>
<div class="wrap">
<header class="top">
  <div>
    <h1>{_escape(title)}</h1>
    <div class="sub">AudioLab Studio 音频分析报告 · 项目 {_escape(result.project_id or "—")}</div>
    <div class="chips" style="margin-top:10px">
      <span class="chip">时长 <b>{_escape(_fmt_time(duration))}</b></span>
      {summary_chips}
      {media_chip}
    </div>
  </div>
  <div class="chips">{ "".join(f'<span class="chip">{_escape(name)} <b>{value}</b></span>' for name, value in [("分段", len(timeline.segments)), ("音色簇", cluster_count), ("警告", len([w for w in warnings if w]))]) }</div>
</header>

<h2>概览</h2>
<div class="cards">
  <div class="card"><div class="k">总时长</div><div class="v">{duration / 60:.2f}<small> 分钟</small></div></div>
  <div class="card"><div class="k">人声占比</div><div class="v">{vocal_pct:.1f}<small> %</small></div></div>
  <div class="card"><div class="k">音乐占比</div><div class="v">{music_pct:.1f}<small> %</small></div></div>
  <div class="card"><div class="k">分段数量</div><div class="v">{len(timeline.segments)}</div></div>
  <div class="card"><div class="k">音色簇</div><div class="v">{cluster_count}</div></div>
  <div class="card"><div class="k">警告</div><div class="v {'warn' if warnings else ''}">{len([w for w in warnings if w])}</div></div>
</div>

<h2>试听</h2>
<div class="players">
{ "".join(players) or '<div class="empty">没有可播放的音频文件</div>' }
</div>

<h2>时间轴</h2>
{_timeline_svg(duration, timeline.segments, (peaks or {}).get("peaks"))}
{table_note}

<h2>分段明细</h2>
<div class="tablewrap">
<table>
<thead><tr><th>#</th><th>开始</th><th>结束</th><th>时长</th><th>标签</th><th>置信度</th><th>标签证据</th></tr></thead>
<tbody>{ "".join(rows) }</tbody>
</table>
</div>

<h2>音色分析</h2>
<div class="grid2">
  <div class="panel">
    <div class="sub" style="margin-bottom:8px">PCA 音色散点（颜色对应簇）</div>
    {scatter}
  </div>
  <div class="panel">
    <div class="sub" style="margin-bottom:8px">后端与生成信息</div>
    <table><tbody>{diag_rows}</tbody></table>
    <div class="sub" style="margin-top:12px">警告</div>
    {warning_block}
  </div>
</div>
<div class="clusters" style="margin-top:16px">
{ "".join(cluster_cards) }
</div>

<h2>产物</h2>
<div class="panel" style="padding:0;overflow:hidden">
<table>
<thead><tr><th>类型</th><th>文件</th><th>时长</th><th>大小</th></tr></thead>
<tbody>{ "".join(artifact_rows) }</tbody>
</table>
</div>

<div class="foot">
  本报告由 AudioLab Studio 离线生成，所有资源均为相对路径，可直接移动/打包。<br/>
  生成时间 {_escape(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))} · 音色后端 {_escape(timbre.backend)}
</div>
</div>
<script>{_JS}</script>
<script id="audiolab-report-data" type="application/json">{payload_json}</script>
</body>
</html>
"""
    out.write_text(html_text, encoding="utf-8")
    return out
