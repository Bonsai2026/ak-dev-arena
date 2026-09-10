/* Typed client for the Arena backend (FastAPI sidecar). */

// LAN auth: when the backend runs with ARENA_TOKEN set, every request must
// carry it. Token sources (first wins): ?token=… in the URL (start.bat can
// open the UI with it), then localStorage. The fetch shim below adds the
// header to ALL api calls, including streaming.
export const ARENA_TOKEN: string = (() => {
  try {
    const fromUrl = new URLSearchParams(window.location.search).get("token");
    if (fromUrl) localStorage.setItem("arena.token", fromUrl);
    return localStorage.getItem("arena.token") || "";
  } catch {
    return "";
  }
})();

const _origFetch = window.fetch.bind(window);
window.fetch = (input: RequestInfo | URL, init?: RequestInit) => {
  if (ARENA_TOKEN) {
    const headers = new Headers(init?.headers);
    if (!headers.has("Authorization")) {
      headers.set("Authorization", `Bearer ${ARENA_TOKEN}`);
    }
    init = { ...init, headers };
  }
  return _origFetch(input, init);
};

export interface ChatMessage {
  role: "system" | "user" | "assistant";
  content: string;
}

export interface ModelEntry {
  id: string;
  label: string;
  provider: string;
  provider_name?: string;
  best_for?: string;
  needs_key: boolean;
  configured: boolean;
  cost?: { input: number; output: number };
  free?: boolean;
  tool_call?: boolean;
  reasoning?: boolean;
  context?: number;
}

export interface ProviderEntry {
  provider: string;
  name?: string;
  env_var: string | null;
  needs_key: boolean;
  configured: boolean;
  models?: number;
  free_models?: number;
}

export interface ModelQuery {
  provider?: string;
  search?: string;
  free_only?: boolean;
  limit?: number;
}

export interface FileEntry {
  name: string;
  path: string;
  type: "file" | "dir";
  size: number;
}

export interface SearchHit {
  path: string;
  line: number;
  text: string;
}

export interface GitStatus {
  is_repo: boolean;
  branch: string;
  clean: boolean;
  changed: string[];
  untracked: string[];
}

export interface AgentStep {
  thought: string;
  tool: string;
  args: Record<string, unknown>;
  result: string;
}

export interface AgentResult {
  status: string;
  steps: AgentStep[];
  summary: string;
}

export interface Job {
  id: string;
  task: string;
  model: string;
  status: string;
  created_at: number;
  finished_at: number | null;
  summary: string;
  error: string;
  steps?: AgentStep[];
}

export interface Template {
  id: string;
  description: string;
  files: string[];
}

export interface BuildInfo {
  name: string;
  path: string;
  files: number;
}

export interface Finding {
  severity: string;
  file: string;
  line: number;
  message: string;
}

export interface UsageSummary {
  totals: { calls: number; prompt: number; completion: number; total: number; cost: number };
  by_model: { model: string; calls: number; prompt: number; completion: number; total: number; cost: number }[];
}

export interface CustomProvider {
  id: string;
  name: string;
  base_url: string;
  model: string;
}

export async function getCustomProviders(): Promise<CustomProvider[]> {
  const res = await asJson(await fetch("/api/providers/custom"));
  return res.providers ?? [];
}

export async function addCustomProvider(p: {
  id: string;
  name: string;
  base_url: string;
  model: string;
}): Promise<CustomProvider> {
  const res = await post("/api/providers/custom", p);
  return res.provider;
}

export async function deleteCustomProvider(id: string): Promise<boolean> {
  const res = await asJson(await fetch(`/api/providers/custom/${id}`, { method: "DELETE" }));
  return res.deleted ?? false;
}

async function asJson(res: Response): Promise<any> {
  if (!res.ok) {
    const detail = await res
      .json()
      .then((b) => (b as any)?.detail ?? res.statusText)
      .catch(() => res.statusText);
    throw new Error(typeof detail === "string" ? detail : res.statusText);
  }
  return res.json();
}

async function post(path: string, body: unknown): Promise<any> {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return asJson(res);
}

/* ------------------------------- catalog/keys ------------------------------ */

