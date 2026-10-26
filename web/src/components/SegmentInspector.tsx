/** Inspector for the segment selected on the timeline. */
import type { ReactNode } from "react";
import {
  GitMerge,
  Play,
  RotateCcw,
  Scissors,
  Tag,
  X,
} from "lucide-react";
import type { Label, Segment, TranscriptSegment } from "../api/types";
import {
  LABEL_TEXT,
  emotionText,
  eventText,
  formatSeconds,
  languageText,
} from "../utils/format";
import { Chip } from "./common/ui";

export interface SegmentInspectorProps {
  segment: Segment;
  index: number;
  playhead: number;
  busy: boolean;
  /** Closest transcript segment overlapping the current timeline segment. */
  transcript?: TranscriptSegment | null;
  onChangeLabel: (label: Label | null) => void;
  onMergeNext: () => void;
  onSplitAtPlayhead: () => void;
  onPlaySegment: () => void;
  onClose: () => void;
}

const LABEL_OPTIONS: Label[] = ["vocals", "music", "vocals+music", "other"];

export function SegmentInspector({
  segment,
  index,
  playhead,
  busy,
  transcript,
  onChangeLabel,
  onMergeNext,
  onSplitAtPlayhead,
  onPlaySegment,
  onClose,
}: SegmentInspectorProps): ReactNode {
  const duration = segment.stop - segment.start;
  const effective = segment.label;
  const inside = playhead > segment.start + 0.05 && playhead < segment.stop - 0.05;
  const tags = Object.entries(segment.tags)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 6);

  return (
    <div className="segment-inspector">
      <div className="segment-inspector-head">
        <span className="segment-inspector-title">
          <Tag size={14} /> 分段检查器
          <span className="muted">#{index + 1}</span>
        </span>
        <button type="button" className="icon-btn" onClick={onClose} aria-label="关闭分段检查器">
          <X size={14} />
        </button>
      </div>

      <div className="segment-inspector-body">
        <div className="segment-times">
          <span className="segment-time">{formatSeconds(segment.start)}</span>
          <span className="muted">→</span>
          <span className="segment-time">{formatSeconds(segment.stop)}</span>
          <span className="segment-duration">{duration.toFixed(2)}s</span>
        </div>

        <div className="segment-fields">
          <label className="segment-field">
            <span className="k">标签</span>
            <select
              value={segment.user_label ?? ""}
              onChange={(event) => {
                const value = event.target.value;
                onChangeLabel(value ? (value as Label) : null);
              }}
              disabled={busy}
            >
              <option value="">自动（{LABEL_TEXT[effective]}）</option>
              {LABEL_OPTIONS.map((label) => (
                <option key={label} value={label}>
                  {LABEL_TEXT[label]}
                </option>
              ))}
            </select>
          </label>
          <div className="segment-field">
            <span className="k">置信度</span>
            <span className={`segment-confidence${segment.confidence < 0.6 ? " low" : ""}`}>
              {Math.round(segment.confidence * 100)}%
            </span>
          </div>
          {segment.user_label ? (
            <Chip tone="var(--accent)">手动标注</Chip>
          ) : (
            <Chip>自动标注</Chip>
          )}
        </div>

        <div className="segment-tags">
          <span className="k">AST 标签</span>
          {tags.length === 0 ? (
            <span className="muted">无标签（可能跳过了 AST 推理）</span>
          ) : (
            <div className="segment-tag-list">
              {tags.map(([name, value]) => (
                <div className="segment-tag" key={name}>
                  <span className="segment-tag-name">{name}</span>
                  <span className="segment-tag-bar">
                    <span style={{ width: `${Math.max(2, value * 100)}%` }} />
                  </span>
                  <span className="segment-tag-value">{Math.round(value * 100)}%</span>
                </div>
              ))}
            </div>
          )}
        </div>

        {transcript && transcript.text ? (
          <div className="segment-transcript">
            <span className="k">转写文本</span>
            <div className="segment-transcript-text">{transcript.text}</div>
            <div className="segment-transcript-meta">
              {languageText(transcript.language) ? (
                <Chip>{languageText(transcript.language)}</Chip>
              ) : null}
              {emotionText(transcript.emotion) ? (
                <Chip tone="var(--warn)">情绪 {emotionText(transcript.emotion)}</Chip>
              ) : null}
              {eventText(transcript.event) ? (
                <Chip tone="var(--accent-2)">事件 {eventText(transcript.event)}</Chip>
              ) : null}
              <span className="muted segment-transcript-time">
                {formatSeconds(transcript.start)} → {formatSeconds(transcript.stop)}
              </span>
            </div>
          </div>
        ) : null}
      </div>

      <div className="segment-actions">
        <button type="button" className="btn btn-sm" onClick={onPlaySegment} disabled={busy}>
          <Play size={13} /> 播放片段
        </button>
        <button type="button" className="btn btn-sm" onClick={onMergeNext} disabled={busy}>
          <GitMerge size={13} /> 合并下一段
        </button>
        <button
          type="button"
          className="btn btn-sm"
          onClick={onSplitAtPlayhead}
          disabled={busy || !inside}
          title={inside ? `在 ${formatSeconds(playhead)} 切分` : "播放头需位于该分段内部"}
        >
          <Scissors size={13} /> 在播放头切分
        </button>
        <button
          type="button"
          className="btn btn-sm"
          onClick={() => onChangeLabel(null)}
          disabled={busy || !segment.user_label}
        >
          <RotateCcw size={13} /> 恢复自动
        </button>
      </div>
    </div>
  );
}
