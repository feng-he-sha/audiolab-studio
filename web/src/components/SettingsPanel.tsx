/** Settings page: workspace/models paths, device, mirror, theme, language. */
import { useEffect, useMemo, useState, type ReactNode } from "react";
import {
  AlertTriangle,
  Check,
  Cpu,
  FolderOpen,
  Globe,
  Languages,
  Loader2,
  Monitor,
  RotateCcw,
  Save,
  Settings as SettingsIcon,
  Sparkles,
} from "lucide-react";
import type { DeviceTarget, Settings, ThemeName } from "../api/types";
import { describeError } from "../api/client";
import { useStudio } from "../state/StudioContext";
import { useToast } from "../state/ui";
import { LoadingBlock, SectionTitle } from "./common/ui";

const DEVICES: { value: DeviceTarget; label: string; hint: string }[] = [
  { value: "auto", label: "自动", hint: "有 CUDA 时使用 GPU，否则 CPU" },
  { value: "cuda", label: "CUDA", hint: "强制 GPU 推理" },
  { value: "cpu", label: "CPU", hint: "强制 CPU，兼容性最好" },
];

const THEMES: { value: ThemeName; label: string }[] = [
  { value: "dark", label: "深色（默认）" },
  { value: "light", label: "浅色" },
];

const LANGUAGES = [
  { value: "zh-CN", label: "简体中文" },
  { value: "en-US", label: "English" },
];