export async function getModels(q: ModelQuery = {}): Promise<{
  models: ModelEntry[];
  defaults: Record<string, string>;
  total: number;
  catalog_total: number;
}> {
  const params = new URLSearchParams();
  if (q.provider) params.set("provider", q.provider);
  if (q.search) params.set("search", q.search);
  if (q.free_only) params.set("free_only", "true");
  params.set("limit", String(q.limit ?? 500));
  return asJson(await fetch(`/api/models?${params.toString()}`));
}

export async function refreshCatalog(): Promise<{ providers: number; models: number; fetched_at: string }> {
  const res = await fetch("/api/catalog/refresh", { method: "POST" });
  return asJson(res);
}

export async function getProviders(): Promise<{ providers: ProviderEntry[] }> {
  return asJson(await fetch("/api/providers"));
}

export async function saveKey(provider: string, key: string): Promise<void> {
  await post("/api/keys", { provider, key });
}

export async function deleteKey(provider: string): Promise<void> {
  await asJson(await fetch(`/api/keys/${provider}`, { method: "DELETE" }));
}

/* ---------------------------------- chat ----------------------------------- */

/** POST /api/chat/stream and invoke onToken per SSE delta. Pass a signal to cancel. */
export async function streamChat(
  model: string,
  messages: ChatMessage[],
  onToken: (token: string) => void,
  signal?: AbortSignal
): Promise<void> {
  const res = await fetch("/api/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model, messages }),
    signal,
  });
  if (!res.ok || !res.body) {
    const detail = await res
      .json()
      .then((b) => (b as any)?.detail ?? res.statusText)
      .catch(() => res.statusText);
    throw new Error(typeof detail === "string" ? detail : res.statusText);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed.startsWith("data:")) continue;
      const payload = trimmed.slice(5).trim();
      if (payload === "[DONE]") return;
      try {
        const obj = JSON.parse(payload);
        if (obj.error) throw new Error(obj.error);
        if (obj.token) onToken(obj.token);
      } catch (e) {
        if (e instanceof SyntaxError) continue;
        throw e;
      }
    }
  }
}

/* ------------------------------- code (files) ------------------------------ */

export async function listFiles(path = ""): Promise<FileEntry[]> {
  const res = await fetch(`/api/files?path=${encodeURIComponent(path)}`);
  return ((await asJson(res)).entries ?? []) as FileEntry[];
}

export async function readFile(path: string): Promise<{ path: string; content: string; size: number }> {
  return asJson(await fetch(`/api/files/read?path=${encodeURIComponent(path)}`));
}

export async function writeFile(path: string, content: string): Promise<void> {
  await post("/api/files/write", { path, content });
}

export async function searchFiles(q: string): Promise<SearchHit[]> {
  const res = await fetch(`/api/files/search?q=${encodeURIComponent(q)}`);
  return ((await asJson(res)).hits ?? []) as SearchHit[];
}

export async function previewEdit(path: string, old_text: string, new_text: string): Promise<string> {
  const res = await post("/api/files/edit/preview", { path, old_text, new_text });
  return (res.diff ?? "") as string;
}

/* ----------------------------------- git ----------------------------------- */

export async function gitStatus(): Promise<GitStatus> {
  return asJson(await fetch("/api/git/status"));
}

export async function gitCheckpoint(message: string): Promise<{ hash: string | null; message: string }> {
  return post("/api/git/checkpoint", { message });
}

export async function gitUndo(): Promise<{ undone: boolean; reverted: string }> {
  return post("/api/git/undo", {});
}

/* ---------------------------------- agent ---------------------------------- */

export async function runAgent(
  task: string,
  model: string,
  max_steps: number,
  profile = "coder"
): Promise<AgentResult> {
  return post("/api/agent/run", { task, model, max_steps, profile });
}

/* ----- long-running agent tasks (Phase B): progress, cancel, verify ----- */

export interface AgentTaskStep {
  thought: string;
  tool: string;
  args?: Record<string, unknown>;
  result: string;
}

