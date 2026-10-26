/** Global studio state: projects, jobs, models, settings, websocket events. */
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
import { ApiError, describeError, getClient, isDemoMode } from "../api/client";
import type {
  AnalyzeOptions,
  ApiClient,
  Health,
  ImportResult,
  Job,
  ModelInfo,
  ProcessOptions,
  Project,
  Settings,
  ThemeName,
} from "../api/types";
import { friendlyError } from "../utils/format";
import { useInterval, useLocalStorage } from "../utils/hooks";
import { useToast, type ToastApi } from "./ui";

export type TabKey = "overview" | "timeline" | "separation" | "timbre" | "process" | "report";
export type WorkspaceView = "studio" | "models" | "settings" | "doctor";

export interface StudioContextValue {
  client: ApiClient;
  demo: boolean;
  toast: ToastApi;

  health: Health | null;
  healthError: string;
  wsConnected: boolean;

  projects: Project[];
  projectsLoading: boolean;
  projectsError: string;
  refreshProjects: (silent?: boolean) => Promise<void>;
  importPaths: (paths: string[]) => Promise<ImportResult>;
  uploadFiles: (files: File[]) => Promise<ImportResult>;
  removeProject: (id: string, deleteOutputs: boolean) => Promise<void>;
  analyzeProject: (id: string, options?: AnalyzeOptions) => Promise<string>;
  processProject: (id: string, options: ProcessOptions) => Promise<string>;

  selectedProjectId: string | null;
  selectedProject: Project | null;
  selectProject: (id: string | null) => void;
  reloadSelected: () => Promise<void>;

  dataVersion: number;
  bumpDataVersion: () => void;

  jobs: Job[];
  jobsError: string;
  refreshJobs: () => Promise<void>;

  models: ModelInfo[];
  modelsError: string;
  refreshModels: () => Promise<void>;

  settings: Settings | null;
  settingsError: string;
  saveSettings: (patch: Partial<Settings>) => Promise<Settings>;

  selectedTab: TabKey;
  setSelectedTab: (tab: TabKey) => void;
  view: WorkspaceView;
  setView: (view: WorkspaceView) => void;

  theme: ThemeName;
  setTheme: (theme: ThemeName) => void;

  logOpen: boolean;
  setLogOpen: (open: boolean) => void;
}

const StudioContext = createContext<StudioContextValue | null>(null);

function upsertProject(list: Project[], project: Project): Project[] {
  const index = list.findIndex((p) => p.id === project.id);
  if (index === -1) return [project, ...list];
  const next = list.slice();
  next[index] = project;
  return next;
}

function upsertJob(list: Job[], job: Job): Job[] {
  const index = list.findIndex((j) => j.id === job.id);
  if (index === -1) return [job, ...list].slice(0, 120);
  const next = list.slice();
  next[index] = job;
  return next;
}

function upsertModel(list: ModelInfo[], model: ModelInfo): ModelInfo[] {
  const index = list.findIndex((m) => m.id === model.id);
  if (index === -1) return [...list, model];
  const next = list.slice();
  next[index] = model;
  return next;
}