export function SettingsPanel(): ReactNode {
  const { settings, settingsError, saveSettings, toast, demo } = useStudio();
  const [draft, setDraft] = useState<Settings | null>(settings);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setDraft(settings);
  }, [settings]);

  const dirty = useMemo(
    () => JSON.stringify(draft) !== JSON.stringify(settings),
    [draft, settings],
  );

  const patch = (values: Partial<Settings>) => {
    setDraft((current) => (current ? { ...current, ...values } : current));
  };

  const save = async () => {
    if (!draft) return;
    setSaving(true);
    try {
      await saveSettings(draft);
      toast.success("设置已保存");
    } catch (err) {
      toast.error(describeError(err));
    } finally {
      setSaving(false);
    }
  };

  if (!draft) {
    return (
      <div className="settings-panel">
        <div className="page-head">
          <h1>
            <SettingsIcon size={22} /> 设置
          </h1>
        </div>
        {settingsError ? (
          <div className="banner banner-warn">
            <AlertTriangle size={15} /> {settingsError}
          </div>
        ) : (
          <LoadingBlock label="正在读取设置…" rows={5} />
        )}
      </div>
    );
  }

  return (
    <div className="settings-panel">
      <div className="page-head">
        <div>
          <h1>
            <SettingsIcon size={22} /> 设置
          </h1>
          <p className="muted">路径与应用配置保存到后端，立即生效；部分引擎参数在下一个任务中生效。</p>
        </div>
        <div className="page-head-actions">
          <button type="button" className="btn btn-sm" onClick={() => setDraft(settings)} disabled={!dirty || saving}>
            <RotateCcw size={13} /> 撤销更改
          </button>
          <button type="button" className="btn btn-primary btn-sm" onClick={() => void save()} disabled={!dirty || saving}>
            {saving ? <Loader2 size={14} className="spin" /> : <Save size={14} />} 保存设置
          </button>
        </div>
      </div>

      {demo ? (
        <div className="banner banner-info">
          <Sparkles size={14} /> 演示模式：设置修改仅保留在当前页面，不会写入磁盘。
        </div>
      ) : null}
      {settingsError ? (
        <div className="banner banner-warn">
          <AlertTriangle size={15} /> {settingsError}
        </div>
      ) : null}

      <div className="settings-layout">
        <div className="card">
          <SectionTitle icon={<FolderOpen size={15} />} title="存储路径" />
          <label className="field">
            <span className="field-label">工作区目录</span>
            <input
              value={draft.workspace_dir}
              onChange={(event) => patch({ workspace_dir: event.target.value })}
              placeholder="E:\\AudioLab\\workspace"
              spellCheck={false}
            />
            <span className="field-hint">项目分析结果、stems、报告和输出文件存于此目录。</span>
          </label>
          <label className="field">
            <span className="field-label">模型目录</span>
            <input
              value={draft.models_dir}
              onChange={(event) => patch({ models_dir: event.target.value })}
              placeholder="E:\\AudioLab\\models"
              spellCheck={false}
            />
            <span className="field-hint">VAD / AST / 分离模型缓存目录（建议 SSD 且空间充足）。</span>
          </label>
        </div>

        <div className="card">
          <SectionTitle icon={<Cpu size={15} />} title="计算与并发" />
          <label className="field">
            <span className="field-label">推理设备</span>
            <select
              value={draft.device}
              onChange={(event) => patch({ device: event.target.value as DeviceTarget })}
            >
              {DEVICES.map((device) => (
                <option key={device.value} value={device.value}>
                  {device.label}
                </option>
              ))}
            </select>
            <span className="field-hint">
              {DEVICES.find((device) => device.value === draft.device)?.hint}
            </span>
          </label>
          <label className="field">
            <span className="field-label">最大 GPU 并发任务</span>
            <input
              type="number"
              min={1}
              max={4}
              value={draft.max_gpu_jobs}
              onChange={(event) => patch({ max_gpu_jobs: Number(event.target.value) })}
            />
            <span className="field-hint">显存不足时保持 1，避免任务排队失败。</span>
          </label>
          <label className="field">
            <span className="field-label">预览质量</span>
            <input
              type="number"
              min={8}
              max={192}
              step={8}
              value={draft.preview_quality}
              onChange={(event) => patch({ preview_quality: Number(event.target.value) })}
            />
            <span className="field-hint">预览 m4a 码率（kbps），越高加载越慢。</span>
          </label>
        </div>

        <div className="card">
          <SectionTitle icon={<Globe size={15} />} title="网络与镜像" />
          <label className="field">
            <span className="field-label">HuggingFace 镜像</span>
            <input
              value={draft.hf_endpoint}
              onChange={(event) => patch({ hf_endpoint: event.target.value })}
              placeholder="https://hf-mirror.com"
              spellCheck={false}
            />
            <span className="field-hint">留空使用官方源；国内网络建议使用 hf-mirror。</span>
          </label>
          <label className="checkbox">
            <input
              type="checkbox"
              checked={draft.auto_open_report}
              onChange={(event) => patch({ auto_open_report: event.target.checked })}
            />
            <span>分析完成后自动打开报告</span>
          </label>
        </div>

        <div className="card">
          <SectionTitle icon={<Monitor size={15} />} title="界面" />
          <label className="field">
            <span className="field-label">主题</span>
            <select
              value={draft.theme}
              onChange={(event) => patch({ theme: event.target.value as ThemeName })}
            >
              {THEMES.map((theme) => (
                <option key={theme.value} value={theme.value}>
                  {theme.label}
                </option>
              ))}
            </select>
            <span className="field-hint">保存后立即应用；当前选择会记入 localStorage。</span>
          </label>
          <label className="field">
            <span className="field-label">
              <Languages size={13} /> 界面语言
            </span>
            <select value={draft.language} onChange={(event) => patch({ language: event.target.value })}>
              {LANGUAGES.map((language) => (
                <option key={language.value} value={language.value}>
                  {language.label}
                </option>
              ))}
            </select>
            <span className="field-hint">当前版本以中文为主，English 逐步补充。</span>
          </label>
        </div>
      </div>

      <div className="settings-footer">
        <span className={dirty ? "settings-dirty" : "settings-clean"}>
          {dirty ? <AlertTriangle size={13} /> : <Check size={13} />}
          {dirty ? "有未保存的更改" : "所有更改已保存"}
        </span>
        <span className="muted">配置文件由后端管理，重启 AudioLab 后仍生效。</span>
      </div>
    </div>
  );
}
