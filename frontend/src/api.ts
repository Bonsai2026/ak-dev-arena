/* Typed client for the Arena backend (FastAPI sidecar). */

export interface ChatMessage {
  role: "system" | "user" | "assistant";
  content: string;
}

export interface ModelEntry {
  id: string;
  label: string;
  provider: string;
  best_for: string;
  needs_key: boolean;
  configured: boolean;
}

export interface ProviderEntry {
  provider: string;
  env_var: string | null;
  needs_key: boolean;
  configured: boolean;
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
  totals: { calls: number; prompt: number; completion: number; total: number };
  by_model: { model: string; calls: number; prompt: number; completion: number; total: number }[];
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

export async function getModels(): Promise<{ models: ModelEntry[]; defaults: Record<string, string> }> {
  return asJson(await fetch("/api/models"));
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

/** POST /api/chat/stream and invoke onToken per SSE delta. */
export async function streamChat(
  model: string,
  messages: ChatMessage[],
  onToken: (token: string) => void
): Promise<void> {
  const res = await fetch("/api/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model, messages }),
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

export async function runAgent(task: string, model: string, max_steps: number): Promise<AgentResult> {
  return post("/api/agent/run", { task, model, max_steps });
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
