/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_DEMO?: string;
  readonly VITE_API_BASE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

interface PywebviewApi {
  pick_files?: () => Promise<unknown>;
  pick_folder?: () => Promise<unknown>;
  [key: string]: unknown;
}

interface Window {
  pywebview?: {
    api?: PywebviewApi;
  };
}
