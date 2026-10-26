/** Models page: engine/model table, download / delete / re-verify. */
import { useEffect, useMemo, useState, type ReactNode } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Cpu,
  Download,
  ExternalLink,
  HardDrive,
  Loader2,
  Package,
  RefreshCw,
  ShieldCheck,
  Trash2,
} from "lucide-react";
import type { ModelInfo, ModelStatus } from "../api/types";
import { describeError } from "../api/client";
import { useStudio } from "../state/StudioContext";
import { useConfirm, useToast } from "../state/ui";
import { formatBytes, normalizeProgress } from "../utils/format";
import { Chip, EmptyState, LoadingBlock, ProgressBar } from "./common/ui";

const STATUS_LABEL: Record<ModelStatus, string> = {
  missing: "未下载",
  downloading: "下载中",
  ready: "已就绪",
  error: "异常",
};

const STATUS_TONE: Record<ModelStatus, string> = {
  missing: "var(--muted)",
  downloading: "var(--accent-2)",
  ready: "var(--music)",
  error: "var(--danger)",
};

export function ModelsPanel(): ReactNode {
  const { client, models, modelsError, refreshModels, jobs, toast } = useStudio();
  const confirm = useConfirm();
  const [busyId, setBusyId] = useState<string | null>(null);
  const [verifying, setVerifying] = useState(false);
  const [lastRefresh, setLastRefresh] = useState(() => Date.now());

  useEffect(() => {
    setLastRefresh(Date.now());
  }, [models]);

  const downloadJobs = useMemo(() => {
    const map = new Map<string, { progress: number; stage: string }>();
    for (const job of jobs) {
      if (job.kind === "download" && job.status === "running") {
        const modelId = String(job.params?.model_id ?? "");
        if (modelId) map.set(modelId, { progress: normalizeProgress(job.progress), stage: job.stage });
      }
    }
    return map;
  }, [jobs]);

  const readyCount = models.filter((model) => model.status === "ready").length;
  const totalSize = models.reduce((sum, model) => sum + model.size, 0);
  const readySize = models
    .filter((model) => model.status === "ready")
    .reduce((sum, model) => sum + model.size, 0);

  const download = async (model: ModelInfo) => {
    setBusyId(model.id);
    try {
      await client.downloadModel(model.id);
      toast.info(`已开始下载 ${model.label}，可在任务队列查看进度。`);
      await refreshModels();
    } catch (err) {
      toast.error(describeError(err));
    } finally {
      setBusyId(null);
    }
  };

  const remove = async (model: ModelInfo) => {
    const ok = await confirm({
      title: `删除模型「${model.label}」？`,
      message: "删除后需要重新下载才能使用相关引擎，分析任务可能失败。",
      confirmText: "删除模型",
      danger: true,
    });
    if (!ok) return;
    setBusyId(model.id);
    try {
      await client.deleteModel(model.id);
      await refreshModels();
      toast.success("模型已删除");
    } catch (err) {
      toast.error(describeError(err));
    } finally {
      setBusyId(null);
    }
  };

  const verify = async () => {
    setVerifying(true);
    try {
      await refreshModels();
      toast.success("已重新校验模型状态");
    } finally {
      setVerifying(false);
    }
  };

  return (
    <div className="models-panel">
      <div className="page-head">
        <div>
          <h1>
            <Package size={22} /> 模型与引擎
          </h1>
          <p className="muted">
            VAD / 标签 / 分离 / 音色引擎所需的本地模型。下载通过后台任务进行，不阻塞界面。
          </p>
        </div>
        <div className="page-head-actions">
          <button type="button" className="btn btn-sm" onClick={() => void verify()} disabled={verifying}>
            <RefreshCw size={13} className={verifying ? "spin" : ""} /> 重新校验
          </button>
        </div>
      </div>

      <div className="stat-row">
        <div className="stat-card">
          <span className="k"><ShieldCheck size={14} /> 就绪</span>
          <span className="v">{readyCount} / {models.length}</span>
        </div>
        <div className="stat-card">
          <span className="k"><HardDrive size={14} /> 占用</span>
          <span className="v">{formatBytes(readySize)}</span>
        </div>
        <div className="stat-card">
          <span className="k"><Download size={14} /> 总大小</span>
          <span className="v">{formatBytes(totalSize)}</span>
        </div>
        <div className="stat-card">
          <span className="k"><Cpu size={14} /> 引擎</span>
          <span className="v">{new Set(models.map((model) => model.engine)).size}</span>
        </div>
      </div>

      {modelsError ? (
        <div className="banner banner-warn">
          <AlertTriangle size={15} /> {modelsError}
          <button type="button" className="link-btn" onClick={() => void refreshModels()}>
            重试
          </button>
        </div>
      ) : null}

      {models.length === 0 && !modelsError ? (
        <LoadingBlock label="正在读取模型状态…" rows={4} />
      ) : models.length === 0 ? (
        <EmptyState icon={<Package size={24} />} title="没有可用模型" description="后端未返回模型清单。" />
      ) : (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>模型</th>
                <th>引擎</th>
                <th>大小</th>
                <th>状态</th>
                <th>许可证</th>
                <th>来源</th>
                <th className="right">操作</th>
              </tr>
            </thead>
            <tbody>
              {models.map((model) => {
                const progress = downloadJobs.get(model.id);
                return (
                  <tr key={model.id}>
                    <td>
                      <div className="model-name">{model.label}</div>
                      <div className="muted model-file" title={model.path || model.filename}>
                        {model.filename}
                      </div>
                    </td>
                    <td>
                      <Chip>{model.engine}</Chip>
                    </td>
                    <td>{formatBytes(model.size)}</td>
                    <td>
                      <span className="model-status">
                        <span className="legend-dot" style={{ background: STATUS_TONE[model.status] }} />
                        {STATUS_LABEL[model.status]}
                      </span>
                      {progress ? (
                        <div className="model-progress">
                          <ProgressBar value={progress.progress} animated />
                          <span>{Math.round(progress.progress * 100)}%</span>
                        </div>
                      ) : null}
                      {model.error ? <div className="model-error">{model.error}</div> : null}
                    </td>
                    <td>{model.license || "—"}</td>
                    <td>
                      {model.source ? (
                        <a className="link-btn" href={model.source} target="_blank" rel="noreferrer">
                          <ExternalLink size={12} /> 链接
                        </a>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td className="right">
                      <div className="row-actions">
                        {model.status === "ready" ? (
                          <>
                            <span className="model-ok">
                              <CheckCircle2 size={13} /> 可用
                            </span>
                            <button
                              type="button"
                              className="btn btn-xs"
                              onClick={() => void remove(model)}
                              disabled={busyId === model.id}
                            >
                              <Trash2 size={12} /> 删除
                            </button>
                          </>
                        ) : (
                          <button
                            type="button"
                            className="btn btn-xs btn-primary"
                            onClick={() => void download(model)}
                            disabled={busyId === model.id || model.status === "downloading"}
                          >
                            {busyId === model.id || model.status === "downloading" ? (
                              <Loader2 size={12} className="spin" />
                            ) : (
                              <Download size={12} />
                            )}
                            {model.status === "error" ? "重新下载" : "下载"}
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <div className="models-foot">
        <span className="muted">
          <AlertTriangle size={12} /> 大模型（分离 / AST）下载耗时较长；缺失时部分阶段会自动跳过或回退。
        </span>
        <span className="muted">
          最后刷新：
          {new Date(lastRefresh).toLocaleTimeString("zh-CN", { hour12: false })}
        </span>
      </div>
    </div>
  );
}
