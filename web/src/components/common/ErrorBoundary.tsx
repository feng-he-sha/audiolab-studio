import { Component, type ErrorInfo, type ReactNode } from "react";
import { AlertTriangle, RotateCcw } from "lucide-react";

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
  info: string;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null, info: "" };

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    this.setState({ info: info.componentStack ?? "" });
    console.error("[AudioLab] UI crash:", error, info.componentStack);
  }

  render(): ReactNode {
    const { error, info } = this.state;
    if (!error) return this.props.children;
    return (
      <div className="crash-screen">
        <div className="crash-card">
          <div className="crash-icon">
            <AlertTriangle size={28} />
          </div>
          <h2>界面出现异常</h2>
          <p className="muted">
            当前面板渲染失败，音频项目与后端任务不会受影响。可重试渲染，或刷新整个工作台。
          </p>
          <pre className="crash-detail">
            {error.message}
            {info ? `\n${info.split("\n").slice(0, 8).join("\n")}` : ""}
          </pre>
          <div className="modal-actions">
            <button type="button" className="btn" onClick={() => window.location.reload()}>
              <RotateCcw size={14} /> 刷新工作台
            </button>
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => this.setState({ error: null, info: "" })}
            >
              重试渲染
            </button>
          </div>
        </div>
      </div>
    );
  }
}