export interface AgentTask {
  id: string;
  task: string;
  model: string;
  profile: string;
  status: "queued" | "running" | "complete" | "done" | "failed" | "cancelled" | "timeout";
  created: number;
  started: number | null;
  finished: number | null;
  steps: AgentTaskStep[];
  current: { tool: string; thought: string; result: string } | null;
  summary: string;
  error: string;
  plan: string[];
  files: string[];
  criteria: { criteria: string; status: string }[];
  verification: {
    build: "pass" | "fail" | "unverified" | null;
    tests: "pass" | "fail" | "unverified" | null;
    servers: string[];
    has_evidence: boolean;
  } | null;
}

export async function createAgentTask(
  task: string,
  model: string,
  max_steps: number,
  profile = "coder"
): Promise<AgentTask> {
  return post("/api/agent/tasks", { task, model, max_steps, profile });
}

export async function getAgentTask(id: string): Promise<AgentTask> {
  return asJson(await fetch(`/api/agent/tasks/${id}`));
}

export interface FileChange {
  path: string;
  status: "added" | "modified" | "deleted";
  additions: number;
  deletions: number;
  diff: string;
}

export async function getAgentChanges(id: string): Promise<FileChange[]> {
  const res = await fetch(`/api/agent/tasks/${id}/changes`);
  return ((await asJson(res)).changes ?? []) as FileChange[];
}

export async function revertAgentChange(id: string, path: string): Promise<{ action: string }> {
  return post(`/api/agent/tasks/${id}/changes/revert`, { path });
}

/** SSE stream URL for live task updates. EventSource can't set headers, so
 *  the token (if any) rides as ?token= — the backend accepts it for SSE. */
export function agentEventsUrl(id: string): string {
  const qs = ARENA_TOKEN ? `?token=${encodeURIComponent(ARENA_TOKEN)}` : "";
  return `/api/agent/tasks/${id}/events${qs}`;
}

export async function listAgentTasks(): Promise<AgentTask[]> {
  const res = await fetch("/api/agent/tasks");
  return ((await asJson(res)).tasks ?? []) as AgentTask[];
}

export async function cancelAgentTask(id: string): Promise<{ id: string; cancelled: boolean; status: string }> {
  return asJson(await fetch(`/api/agent/tasks/${id}`, { method: "DELETE" }));
}

/* ---------------------------------- jobs ----------------------------------- */

export async function createJob(task: string, model: string, max_steps: number): Promise<Job> {
  return post("/api/jobs", { task, model, max_steps });
}

export async function listJobs(): Promise<Job[]> {
  const res = await fetch("/api/jobs");
  return ((await asJson(res)).jobs ?? []) as Job[];
}

export async function getJob(id: string): Promise<Job> {
  return asJson(await fetch(`/api/jobs/${id}`));
}

export async function cancelJob(id: string): Promise<void> {
  await asJson(await fetch(`/api/jobs/${id}`, { method: "DELETE" }));
}

/* ---------------------------------- build ---------------------------------- */

export async function buildTemplates(): Promise<Template[]> {
  const res = await fetch("/api/build/templates");
  return ((await asJson(res)).templates ?? []) as Template[];
}

export async function buildGenerate(name: string, template: string, description: string): Promise<any> {
  return post("/api/build/generate", { name, template, description });
}

export async function buildList(): Promise<BuildInfo[]> {
  const res = await fetch("/api/build/list");
  return ((await asJson(res)).builds ?? []) as BuildInfo[];
}

export async function buildFix(name: string, error: string, model: string): Promise<any> {
  return post("/api/build/fix", { name, error, model });
}

/* --------------------------- run/build jobs (Phase C) --------------------- */

export type RunAction = "install" | "build" | "test" | "serve";

export interface RunJob {
  id: string;
  action: RunAction;
  path: string;
  project_type: string;
  status: "queued" | "running" | "serving" | "passed" | "failed" | "cancelled" | "stopped";
  created: number;
  finished: number | null;
  exit_code: number | null;
  duration: number | null;
  output: string;
  error: string;
  pid: number | null;
  port: number | null;
  url: string | null;
  cmd: string;
}

export async function runJob(
  action: RunAction,
  path = "",
  port?: number
): Promise<RunJob> {
  return post("/api/run", { action, path, port });
}

export async function getRunJob(id: string): Promise<RunJob> {
  return asJson(await fetch(`/api/run/${id}`));
}

