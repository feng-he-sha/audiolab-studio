/** Left project library: search, status filter, multi-select, imports. */
import { useEffect, useMemo, useRef, useState, type ChangeEvent, type ReactNode } from "react";
import {
  AlertCircle,
  CheckSquare,
  FileAudio,
  FolderSearch,
  Loader2,
  Music4,
  Play,
  RefreshCw,
  Search,
  Sparkles,
  Square,
  Trash2,
  Upload,
  Wand2,
  Download,
} from "lucide-react";
import type { Label, Preset, Project } from "../api/types";
import { describeError } from "../api/client";
import { useStudio } from "../state/StudioContext";
import { useConfirm, useToast } from "../state/ui";
import {
  LABEL_TEXT,
  STATUS_TEXT,
  formatDuration,
  relativeTime,
} from "../utils/format";
import { useLocalStorage } from "../utils/hooks";
import {
  Chip,
  EmptyState,
  Modal,
  Skeleton,
  StatusDot,
} from "./common/ui";

const AUDIO_EXTS =
  ".mp3,.wav,.flac,.m4a,.aac,.ogg,.opus,.wma,.aiff,.aif,.mp4,.mov,.mkv,.webm,.avi";

const STATUS_FILTERS: { value: string; label: string }[] = [
  { value: "all", label: "全部状态" },
  { value: "imported", label: "已导入" },
  { value: "analyzing", label: "分析中" },
  { value: "analyzed", label: "已分析" },
  { value: "processing", label: "处理中" },
  { value: "ready", label: "已就绪" },
  { value: "error", label: "出错" },
];

const PRESETS: { id: Preset; label: string }[] = [
  { id: "douyin", label: "抖音" },
  { id: "podcast", label: "播客" },
  { id: "movie", label: "影视" },
  { id: "music", label: "音乐" },
  { id: "clean", label: "纯净" },
];

function getBridge(): PywebviewApi | null {
  return window.pywebview?.api ?? null;
}

function normalizePicked(result: unknown): string[] {
  if (Array.isArray(result)) {
    return result.filter((item): item is string => typeof item === "string");
  }
  if (result && typeof result === "object") {
    const paths = (result as { paths?: unknown }).paths;
    if (Array.isArray(paths)) {
      return paths.filter((item): item is string => typeof item === "string");
    }
    const single = (result as { path?: unknown }).path;
    if (typeof single === "string") return [single];
  }
  return [];
}

function useBridge(): PywebviewApi | null {
  const [bridge, setBridge] = useState<PywebviewApi | null>(() => getBridge());
  useEffect(() => {
    if (bridge) return undefined;
    // pywebview injects window.pywebview after DOMContentLoaded; poll briefly.
    let attempts = 0;
    const timer = window.setInterval(() => {
      attempts += 1;
      const next = getBridge();
      if (next) {
        setBridge(next);
        window.clearInterval(timer);
      } else if (attempts > 40) {
        window.clearInterval(timer);
      }
    }, 250);
    const onReady = () => {
      const next = getBridge();
      if (next) setBridge(next);
    };
    window.addEventListener("pywebviewready", onReady);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("pywebviewready", onReady);
    };
  }, [bridge]);
  return bridge;
}

function labelDurations(project: Project): { label: Label; seconds: number }[] {
  const labels: Label[] = ["vocals", "music", "vocals+music", "other"];
  const result: { label: Label; seconds: number }[] = [];
  for (const label of labels) {
    const value = Number(project.summary?.[label]);
    if (Number.isFinite(value) && value > 0) result.push({ label, seconds: value });
  }
  return result;
}

