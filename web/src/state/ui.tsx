/** Toasts + confirmation dialogs shared across the app. */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { AlertTriangle, CheckCircle2, Info, X, XCircle } from "lucide-react";

export type ToastKind = "info" | "success" | "warn" | "error";

interface ToastItem {
  id: number;
  kind: ToastKind;
  message: string;
}

export interface ToastApi {
  push: (kind: ToastKind, message: string) => void;
  info: (message: string) => void;
  success: (message: string) => void;
  warn: (message: string) => void;
  error: (message: string) => void;
}

export interface ConfirmOptions {
  title: string;
  message?: string;
  confirmText?: string;
  cancelText?: string;
  danger?: boolean;
}

type ConfirmFn = (options: ConfirmOptions) => Promise<boolean>;

interface PendingConfirm {
  options: ConfirmOptions;
  resolve: (value: boolean) => void;
}

const ToastContext = createContext<ToastApi | null>(null);
const ConfirmContext = createContext<ConfirmFn | null>(null);

const TOAST_ICONS = {
  info: Info,
  success: CheckCircle2,
  warn: AlertTriangle,
  error: XCircle,
};

export function UIProvider({ children }: { children: ReactNode }): ReactNode {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const [pending, setPending] = useState<PendingConfirm | null>(null);
  const sequence = useRef(0);
  const timers = useRef(new Map<number, number>());

  const dismiss = useCallback((id: number) => {
    setToasts((prev) => prev.filter((toast) => toast.id !== id));
    const timer = timers.current.get(id);
    if (timer !== undefined) {
      window.clearTimeout(timer);
      timers.current.delete(id);
    }
  }, []);

  const push = useCallback(
    (kind: ToastKind, message: string) => {
      sequence.current += 1;
      const id = sequence.current;
      setToasts((prev) => [...prev.slice(-3), { id, kind, message }]);
      const timer = window.setTimeout(() => dismiss(id), kind === "error" ? 6500 : 4200);
      timers.current.set(id, timer);
    },
    [dismiss],
  );

  useEffect(
    () => () => {
      timers.current.forEach((timer) => window.clearTimeout(timer));
      timers.current.clear();
    },
    [],
  );

  const toastApi = useMemo<ToastApi>(
    () => ({
      push,
      info: (message) => push("info", message),
      success: (message) => push("success", message),
      warn: (message) => push("warn", message),
      error: (message) => push("error", message),
    }),
    [push],
  );

  const confirm = useCallback<ConfirmFn>(
    (options) =>
      new Promise<boolean>((resolve) => {
        setPending({ options, resolve });
      }),
    [],
  );

  const settle = useCallback(
    (value: boolean) => {
      setPending((current) => {
        current?.resolve(value);
        return null;
      });
    },
    [],
  );

  useEffect(() => {
    if (!pending) return undefined;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        settle(false);
      }
      if (event.key === "Enter") {
        event.preventDefault();
        settle(true);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [pending, settle]);

  return (
    <ToastContext.Provider value={toastApi}>
      <ConfirmContext.Provider value={confirm}>
        {children}

        <div className="toast-stack" role="status" aria-live="polite">
          {toasts.map((toast) => {
            const Icon = TOAST_ICONS[toast.kind];
            return (
              <div key={toast.id} className={`toast toast-${toast.kind}`}>
                <Icon size={17} className="toast-icon" />
                <div className="toast-message">{toast.message}</div>
                <button
                  type="button"
                  className="icon-btn toast-close"
                  onClick={() => dismiss(toast.id)}
                  aria-label="关闭提示"
                >
                  <X size={14} />
                </button>
              </div>
            );
          })}
        </div>

        {pending ? (
          <div
            className="modal-backdrop"
            data-modal-open="true"
            onMouseDown={(event) => {
              if (event.target === event.currentTarget) settle(false);
            }}
          >
            <div className="modal confirm-dialog" role="dialog" aria-modal="true">
              <div className="modal-head">
                <h3>{pending.options.title}</h3>
                <button
                  type="button"
                  className="icon-btn"
                  onClick={() => settle(false)}
                  aria-label="关闭"
                >
                  <X size={16} />
                </button>
              </div>
              {pending.options.message ? (
                <p className="confirm-message">{pending.options.message}</p>
              ) : null}
              <div className="modal-actions">
                <button type="button" className="btn" onClick={() => settle(false)}>
                  {pending.options.cancelText ?? "取消"}
                </button>
                <button
                  type="button"
                  className={`btn ${pending.options.danger ? "btn-danger" : "btn-primary"}`}
                  onClick={() => settle(true)}
                  autoFocus
                >
                  {pending.options.confirmText ?? "确认"}
                </button>
              </div>
            </div>
          </div>
        ) : null}
      </ConfirmContext.Provider>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastApi {
  const context = useContext(ToastContext);
  if (!context) throw new Error("useToast 必须在 UIProvider 内使用");
  return context;
}

export function useConfirm(): ConfirmFn {
  const context = useContext(ConfirmContext);
  if (!context) throw new Error("useConfirm 必须在 UIProvider 内使用");
  return context;
}