export async function cancelRunJob(id: string): Promise<{ cancelled: boolean; status: string }> {
  return asJson(await fetch(`/api/run/${id}`, { method: "DELETE" }));
}

/* ------------------------------ workspace (Phase C) ----------------------- */

export interface WorkspaceInfo {
  layout: Record<string, string>;
  usage: {
    workspace: string;
    akdev_bytes: number;
    limit_bytes: number;
    user_files_bytes: number;
    by_dir: Record<string, number>;
  };
}

export async function getWorkspace(): Promise<WorkspaceInfo> {
  return asJson(await fetch("/api/workspace"));
}

export async function cleanupWorkspace(
  max_age_hours = 24
): Promise<{ removed_files: number; removed_bytes: number; usage: WorkspaceInfo["usage"] }> {
  return post("/api/workspace/cleanup", { max_age_hours });
}

export interface BrowserReport {
  url: string;
  status_code: number | null;
  title: string;
  console_errors: string[];
  failed_requests: string[];
  action_results: { type: string; ok: boolean; text?: string; error?: string }[];
  body_snippet: string;
  has_errors: boolean;
}

export async function browserInspect(url: string, actions: { type: string; selector?: string; value?: string }[] = []): Promise<BrowserReport> {
  return post("/api/browser/inspect", { url, actions });
}

/* ---------------------------------- review --------------------------------- */

export async function reviewDiff(diff: string, model: string): Promise<{ summary: string; findings: Finding[] }> {
  return post("/api/review", { diff, model });
}

/* ---------------------------------- voice ---------------------------------- */

export async function transcribeAudio(blob: Blob): Promise<{ text: string; language: string; duration: number }> {
  const form = new FormData();
  form.append("audio", blob, "speech.webm");
  const res = await fetch("/api/voice/transcribe", { method: "POST", body: form });
  return asJson(res);
}

export async function speakText(text: string): Promise<Blob> {
  const res = await fetch("/api/voice/speak", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  if (!res.ok) {
    const detail = await res
      .json()
      .then((b) => (b as any)?.detail ?? res.statusText)
      .catch(() => res.statusText);
    throw new Error(typeof detail === "string" ? detail : res.statusText);
  }
  return res.blob();
}

/* ---------------------------------- usage ---------------------------------- */

export async function getUsage(): Promise<UsageSummary> {
  return asJson(await fetch("/api/usage"));
}

export async function resetUsage(): Promise<void> {
  await asJson(await fetch("/api/usage", { method: "DELETE" }));
}

/* ------------------------------ mixing (v1.2) ------------------------------ */

export interface Profile {
  id: string;
  name: string;
  description: string;
  tools: string[];
}

export interface Todo {
  id: string;
  text: string;
  done: boolean;
  job: string | null;
}

export interface WorkflowStepInput {
  task: string;
  profile?: string;
  max_steps?: number;
}

export interface Workflow {
  name: string;
  steps: WorkflowStepInput[];
  created: number;
}

export interface WorkflowRunInfo {
  id: string;
  workflow: string;
  status: string;
  current: number;
  total: number;
  results: { task: string; status: string; summary: string }[];
  error: string;
}

export interface SlashCmd {
  name: string;
  description: string;
  builtin: boolean;
}

export interface ComposerPatchView {
  path: string;
  diff: string;
  ok: boolean;
  error: string;
  old_text?: string;
  new_text?: string;
}

export async function repomap(path = ""): Promise<{ map: string; engine: string }> {
  return asJson(await fetch(`/api/code/repomap?path=${encodeURIComponent(path)}`));
}

export async function composerPreview(instructions: string, model: string): Promise<ComposerPatchView[]> {
  const res = await post("/api/code/composer", { instructions, model });
  return (res.patches ?? []) as ComposerPatchView[];
}

export async function composerApply(
  patches: { path: string; old_text: string; new_text: string }[]
): Promise<any> {
  return post("/api/code/composer/apply", { patches });
}

export async function completeCode(file: string, prefix: string, suffix: string, model: string): Promise<string> {
  const res = await post("/api/code/complete", { file, prefix, suffix, model });
  return (res.suggestion ?? "") as string;
}

export async function getRules(): Promise<{ rules: string; found: boolean }> {
  return asJson(await fetch("/api/context/rules"));
}

export interface InstructionsState {
  global: string;
  project: string;
  global_found: boolean;
  project_found: boolean;
}

export async function getInstructions(): Promise<InstructionsState> {
  return asJson(await fetch("/api/context/instructions"));
}

export async function saveGlobalInstructions(content: string): Promise<InstructionsState> {
  const res = await fetch("/api/context/instructions", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content }),
  });
  return asJson(res);
}

