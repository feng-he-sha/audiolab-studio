/** Small shared primitives: spinner, skeleton, empty state, chips, modal... */
import { useEffect, useState, type ReactNode } from "react";
import { Check, Copy, Loader2, X } from "lucide-react";
import type { ModelStatus, ProjectStatus } from "../../api/types";
import { STATUS_COLOR } from "../../utils/format";

export function Spinner({ size = 16, label }: { size?: number; label?: string }): ReactNode {
  return (
    <span className="spinner-wrap" role="status">
      <Loader2 size={size} className="spin" aria-hidden="true" />
      {label ? <span>{label}</span> : null}
    </span>
  );
}

export function Skeleton({
  height = 14,
  width = "100%",
  radius,
}: {
  height?: number | string;
  width?: number | string;
  radius?: number;
}): ReactNode {
  return (
    <span
      className="skeleton"
      style={{ height, width, borderRadius: radius ?? 6 }}
      aria-hidden="true"
    />
  );
}

export function LoadingBlock({
  label = "加载中…",
  rows = 3,
}: {
  label?: string;
  rows?: number;
}): ReactNode {
  return (
    <div className="loading-block">
      <div className="loading-label">
        <Spinner size={14} /> {label}
      </div>
      {Array.from({ length: rows }, (_, index) => (
        <Skeleton key={index} height={index === 0 ? 46 : 30} />
      ))}
    </div>
  );
}

export interface EmptyStateProps {
  icon?: ReactNode;
  title: string;
  description?: ReactNode;
  action?: ReactNode;
  compact?: boolean;
}

export function EmptyState({ icon, title, description, action, compact }: EmptyStateProps): ReactNode {
  return (
    <div className={`empty-state${compact ? " compact" : ""}`}>
      {icon ? <div className="empty-icon">{icon}</div> : null}
      <div className="empty-title">{title}</div>
      {description ? <div className="empty-desc">{description}</div> : null}
      {action ? <div className="empty-action">{action}</div> : null}
    </div>
  );
}

export function StatusDot({ status }: { status: ProjectStatus | ModelStatus | string }): ReactNode {
  const color = STATUS_COLOR[status as ProjectStatus];
  const isActive = status === "analyzing" || status === "processing" || status === "downloading";
  return (
    <span
      className={`status-dot${isActive ? " pulse" : ""}`}
      style={{ background: color ?? "var(--muted)" }}
      aria-hidden="true"
    />
  );
}

export function ProgressBar({
  value,
  tone,
  animated,
}: {
  value: number;
  tone?: string;
  animated?: boolean;
}): ReactNode {
  const pct = Math.max(0, Math.min(100, value * 100));
  return (
    <div className={`progress${animated ? " progress-animated" : ""}`}>
      <div className="progress-fill" style={{ width: `${pct}%`, background: tone }} />
    </div>
  );
}

export function Chip({
  children,
  tone,
  title,
  className,
}: {
  children: ReactNode;
  tone?: string;
  title?: string;
  className?: string;
}): ReactNode {
  return (
    <span className={`chip${className ? ` ${className}` : ""}`} title={title}>
      {tone ? <span className="chip-dot" style={{ background: tone }} /> : null}
      {children}
    </span>
  );
}

export function Field({
  label,
  hint,
  error,
  children,
  inline,
}: {
  label: string;
  hint?: ReactNode;
  error?: string;
  children: ReactNode;
  inline?: boolean;
}): ReactNode {
  return (
    <label className={`field${inline ? " field-inline" : ""}`}>
      <span className="field-label">{label}</span>
      <span className="field-control">{children}</span>
      {error ? <span className="field-error">{error}</span> : null}
      {!error && hint ? <span className="field-hint">{hint}</span> : null}
    </label>
  );
}

export function SectionTitle({
  icon,
  title,
  extra,
}: {
  icon?: ReactNode;
  title: string;
  extra?: ReactNode;
}): ReactNode {
  return (
    <div className="section-title">
      <span className="section-title-main">
        {icon}
        {title}
      </span>
      {extra ? <span className="section-title-extra">{extra}</span> : null}
    </div>
  );
}

export interface ModalProps {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  width?: number | string;
}

export function Modal({ open, title, onClose, children, footer, width }: ModalProps): ReactNode {
  useEffect(() => {
    if (!open) return undefined;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.stopPropagation();
        onClose();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div
      className="modal-backdrop"
      data-modal-open="true"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="modal" role="dialog" aria-modal="true" style={{ width }}>
        <div className="modal-head">
          <h3>{title}</h3>
          <button type="button" className="icon-btn" onClick={onClose} aria-label="关闭">
            <X size={16} />
          </button>
        </div>
        <div className="modal-body">{children}</div>
        {footer ? <div className="modal-actions">{footer}</div> : null}
      </div>
    </div>
  );
}

export function CopyButton({ text, label = "复制" }: { text: string; label?: string }): ReactNode {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      className="btn btn-sm"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
        } catch {
          const area = document.createElement("textarea");
          area.value = text;
          document.body.appendChild(area);
          area.select();
          document.execCommand("copy");
          area.remove();
        }
        setCopied(true);
        window.setTimeout(() => setCopied(false), 1600);
      }}
    >
      {copied ? <Check size={13} /> : <Copy size={13} />} {copied ? "已复制" : label}
    </button>
  );
}
