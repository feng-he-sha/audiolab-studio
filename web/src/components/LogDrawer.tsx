/** Bottom log drawer for the active/most recent job. */
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Copy, ScrollText, X } from "lucide-react";
import { useStudio } from "../state/StudioContext";
import { useToast } from "../state/ui";
import { JOB_KIND_TEXT, JOB_STATUS_TEXT } from "../utils/format";

export function LogDrawer(): ReactNode {
  const { client, jobs, logOpen, setLogOpen, toast } = useStudio();
  const [lines, setLines] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);

  const target = useMemo(
    () =>
      jobs.find((job) => job.status === "running") ??
      jobs.find((job) => job.status === "queued") ??
      [...jobs].sort((a, b) => (a.created_at < b.created_at ? 1 : -1))[0] ??
      null,
    [jobs],
  );

  useEffect(() => {
    if (!logOpen) return undefined;
    let cancelled = false;
    const load = async () => {
      if (!target) {
        setLines(["当前没有任务日志。"]);
        return;
      }
      setLoading(true);
      try {
        const response = await client.jobLog(target.id);
        if (!cancelled) setLines(response.lines.slice(-300));
      } catch {
        if (!cancelled) {
          setLines(["[界面] 无法读取日志：后端未启动或日志接口不可用。"]);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    void load();
    const timer = window.setInterval(load, 2000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [client, logOpen, target?.id]);

  if (!logOpen) return null;

  return (
    <div className="log-drawer">
      <div className="log-drawer-head">
        <span className="log-drawer-title">
          <ScrollText size={14} /> 任务日志
          {target ? (
            <span className="muted">
              {JOB_KIND_TEXT[target.kind] ?? target.kind} · {JOB_STATUS_TEXT[target.status]} · {target.id}
            </span>
          ) : null}
        </span>
        <div className="log-drawer-actions">
          <button
            type="button"
            className="btn btn-xs"
            onClick={async () => {
              try {
                await navigator.clipboard.writeText(lines.join("\n"));
                toast.success("日志已复制");
              } catch {
                toast.error("复制失败：浏览器不允许访问剪贴板");
              }
            }}
          >
            <Copy size={11} /> 复制
          </button>
          <button type="button" className="icon-btn" onClick={() => setLogOpen(false)} aria-label="关闭日志抽屉">
            <X size={14} />
          </button>
        </div>
      </div>
      <pre className="log-drawer-body">
        {lines.length === 0 ? (loading ? "加载日志…" : "暂无日志") : lines.join("\n")}
      </pre>
    </div>
  );
}