export async function saveProjectRules(content: string): Promise<InstructionsState> {
  const res = await fetch("/api/context/rules", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content }),
  });
  return asJson(res);
}

export async function deleteProjectRules(): Promise<InstructionsState> {
  return asJson(await fetch("/api/context/rules", { method: "DELETE" }));
}

export async function getProfiles(): Promise<Profile[]> {
  const res = await fetch("/api/agent/profiles");
  return ((await asJson(res)).profiles ?? []) as Profile[];
}

export async function planTask(task: string, model: string): Promise<{ plan: string[] }> {
  return post("/api/agent/plan", { task, model });
}

export async function getPending(): Promise<{ tool: string }[]> {
  const res = await fetch("/api/agent/pending");
  return ((await asJson(res)).pending ?? []) as { tool: string }[];
}

export async function approveTool(tool: string): Promise<void> {
  await post("/api/agent/approve", { tool });
}

export async function slashList(): Promise<SlashCmd[]> {
  const res = await fetch("/api/slash/list");
  return ((await asJson(res)).commands ?? []) as SlashCmd[];
}

export async function slashRun(command: string, args: string, model: string): Promise<string> {
  const res = await post("/api/slash/run", { command, args, model });
  return (res.output ?? "") as string;
}

export async function mcpStatus(): Promise<{
  installed: boolean;
  servers: { id: string; ok: boolean; tools?: string[]; error?: string }[];
  hint?: string;
}> {
  return asJson(await fetch("/api/mcp/status"));
}

export async function mcpCall(server: string, tool: string, args: Record<string, unknown>): Promise<string> {
  const res = await post("/api/mcp/call", { server, tool, args });
  return (res.result ?? "") as string;
}

export async function listTodos(): Promise<Todo[]> {
  const res = await fetch("/api/todos");
  return ((await asJson(res)).todos ?? []) as Todo[];
}

export async function createTodo(text: string): Promise<Todo> {
  return post("/api/todos", { text });
}

export async function patchTodo(id: string, done: boolean): Promise<void> {
  await asJson(
    await fetch(`/api/todos/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ done }),
    })
  );
}

export async function deleteTodo(id: string): Promise<void> {
  await asJson(await fetch(`/api/todos/${id}`, { method: "DELETE" }));
}

export async function clearTodos(): Promise<void> {
  await post("/api/todos/clear", {});
}

export async function listWorkflows(): Promise<Workflow[]> {
  const res = await fetch("/api/workflows");
  return ((await asJson(res)).workflows ?? []) as Workflow[];
}

export async function saveWorkflow(name: string, steps: WorkflowStepInput[]): Promise<void> {
  await post("/api/workflows", { name, steps });
}

export async function deleteWorkflow(name: string): Promise<void> {
  await asJson(await fetch(`/api/workflows/${name}`, { method: "DELETE" }));
}

export async function runWorkflow(name: string, model: string): Promise<WorkflowRunInfo> {
  return post(`/api/workflows/${name}/run`, { model });
}

export async function getWorkflowRun(id: string): Promise<WorkflowRunInfo> {
  return asJson(await fetch(`/api/workflows/runs/${id}`));
}

export async function webSearch(q: string): Promise<{ title: string; url: string; snippet: string }[]> {
  const res = await post("/api/web/search", { q });
  return (res.results ?? []) as { title: string; url: string; snippet: string }[];
}

export async function webFetch(url: string): Promise<{ title: string; url: string; text: string }> {
  return post("/api/web/fetch", { url });
}

export async function jobArtifacts(id: string): Promise<{ path: string; size: number }[]> {
  const res = await fetch(`/api/jobs/${id}/artifacts`);
  return ((await asJson(res)).artifacts ?? []) as { path: string; size: number }[];
}