export function StudioProvider({ children }: { children: ReactNode }): ReactNode {
  const clientRef = useRef<ApiClient | null>(null);
  if (!clientRef.current) clientRef.current = getClient();
  const client = clientRef.current;
  const demo = isDemoMode();
  const toast = useToast();

  const [health, setHealth] = useState<Health | null>(null);
  const [healthError, setHealthError] = useState("");
  const [wsConnected, setWsConnected] = useState(false);

  const [projects, setProjects] = useState<Project[]>([]);
  const [projectsLoading, setProjectsLoading] = useState(true);
  const [projectsError, setProjectsError] = useState("");

  const [jobs, setJobs] = useState<Job[]>([]);
  const [jobsError, setJobsError] = useState("");

  const [models, setModels] = useState<ModelInfo[]>([]);
  const [modelsError, setModelsError] = useState("");

  const [settings, setSettings] = useState<Settings | null>(null);
  const [settingsError, setSettingsError] = useState("");

  const [selectedProjectId, setSelectedProjectId] = useLocalStorage<string | null>(
    "audiolab.selectedProject",
    null,
  );
  const [selectedTab, setSelectedTab] = useLocalStorage<TabKey>("audiolab.tab", "overview");
  const [view, setView] = useState<WorkspaceView>("studio");
  const [theme, setTheme] = useLocalStorage<ThemeName>("audiolab.theme", "dark");
  const [logOpen, setLogOpen] = useLocalStorage<boolean>("audiolab.logOpen", false);
  const [dataVersion, setDataVersion] = useState(0);

  const selectedProject = useMemo(
    () => projects.find((p) => p.id === selectedProjectId) ?? null,
    [projects, selectedProjectId],
  );

  const selectedIdRef = useRef(selectedProjectId);
  useEffect(() => {
    selectedIdRef.current = selectedProjectId;
  }, [selectedProjectId]);

  const jobStatusRef = useRef(new Map<string, string>());
  const refreshTimer = useRef<number | null>(null);
  const initialJobsLoaded = useRef(false);

  /* ------------------------------------------------------------ */
  /* Data loading                                                 */
  /* ------------------------------------------------------------ */

  const refreshProjects = useCallback(
    async (silent = false) => {
      if (!silent) setProjectsLoading(true);
      try {
        const response = await client.listProjects({ page_size: 200 });
        setProjects(response.items);
        setProjectsError("");
      } catch (err) {
        setProjectsError(friendlyError(describeError(err)));
      } finally {
        setProjectsLoading(false);
      }
    },
    [client],
  );

  const refreshJobs = useCallback(async () => {
    try {
      const response = await client.listJobs(false);
      setJobsError("");
      const known = jobStatusRef.current;
      const fresh = !initialJobsLoaded.current;
      initialJobsLoaded.current = true;
      const transitions: Job[] = [];
      for (const job of response.items) {
        const previous = known.get(job.id);
        if (!fresh && previous && previous !== job.status) transitions.push(job);
        known.set(job.id, job.status);
      }
      setJobs(response.items);
      for (const job of transitions) {
        if (job.status === "done" && job.kind !== "download") {
          toast.success(`任务完成：${job.message || job.stage}`);
        }
        if (job.status === "failed") {
          toast.error(`任务失败：${job.error || job.message || "未知错误"}`);
        }
      }
    } catch (err) {
      setJobsError(friendlyError(describeError(err)));
    }
  }, [client, toast]);

  const refreshModels = useCallback(async () => {
    try {
      const response = await client.listModels();
      setModels(response.models);
      setModelsError("");
    } catch (err) {
      setModelsError(friendlyError(describeError(err)));
    }
  }, [client]);

  const refreshHealth = useCallback(async () => {
    try {
      const value = await client.health();
      setHealth(value);
      setHealthError("");
    } catch (err) {
      setHealthError(friendlyError(describeError(err)));
    }
  }, [client]);

  const loadSettings = useCallback(async () => {
    try {
      const value = await client.getSettings();
      setSettings(value);
      setSettingsError("");
    } catch (err) {
      setSettingsError(friendlyError(describeError(err)));
    }
  }, [client]);

  useEffect(() => {
    void refreshHealth();
    void refreshProjects();
    void refreshJobs();
    void refreshModels();
    void loadSettings();
  }, [refreshHealth, refreshProjects, refreshJobs, refreshModels, loadSettings]);

  useInterval(() => {
    void refreshHealth();
  }, 15000);

  useInterval(() => {
    void refreshJobs();
  }, 3500);

  /* ------------------------------------------------------------ */
  /* WebSocket events                                             */
  /* ------------------------------------------------------------ */

  const scheduleRefresh = useCallback(
    (projectId?: string) => {
      if (refreshTimer.current !== null) window.clearTimeout(refreshTimer.current);
      refreshTimer.current = window.setTimeout(() => {
        void refreshProjects(true);
        if (!projectId || projectId === selectedIdRef.current) {
          setDataVersion((v) => v + 1);
          if (selectedIdRef.current) {
            client
              .getProject(selectedIdRef.current)
              .then((project) => setProjects((prev) => upsertProject(prev, project)))
              .catch(() => undefined);
          }
        }
      }, 500);
    },
    [client, refreshProjects],
  );

  useEffect(
    () => () => {
      if (refreshTimer.current !== null) window.clearTimeout(refreshTimer.current);
    },
    [],
  );

  useEffect(() => {
    const unsubscribe = client.subscribe((event) => {
      setWsConnected(true);
      if (event.type === "job") {
        const job = event.job;
        const previous = jobStatusRef.current.get(job.id);
        jobStatusRef.current.set(job.id, job.status);
        setJobs((prev) => upsertJob(prev, job));
        if (job.status === "done" && previous !== "done") {
          if (job.kind !== "download") toast.success(`任务完成：${job.message || job.stage}`);
          if (job.kind === "download") void refreshModels();
          scheduleRefresh(job.project_id);
        }
        if (job.status === "failed" && previous !== "failed") {
          toast.error(`任务失败：${job.error || job.message || "未知错误"}`);
          scheduleRefresh(job.project_id);
        }
        return;
      }
      if (event.type === "project") {
        setProjects((prev) => upsertProject(prev, event.project));
        if (event.project.id === selectedIdRef.current) setDataVersion((v) => v + 1);
        return;
      }
      if (event.type === "model") {
        setModels((prev) => upsertModel(prev, event.model));
      }
    });
    return unsubscribe;
  }, [client, refreshModels, scheduleRefresh, toast]);

  /* ------------------------------------------------------------ */
  /* Theme                                                        */
  /* ------------------------------------------------------------ */

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    document.documentElement.style.colorScheme = theme === "light" ? "light" : "dark";
  }, [theme]);

  /* URL deep-links: ?project=<id>&tab=timeline|timbre|process|report&view=models
     Works in both real and demo mode (used for automation/screenshots). */
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const tab = params.get("tab");
    if (tab && ["overview", "timeline", "separation", "timbre", "process", "report"].includes(tab)) {
      setSelectedTab(tab as TabKey);
    }
    const targetView = params.get("view");
    if (targetView && ["studio", "models", "settings", "doctor"].includes(targetView)) {
      setView(targetView as WorkspaceView);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const requested = new URLSearchParams(window.location.search).get("project");
    if (requested) {
      if (requested !== selectedProjectId) setSelectedProjectId(requested);
      return;
    }
    if (demo && !selectedProjectId && projects.length > 0) {
      setSelectedProjectId(projects[0].id);
    }
  }, [demo, projects, selectedProjectId, setSelectedProjectId]);

  /* ------------------------------------------------------------ */
  /* Actions                                                      */
  /* ------------------------------------------------------------ */

  const selectProject = useCallback(
    (id: string | null) => {
      setSelectedProjectId(id);
      setView("studio");
      setDataVersion((v) => v + 1);
    },
    [setSelectedProjectId],
  );

  const reloadSelected = useCallback(async () => {
    if (!selectedIdRef.current) return;
    try {
      const project = await client.getProject(selectedIdRef.current);
      setProjects((prev) => upsertProject(prev, project));
      setDataVersion((v) => v + 1);
    } catch (err) {
      toast.error(friendlyError(describeError(err)));
    }
  }, [client, toast]);

  const importPaths = useCallback(
    async (paths: string[]): Promise<ImportResult> => {
      const result = await client.importPaths(paths);
      await refreshProjects(true);
      if (result.projects.length > 0) {
        selectProject(result.projects[0].id);
      }
      return result;
    },
    [client, refreshProjects, selectProject],
  );

  const uploadFiles = useCallback(
    async (files: File[]): Promise<ImportResult> => {
      const result = await client.uploadFiles(files);
      await refreshProjects(true);
      if (result.projects.length > 0) {
        selectProject(result.projects[0].id);
      }
      return result;
    },
    [client, refreshProjects, selectProject],
  );

  const removeProject = useCallback(
    async (id: string, deleteOutputs: boolean) => {
      await client.deleteProject(id, deleteOutputs);
      setProjects((prev) => prev.filter((p) => p.id !== id));
      if (selectedIdRef.current === id) {
        setSelectedProjectId(null);
      }
      toast.success("项目已删除");
    },
    [client, setSelectedProjectId, toast],
  );

  const analyzeProject = useCallback(
    async (id: string, options?: AnalyzeOptions): Promise<string> => {
      const response = await client.analyze(id, options);
      toast.info("已提交分析任务，可在右侧队列查看进度。");
      void refreshJobs();
      void refreshProjects(true);
      setDataVersion((v) => v + 1);
      return response.job_id;
    },
    [client, refreshJobs, refreshProjects, toast],
  );

  const processProject = useCallback(
    async (id: string, options: ProcessOptions): Promise<string> => {
      const response = await client.process(id, options);
      toast.info("已提交处理任务，可在右侧队列查看进度。");
      void refreshJobs();
      return response.job_id;
    },
    [client, refreshJobs, toast],
  );

  const saveSettings = useCallback(
    async (patch: Partial<Settings>): Promise<Settings> => {
      const value = await client.patchSettings(patch);
      setSettings(value);
      if (patch.theme) setTheme(value.theme);
      return value;
    },
    [client, setTheme],
  );

  const value = useMemo<StudioContextValue>(
    () => ({
      client,
      demo,
      toast,
      health,
      healthError,
      wsConnected,
      projects,
      projectsLoading,
      projectsError,
      refreshProjects,
      importPaths,
      uploadFiles,
      removeProject,
      analyzeProject,
      processProject,
      selectedProjectId,
      selectedProject,
      selectProject,
      reloadSelected,
      dataVersion,
      bumpDataVersion: () => setDataVersion((v) => v + 1),
      jobs,
      jobsError,
      refreshJobs,
      models,
      modelsError,
      refreshModels,
      settings,
      settingsError,
      saveSettings,
      selectedTab,
      setSelectedTab,
      view,
      setView,
      theme,
      setTheme,
      logOpen,
      setLogOpen,
    }),
    [
      client,
      demo,
      toast,
      health,
      healthError,
      wsConnected,
      projects,
      projectsLoading,
      projectsError,
      refreshProjects,
      importPaths,
      uploadFiles,
      removeProject,
      analyzeProject,
      processProject,
      selectedProjectId,
      selectedProject,
      selectProject,
      reloadSelected,
      dataVersion,
      jobs,
      jobsError,
      refreshJobs,
      models,
      modelsError,
      refreshModels,
      settings,
      settingsError,
      saveSettings,
      selectedTab,
      setSelectedTab,
      view,
      theme,
      setTheme,
      logOpen,
      setLogOpen,
    ],
  );

  return <StudioContext.Provider value={value}>{children}</StudioContext.Provider>;
}

export function useStudio(): StudioContextValue {
  const context = useContext(StudioContext);
  if (!context) throw new Error("useStudio 必须在 StudioProvider 内使用");
  return context;
}

export { ApiError };
