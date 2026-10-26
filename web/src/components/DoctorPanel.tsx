/** Doctor page: environment checks with actionable hints. */
import { useCallback, useEffect, useState, type ReactNode } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Copy,
  Cpu,
  Loader2,
  RefreshCw,
  Stethoscope,
  Terminal,
  XCircle,
} from "lucide-react";
import { describeError } from "../api/client";
import type { DoctorResult } from "../api/types";
import { useStudio } from "../state/StudioContext";
import { useToast } from "../state/ui";
import { CopyButton, EmptyState, LoadingBlock, SectionTitle } from "./common/ui";

export function DoctorPanel(): ReactNode {
  const { client, health, toast } = useStudio();
  const [doctor, setDoctor] = useState<DoctorResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const value = await client.doctor();
      setDoctor(value);
      setError("");
    } catch (err) {
      setError(describeError(err));
    } finally {
      setLoading(false);
    }
  }, [client]);

  useEffect(() => {
    void load();
  }, [load]);

  const failed = doctor?.checks.filter((check) => !check.ok) ?? [];

  const diagnostics = JSON.stringify(
    {
      generated_at: new Date().toISOString(),
      health,
      doctor,
      user_agent: navigator.userAgent,
      url: window.location.href,
    },
    null,
    2,
  );

  return (
    <div className="doctor-panel">
      <div className="page-head">
        <div>
          <h1>
            <Stethoscope size={22} /> 诊断
          </h1>
          <p className="muted">检查运行环境、引擎依赖与模型状态；复制诊断信息可随问题反馈。</p>
        </div>
        <div className="page-head-actions">
          <button
            type="button"
            className="btn btn-sm"
            onClick={async () => {
              await load();
              toast.info("已重新检查");
            }}
            disabled={loading}
          >
            <RefreshCw size={13} className={loading ? "spin" : ""} /> 重新检查
          </button>
          <button
            type="button"
            className="btn btn-sm"
            onClick={async () => {
              try {
                await navigator.clipboard.writeText(diagnostics);
                toast.success("诊断信息已复制到剪贴板");
              } catch {
                const area = document.createElement("textarea");
                area.value = diagnostics;
                document.body.appendChild(area);
                area.select();
                document.execCommand("copy");
                area.remove();
                toast.success("诊断信息已复制");
              }
            }}
          >
            <Copy size={13} /> 复制诊断信息
          </button>
        </div>
      </div>

      {loading && !doctor ? (
        <LoadingBlock label="正在检查环境…" rows={5} />
      ) : error ? (
        <EmptyState
          icon={<AlertTriangle size={24} />}
          title="诊断接口不可用"
          description={error}
          action={
            <button type="button" className="btn btn-sm" onClick={() => void load()}>
              <RefreshCw size={13} /> 重试
            </button>
          }
        />
      ) : doctor ? (
        <>
          <div className={`doctor-banner ${doctor.ok ? "ok" : "warn"}`}>
            {doctor.ok ? <CheckCircle2 size={20} /> : <AlertTriangle size={20} />}
            <div>
              <div className="doctor-banner-title">
                {doctor.ok ? "环境检查全部通过" : `${failed.length} 项需要处理`}
              </div>
              <div className="muted">
                {doctor.ok
                  ? "可以开始导入媒体并运行分析任务。"
                  : failed.map((check) => check.name).join("、")}
              </div>
            </div>
            <span className="doctor-count">{doctor.checks.length} 项检查</span>
          </div>

          <div className="card check-card">
            <SectionTitle icon={<Terminal size={15} />} title="检查明细" extra={<CopyButton text={diagnostics} label="复制 JSON" />} />
            <ul className="check-list">
              {doctor.checks.map((check) => (
                <li key={check.name} className={`check-item ${check.ok ? "ok" : "fail"}`}>
                  <span className="check-icon">
                    {check.ok ? <CheckCircle2 size={16} /> : <XCircle size={16} />}
                  </span>
                  <div className="check-main">
                    <div className="check-name">{check.name}</div>
                    <div className="check-detail">{check.detail || "—"}</div>
                    {!check.ok && check.hint ? <div className="check-hint">建议：{check.hint}</div> : null}
                  </div>
                </li>
              ))}
            </ul>
          </div>

          <div className="doctor-meta">
            <span>
              <Cpu size={12} /> 设备：{health?.device ?? "未知"}
              {health ? ` · CUDA ${health.cuda ? "可用" : "不可用"}` : ""}
            </span>
            <span>
              <CheckCircle2 size={12} /> 版本：{health?.version ?? "—"}
            </span>
            <span>
              <AlertTriangle size={12} /> 后端：{health?.ok ? "在线" : "离线"}
            </span>
          </div>
        </>
      ) : null}
    </div>
  );
}
