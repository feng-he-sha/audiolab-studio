/** 报告 tab: iframe report preview, open-in-browser and export buttons. */
import { useMemo, useState, type ReactNode } from "react";
import {
  Download,
  ExternalLink,
  FileArchive,
  FileJson,
  FileSpreadsheet,
  Loader2,
  RefreshCw,
} from "lucide-react";
import { useStudio } from "../state/StudioContext";
import { useToast } from "../state/ui";
import { EmptyState } from "./common/ui";

export function ReportPanel(): ReactNode {
  const { client, demo, selectedProject, toast } = useStudio();
  const [loading, setLoading] = useState(true);
  const [reloadKey, setReloadKey] = useState(0);
  const projectId = selectedProject?.id ?? "";
  const reportUrl = useMemo(() => (projectId ? client.reportUrl(projectId) : ""), [client, projectId]);
  const reportHtml = useMemo(() => (projectId ? client.reportHtml(projectId) : null), [client, projectId]);

  const openInBrowser = () => {
    if (!reportUrl) return;
    if (demo) {
      toast.warn("演示模式没有真实报告服务，请在 iframe 中查看示例报告。");
      return;
    }
    window.open(reportUrl, "_blank", "noopener,noreferrer");
  };

  const exportFile = async (format: "zip" | "json" | "csv") => {
    if (demo) {
      toast.warn("演示模式没有真实输出文件，导出不可用。");
      return;
    }
    if (!projectId) return;
    const url = client.exportUrl(projectId, format);
    if (!url) {
      toast.warn("当前后端未提供导出接口。");
      return;
    }
    if (format === "zip") {
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `${selectedProject?.name ?? "audiolab"}.zip`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      toast.info("已开始导出 ZIP");
      return;
    }
    try {
      const response = await fetch(url);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const blob = await response.blob();
      const objectUrl = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = objectUrl;
      anchor.download = `${selectedProject?.name ?? "audiolab"}.${format}`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(objectUrl);
      toast.info(`已导出 ${format.toUpperCase()}`);
    } catch (err) {
      toast.error(
        `导出 ${format.toUpperCase()} 失败：${err instanceof Error ? err.message : String(err)}（后端可能只实现了 ?format=zip）`,
      );
    }
  };

  if (!projectId) return <EmptyState title="未选择项目" />;

  return (
    <div className="report-panel">
      <div className="report-toolbar">
        <div className="report-toolbar-left">
          <span className="report-title">分析报告</span>
          <span className="muted">由后端生成 HTML，内嵌波形、分段与响度统计</span>
        </div>
        <div className="report-toolbar-right">
          <button
            type="button"
            className="btn btn-sm"
            onClick={() => {
              setLoading(true);
              setReloadKey((key) => key + 1);
            }}
            disabled={demo}
            title={demo ? "演示模式使用内置报告" : "重新加载报告"}
          >
            <RefreshCw size={13} /> 刷新
          </button>
          <button type="button" className="btn btn-sm" onClick={openInBrowser}>
            <ExternalLink size={13} /> 浏览器打开
          </button>
          <button type="button" className="btn btn-sm" onClick={() => void exportFile("zip")}>
            <FileArchive size={13} /> ZIP
          </button>
          <button type="button" className="btn btn-sm" onClick={() => void exportFile("json")}>
            <FileJson size={13} /> JSON
          </button>
          <button type="button" className="btn btn-sm" onClick={() => void exportFile("csv")}>
            <FileSpreadsheet size={13} /> CSV
          </button>
        </div>
      </div>

      <div className="report-frame-wrap">
        {loading ? (
          <div className="report-loading">
            <Loader2 size={18} className="spin" /> 正在加载报告…
          </div>
        ) : null}
        {reportHtml ? (
          <iframe
            key={`${projectId}-${reloadKey}`}
            className="report-frame"
            title="分析报告"
            srcDoc={reportHtml}
            onLoad={() => setLoading(false)}
            sandbox="allow-same-origin allow-popups"
          />
        ) : (
          <iframe
            key={`${projectId}-${reloadKey}`}
            className="report-frame"
            title="分析报告"
            src={reportUrl}
            onLoad={() => setLoading(false)}
          />
        )}
      </div>

      <div className="report-foot">
        <span>
          <Download size={12} /> 导出 ZIP 包含 stems、时间轴 JSON、音色片段与报告。
        </span>
        {demo ? <span className="muted">演示模式：报告为内置示例 HTML。</span> : null}
      </div>
    </div>
  );
}