export function Library(): ReactNode {
  const {
    client,
    demo,
    projects,
    projectsLoading,
    projectsError,
    refreshProjects,
    selectedProjectId,
    selectProject,
    importPaths,
    uploadFiles,
    processProject,
    toast,
    jobs,
  } = useStudio();
  const confirm = useConfirm();
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("all");
  const [selection, setSelection] = useState<Set<string>>(new Set());
  const [pathModal, setPathModal] = useState(false);
  const [pathText, setPathText] = useState("");
  const [busy, setBusy] = useState(false);
  const [batchOpen, setBatchOpen] = useState(false);
  const [batchPreset, setBatchPreset] = useState<Preset>("douyin");
  const [collapsed, setCollapsed] = useLocalStorage<boolean>("audiolab.libCollapsed", false);
  const fileInput = useRef<HTMLInputElement | null>(null);
  const bridge = useBridge();

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return projects.filter((project) => {
      if (status !== "all" && project.status !== status) return false;
      if (!needle) return true;
      return (
        project.name.toLowerCase().includes(needle) ||
        project.source_path.toLowerCase().includes(needle) ||
        project.tags.some((tag) => tag.toLowerCase().includes(needle)) ||
        (project.media?.filename ?? "").toLowerCase().includes(needle)
      );
    });
  }, [projects, query, status]);

  const activeJobIds = useMemo(() => {
    const map = new Map<string, string>();
    for (const job of jobs) {
      if (job.status === "running" || job.status === "queued") {
        map.set(job.project_id, job.status === "running" ? "运行中" : "排队中");
      }
    }
    return map;
  }, [jobs]);

  const selectedIds = useMemo(() => Array.from(selection), [selection]);
  const allVisibleSelected = filtered.length > 0 && filtered.every((p) => selection.has(p.id));

  const toggleSelect = (id: string) => {
    setSelection((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleSelectAll = () => {
    setSelection((prev) => {
      if (allVisibleSelected) {
        const next = new Set(prev);
        for (const project of filtered) next.delete(project.id);
        return next;
      }
      const next = new Set(prev);
      for (const project of filtered) next.add(project.id);
      return next;
    });
  };

  async function runImport(paths: string[]): Promise<void> {
    if (paths.length === 0) return;
    setBusy(true);
    try {
      const result = await importPaths(paths);
      if (result.errors.length > 0) {
        toast.warn(`部分文件未导入：${result.errors[0]}`);
      }
      if (result.projects.length > 0) {
        toast.success(`已导入 ${result.projects.length} 个项目`);
      } else if (result.errors.length === 0) {
        toast.info("没有发现可导入的音频/视频文件。");
      }
    } catch (err) {
      toast.error(describeError(err));
    } finally {
      setBusy(false);
    }
  }

  async function pickNative(): Promise<boolean> {
    if (!bridge?.pick_files) return false;
    try {
      setBusy(true);
      const picked = normalizePicked(await bridge.pick_files());
      if (picked.length === 0) return true;
      await runImport(picked);
    } catch (err) {
      toast.error(`原生文件对话框失败：${describeError(err)}`);
    } finally {
      setBusy(false);
    }
    return true;
  }

  async function onImportClick(): Promise<void> {
    const handled = await pickNative();
    if (!handled) fileInput.current?.click();
  }

  async function onFileInput(event: ChangeEvent<HTMLInputElement>): Promise<void> {
    const files = Array.from(event.target.files ?? []);
    event.target.value = "";
    if (files.length === 0) return;
    setBusy(true);
    try {
      const result = await uploadFiles(files);
      if (result.errors.length > 0) toast.warn(`部分文件上传失败：${result.errors[0]}`);
      if (result.projects.length > 0) toast.success(`已上传 ${result.projects.length} 个项目`);
    } catch (err) {
      toast.error(describeError(err));
    } finally {
      setBusy(false);
    }
  }

  async function onPathSubmit(): Promise<void> {
    const paths = pathText
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter(Boolean);
    if (paths.length === 0) {
      toast.warn("请输入至少一个本地绝对路径。");
      return;
    }
    await runImport(paths);
    setPathModal(false);
    setPathText("");
  }

  async function onBatchAnalyze(): Promise<void> {
    if (selectedIds.length === 0) return;
    setBusy(true);
    const results = await Promise.allSettled(
      selectedIds.map((id) => client.analyze(id, { quality: "balanced" })),
    );
    const failed = results.filter((r) => r.status === "rejected").length;
    setBusy(false);
    await refreshProjects(true);
    if (failed > 0) toast.warn(`${selectedIds.length - failed} 个任务已提交，${failed} 个失败`);
    else toast.success(`已提交 ${selectedIds.length} 个分析任务`);
  }

  async function onBatchProcess(): Promise<void> {
    if (selectedIds.length === 0) return;
    setBusy(true);
    const results = await Promise.allSettled(
      selectedIds.map((id) =>
        processProject(id, { preset: batchPreset, mux_video: true, output_format: "m4a" }),
      ),
    );
    const failed = results.filter((r) => r.status === "rejected").length;
    setBusy(false);
    setBatchOpen(false);
    if (failed > 0) toast.warn(`${selectedIds.length - failed} 个处理任务已提交，${failed} 个失败`);
    else toast.success(`已提交 ${selectedIds.length} 个处理任务（${batchPreset}）`);
  }

  async function onBatchDelete(): Promise<void> {
    if (selectedIds.length === 0) return;
    const ok = await confirm({
      title: `删除 ${selectedIds.length} 个项目？`,
      message: "将同时删除工作区中的分析结果与输出文件，此操作不可撤销。",
      confirmText: "删除项目",
      danger: true,
    });
    if (!ok) return;
    setBusy(true);
    try {
      for (const id of selectedIds) await client.deleteProject(id, true);
      setSelection(new Set());
      await refreshProjects(true);
      toast.success("已删除所选项目");
    } catch (err) {
      toast.error(describeError(err));
    } finally {
      setBusy(false);
    }
  }

  function onBatchExport(): void {
    if (demo) {
      toast.warn("演示模式没有真实输出文件，导出不可用。启动后端后可导出 ZIP。");
      return;
    }
    let count = 0;
    for (const id of selectedIds) {
      const url = client.exportUrl(id, "zip");
      if (!url) continue;
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = "";
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      count += 1;
    }
    if (count > 0) toast.info(`已开始导出 ${count} 个项目（ZIP）`);
  }

  // Topbar buttons dispatch window events; the library owns import/batch flows.
  useEffect(() => {
    const onImport = () => void onImportClick();
    const onBatch = () => {
      if (selection.size === 0) {
        toast.info("请先在项目库勾选要批量处理的项目。");
        return;
      }
      setBatchOpen(true);
    };
    window.addEventListener("audiolab:import", onImport);
    window.addEventListener("audiolab:batch", onBatch);
    return () => {
      window.removeEventListener("audiolab:import", onImport);
      window.removeEventListener("audiolab:batch", onBatch);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bridge, busy, selection, toast]);

  if (collapsed) {
    return (
      <aside className="library library-collapsed">
        <button
          type="button"
          className="icon-btn"
          title="展开项目库"
          onClick={() => setCollapsed(false)}
        >
          <Music4 size={18} />
        </button>
        <button
          type="button"
          className="icon-btn"
          title="导入"
          onClick={() => void onImportClick()}
        >
          <Upload size={17} />
        </button>
        <span className="library-collapsed-count">{projects.length}</span>
      </aside>
    );
  }

  return (
    <aside className="library">
      <div className="library-head">
        <div className="library-title-row">
          <h2>项目库</h2>
          <span className="library-count">{projects.length}</span>
          <button
            type="button"
            className="icon-btn"
            title="收起项目库"
            onClick={() => setCollapsed(true)}
          >
            <Square size={14} />
          </button>
        </div>
        <div className="library-actions">
          <button
            type="button"
            className="btn btn-primary btn-sm"
            onClick={() => void onImportClick()}
            disabled={busy}
            title={bridge?.pick_files ? "使用系统文件对话框导入" : "选择文件上传"}
          >
            {busy ? <Loader2 size={14} className="spin" /> : <Upload size={14} />} 导入
          </button>
          <button
            type="button"
            className="btn btn-sm"
            onClick={() => setPathModal(true)}
            title="手动输入本地绝对路径"
          >
            <FolderSearch size={14} /> 路径
          </button>
        </div>
        <div className="library-search">
          <Search size={14} className="search-icon" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="搜索项目 / 文件名 / 标签"
            aria-label="搜索项目"
          />
          {query ? (
            <button
              type="button"
              className="icon-btn"
              onClick={() => setQuery("")}
              aria-label="清空搜索"
            >
              ×
            </button>
          ) : null}
        </div>
        <div className="library-filter-row">
          <select
            value={status}
            onChange={(event) => setStatus(event.target.value)}
            aria-label="按状态筛选"
          >
            {STATUS_FILTERS.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </select>
          <button type="button" className="icon-btn" title="刷新项目库" onClick={() => void refreshProjects()}>
            <RefreshCw size={14} />
          </button>
        </div>
        {selectedIds.length > 0 ? (
          <div className="batch-bar">
            <span className="batch-count">
              <CheckSquare size={13} /> 已选 {selectedIds.length}
            </span>
            <div className="batch-actions">
              <button type="button" className="icon-btn" title="批量分析" onClick={() => void onBatchAnalyze()} disabled={busy}>
                <Wand2 size={14} />
              </button>
              <button type="button" className="icon-btn" title="批量处理" onClick={() => setBatchOpen(true)} disabled={busy}>
                <Sparkles size={14} />
              </button>
              <button type="button" className="icon-btn" title="导出 ZIP" onClick={onBatchExport} disabled={busy}>
                <Download size={14} />
              </button>
              <button type="button" className="icon-btn danger" title="删除" onClick={() => void onBatchDelete()} disabled={busy}>
                <Trash2 size={14} />
              </button>
              <button type="button" className="icon-btn" title="取消选择" onClick={() => setSelection(new Set())}>
                ×
              </button>
            </div>
          </div>
        ) : null}
      </div>

      <div className="library-list">
        {projectsLoading && projects.length === 0 ? (
          <div className="library-skeletons">
            {Array.from({ length: 6 }, (_, index) => (
              <div className="lib-row-skeleton" key={index}>
                <Skeleton height={16} width={16} radius={4} />
                <div className="lib-row-skeleton-main">
                  <Skeleton height={13} width={`${60 + ((index * 13) % 30)}%`} />
                  <Skeleton height={10} width="45%" />
                </div>
              </div>
            ))}
          </div>
        ) : projectsError ? (
          <EmptyState
            icon={<AlertCircle size={22} />}
            title="无法加载项目库"
            description={projectsError}
            action={
              <button type="button" className="btn btn-sm" onClick={() => void refreshProjects()}>
                <RefreshCw size={14} /> 重试
              </button>
            }
          />
        ) : filtered.length === 0 ? (
          <EmptyState
            icon={<FileAudio size={24} />}
            title={projects.length === 0 ? "项目库为空" : "没有匹配的项目"}
            description={
              projects.length === 0
                ? "导入本地音频/视频开始：支持 mp3、wav、flac、m4a、mp4、mov 等格式。"
                : "试试调整搜索关键词或状态筛选。"
            }
            action={
              projects.length === 0 ? (
                <button type="button" className="btn btn-primary btn-sm" onClick={() => void onImportClick()}>
                  <Upload size={14} /> 导入文件
                </button>
              ) : undefined
            }
          />
        ) : (
          <>
            <div className="library-select-all">
              <label className="checkbox">
                <input type="checkbox" checked={allVisibleSelected} onChange={toggleSelectAll} />
                <span>全选（{filtered.length}）</span>
              </label>
            </div>
            {filtered.map((project) => {
              const active = project.id === selectedProjectId;
              const labels = labelDurations(project);
              const jobLabel = activeJobIds.get(project.id);
              return (
                <div
                  key={project.id}
                  className={`lib-row${active ? " active" : ""}`}
                  onClick={() => selectProject(project.id)}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") selectProject(project.id);
                  }}
                >
                  <span className="lib-checkbox" onClick={(event) => event.stopPropagation()}>
                    <input
                      type="checkbox"
                      checked={selection.has(project.id)}
                      onChange={() => toggleSelect(project.id)}
                      aria-label={`选择 ${project.name}`}
                    />
                  </span>
                  <div className="lib-main">
                    <div className="lib-title">
                      <StatusDot status={project.status} />
                      <span className="lib-name" title={project.source_path}>
                        {project.name}
                      </span>
                      {jobLabel ? <Chip className="chip-active">{jobLabel}</Chip> : null}
                      {project.status === "error" ? (
                        <Chip tone="var(--danger)">{STATUS_TEXT.error}</Chip>
                      ) : null}
                    </div>
                    <div className="lib-meta">
                      <span>{project.media ? formatDuration(project.media.duration) : "未知时长"}</span>
                      {project.media?.has_video ? (
                        <span>
                          {project.media.video_width ?? "?"}×{project.media.video_height ?? "?"}
                        </span>
                      ) : null}
                      <span>{relativeTime(project.updated_at)}</span>
                    </div>
                    {labels.length > 0 ? (
                      <div className="lib-labels">
                        {labels.map((item) => (
                          <span key={item.label} className={`label-pill label-${item.label}`}>
                            {LABEL_TEXT[item.label]} {item.seconds.toFixed(1)}s
                          </span>
                        ))}
                      </div>
                    ) : project.tags.length > 0 ? (
                      <div className="lib-labels">
                        {project.tags.slice(0, 3).map((tag) => (
                          <span key={tag} className="tag-pill">
                            {tag}
                          </span>
                        ))}
                      </div>
                    ) : null}
                    {project.error ? <div className="lib-error">{project.error}</div> : null}
                  </div>
                  {active ? <Play size={13} className="lib-active-icon" /> : null}
                </div>
              );
            })}
          </>
        )}
      </div>

      <div className="library-foot">
        <span>{filtered.length} / {projects.length} 个项目</span>
        {busy ? <span className="muted"><Loader2 size={12} className="spin" /> 处理中</span> : null}
      </div>

      <input
        ref={fileInput}
        type="file"
        multiple
        accept={AUDIO_EXTS}
        className="hidden-input"
        onChange={(event) => void onFileInput(event)}
      />

      <Modal
        open={pathModal}
        title="手动导入本地文件"
        onClose={() => setPathModal(false)}
        footer={
          <>
            {bridge?.pick_folder ? (
              <button
                type="button"
                className="btn"
                onClick={async () => {
                  try {
                    const picked = normalizePicked(await bridge.pick_folder?.());
                    if (picked.length > 0) {
                      setPathText((prev) => [prev.trim(), ...picked].filter(Boolean).join("\n"));
                    }
                  } catch (err) {
                    toast.error(`选择文件夹失败：${describeError(err)}`);
                  }
                }}
              >
                <FolderSearch size={14} /> 浏览文件夹
              </button>
            ) : null}
            <button type="button" className="btn" onClick={() => setPathModal(false)}>
              取消
            </button>
            <button type="button" className="btn btn-primary" onClick={() => void onPathSubmit()} disabled={busy}>
              {busy ? <Loader2 size={14} className="spin" /> : <Upload size={14} />} 导入
            </button>
          </>
        }
      >
        <p className="muted modal-hint">
          每行一个绝对路径，支持文件或文件夹（后端会递归扫描）。桌面版可直接使用系统文件对话框。
        </p>
        <textarea
          className="textarea path-textarea"
          value={pathText}
          onChange={(event) => setPathText(event.target.value)}
          rows={6}
          placeholder={"E:\\media\\测试视频_抖音口播_29s.mp4\nE:\\media\\播客合集\\"}
          spellCheck={false}
        />
      </Modal>

      <Modal
        open={batchOpen}
        title={`批量处理 ${selectedIds.length} 个项目`}
        onClose={() => setBatchOpen(false)}
        footer={
          <>
            <button type="button" className="btn" onClick={() => setBatchOpen(false)}>
              取消
            </button>
            <button type="button" className="btn btn-primary" onClick={() => void onBatchProcess()} disabled={busy}>
              {busy ? <Loader2 size={14} className="spin" /> : <Sparkles size={14} />} 开始处理
            </button>
          </>
        }
      >
        <p className="muted modal-hint">为每个项目提交一个处理任务，默认回贴视频轨道并输出 m4a。</p>
        <div className="preset-pills">
          {PRESETS.map((preset) => (
            <button
              key={preset.id}
              type="button"
              className={`preset-pill${batchPreset === preset.id ? " active" : ""}`}
              onClick={() => setBatchPreset(preset.id)}
            >
              {preset.label}
            </button>
          ))}
        </div>
      </Modal>
    </aside>
  );
}
