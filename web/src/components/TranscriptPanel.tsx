/** 转写 tab: SenseVoice 全文、分段表格、复制与 SRT/VTT/TXT 导出。 */
import { useCallback, useEffect, useMemo, useRef, useState, type MouseEvent, type ReactNode } from "react";
import {
  AlertTriangle,
  Download,
  FileText,
  Languages,
  ListMusic,
  Loader2,
  Mic,
  RefreshCw,
  Settings,
  Sparkles,
} from "lucide-react";
import { describeError } from "../api/client";
import type { TranscriptFormat, TranscriptResult } from "../api/types";
import { useStudio } from "../state/StudioContext";
import { useToast } from "../state/ui";
import {
  emotionText,
  eventText,
  formatDuration,
  formatSeconds,
  languageText,
} from "../utils/format";
import { Chip, EmptyState, LoadingBlock, SectionTitle } from "./common/ui";

const EXPORT_FORMATS: TranscriptFormat[] = ["srt", "vtt", "txt"];

async function copyText(text: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const area = document.createElement("textarea");
    area.value = text;
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    document.execCommand("copy");
    area.remove();
  }
}

export function TranscriptPanel(): ReactNode {
  const { client, demo, selectedProject, dataVersion, analyzeProject, setView, jobs, toast } = useStudio();
  const projectId = selectedProject?.id ?? "";
  const [result, setResult] = useState<TranscriptResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [activeId, setActiveId] = useState<number | null>(null);
  const rowRefs = useRef(new Map<number, HTMLTableRowElement>());

  const activeJob = useMemo(
    () =>
      jobs.find(
        (job) =>
          job.project_id === projectId &&
          (job.status === "running" || job.status === "queued"),
      ) ?? null,
    [jobs, projectId],
  );

  const load = useCallback(async () => {
    if (!projectId) return;
    setLoading(true);
    setError("");
    try {
      const value = await client.transcript(projectId);
      setResult(value);
      setActiveId(null);
    } catch (err) {
      setError(describeError(err));
    } finally {
      setLoading(false);
    }
  }, [client, projectId]);

  const refresh = useCallback(() => {
    void load();
  }, [load]);

  // Reload after a finished analysis (dataVersion is bumped by the studio).
  useEffect(() => {
    void load();
  }, [load, dataVersion]);

  const fullText = useMemo(() => {
    if (!result) return "";
    if (result.text.trim()) return result.text;
    return result.segments.map((segment) => segment.text).join("\n");
  }, [result]);

  const charCount = useMemo(() => fullText.replace(/\s/g, "").length, [fullText]);

  const copyFull = async () => {
    if (!fullText) {
      toast.warn("没有可复制的转写文本。");
      return;
    }
    try {
      await copyText(fullText);
      toast.success(`已复制全文（${charCount} 字）`);
    } catch (err) {
      toast.error(`复制失败：${describeError(err)}`);
    }
  };

  const exportHref = (format: TranscriptFormat): string => {
    if (!projectId) return "";
    return client.transcriptExportUrl(projectId, format);
  };

  const onExportClick = (
    format: TranscriptFormat,
    event: MouseEvent<HTMLAnchorElement>,
  ) => {
    if (!exportHref(format)) {
      event.preventDefault();
      toast.warn(
        demo
          ? "演示模式下没有真实转写文件；可先「复制全文」查看内容。"
          : "没有可导出的转写内容。",
      );
    }
  };

  const analyzeAgain = async () => {
    setBusy(true);
    try {
      await analyzeProject(projectId, { quality: "balanced" });
      toast.info("已提交重新分析任务，完成后转写会自动刷新。");
    } catch (err) {
      toast.error(describeError(err));
    } finally {
      setBusy(false);
    }
  };

  const selectSegment = (id: number) => {
    setActiveId(id);
    const row = rowRefs.current.get(id);
    row?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  };

  if (!projectId) {
    return <EmptyState title="未选择项目" description="在左侧项目库选择一个项目。" />;
  }

  if (loading && !result) {
    return (
      <div className="transcript-panel">
        <LoadingBlock label="正在加载转写（SenseVoice）…" rows={4} />
      </div>
    );
  }

  if (error) {
    return (
      <EmptyState
        icon={<AlertTriangle size={24} />}
        title="转写加载失败"
        description={error}
        action={
          <>
            <button type="button" className="btn btn-primary btn-sm" onClick={refresh}>
              <RefreshCw size={13} /> 重试
            </button>
            <button type="button" className="btn btn-sm" onClick={() => setView("settings")}>
              <Settings size={13} /> 检查设置
            </button>
          </>
        }
      />
    );
  }

  if (!result || (result.segments.length === 0 && !result.text.trim())) {
    return (
      <EmptyState
        icon={<Mic size={26} />}
        title="本次分析未生成转写"
        description="重新分析并保持 SenseVoice 开启，或在设置里检查 ASR 模型目录。"
        action={
          <>
            <button
              type="button"
              className="btn btn-primary btn-sm"
              onClick={() => void analyzeAgain()}
              disabled={busy || Boolean(activeJob)}
            >
              {busy || activeJob ? <Loader2 size={13} className="spin" /> : <Sparkles size={13} />}
              重新分析
            </button>
            <button type="button" className="btn btn-sm" onClick={() => setView("settings")}>
              <Settings size={13} /> 模型 / 设置
            </button>
            <button type="button" className="btn btn-sm" onClick={refresh}>
              <RefreshCw size={13} /> 刷新
            </button>
          </>
        }
      />
    );
  }

  const language = languageText(result.language) || "未知";
  const warnings = [...(result.warnings ?? [])];

  return (
    <div className="transcript-panel">
      <div className="transcript-toolbar">
        <div className="transcript-meta">
          <Chip tone="var(--accent)" title={result.model_dir || undefined}>
            <Mic size={11} /> SenseVoice
          </Chip>
          <Chip tone="var(--accent-2)">
            <Languages size={11} /> {language}
          </Chip>
          <Chip>{result.segments.length} 段</Chip>
          <Chip>{charCount} 字</Chip>
          {result.duration > 0 ? <Chip>时长 {formatDuration(result.duration)}</Chip> : null}
          {result.elapsed ? <Chip>转写 {result.elapsed.toFixed(1)}s</Chip> : null}
        </div>
        <div className="transcript-actions">
          <button type="button" className="btn btn-sm" onClick={() => void copyFull()}>
            <FileText size={13} /> 复制全文
          </button>
          {EXPORT_FORMATS.map((format) => (
            <a
              key={format}
              className="btn btn-sm"
              href={exportHref(format) || "#"}
              download={`${selectedProject?.name ?? "transcript"}.${format}`}
              onClick={(event) => onExportClick(format, event)}
            >
              <Download size={13} /> {format.toUpperCase()}
            </a>
          ))}
        </div>
      </div>

      {warnings.length > 0 ? (
        <div className="banner banner-warn">
          <AlertTriangle size={14} />
          <span>{warnings.join("；")}</span>
        </div>
      ) : null}

      <div className="card transcript-full-card">
        <SectionTitle
          icon={<FileText size={15} />}
          title="全文"
          extra={<span>{charCount} 字</span>}
        />
        <div className="transcript-text" tabIndex={0}>
          {fullText || "（无全文，见下方分段）"}
        </div>
      </div>

      <div className="card transcript-segments-card">
        <SectionTitle
          icon={<ListMusic size={15} />}
          title="转写分段"
          extra={
            <span className="transcript-segments-hint">
              点击行可高亮定位 · 共 {result.segments.length} 段
            </span>
          }
        />
        <div className="transcript-table-wrap">
          <table className="data-table transcript-table">
            <thead>
              <tr>
                <th className="transcript-col-time">时间</th>
                <th>文本</th>
                <th className="transcript-col-meta">语言</th>
                <th className="transcript-col-meta">情绪</th>
                <th className="transcript-col-meta">事件</th>
              </tr>
            </thead>
            <tbody>
              {result.segments.map((segment) => {
                const isActive = activeId === segment.id;
                return (
                  <tr
                    key={segment.id}
                    ref={(node) => {
                      if (node) rowRefs.current.set(segment.id, node);
                      else rowRefs.current.delete(segment.id);
                    }}
                    className={`transcript-row${isActive ? " active" : ""}`}
                    onClick={() => selectSegment(segment.id)}
                  >
                    <td className="transcript-col-time">
                      <span className="transcript-time">
                        {formatSeconds(segment.start)}
                      </span>
                      <span className="muted"> → {formatSeconds(segment.stop)}</span>
                    </td>
                    <td className="transcript-text-cell">{segment.text}</td>
                    <td className="transcript-col-meta">
                      {languageText(segment.language) || <span className="muted">—</span>}
                    </td>
                    <td className="transcript-col-meta">
                      {emotionText(segment.emotion) ? (
                        <span className="transcript-tag">{emotionText(segment.emotion)}</span>
                      ) : (
                        <span className="muted">—</span>
                      )}
                    </td>
                    <td className="transcript-col-meta">
                      {eventText(segment.event) ? (
                        <span className="transcript-tag">{eventText(segment.event)}</span>
                      ) : (
                        <span className="muted">—</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {loading ? (
        <div className="transcript-loading" aria-hidden="true">
          <Loader2 size={12} className="spin" /> 正在刷新转写…
        </div>
      ) : null}
    </div>
  );
}
