import { useEffect, useRef, useState } from "react";
import {
  buildFix,
  buildGenerate,
  buildList,
  buildTemplates,
  cancelRunJob,
  cleanupWorkspace,
  getRunJob,
  getWorkspace,
  runJob,
} from "../api";
import type { BuildInfo, RunAction, RunJob, Template, WorkspaceInfo } from "../api";

interface Props {
  model: string;
}

const ACTIONS: RunAction[] = ["install", "build", "test", "serve"];
const RUN_LABEL: Record<RunAction, string> = {
  install: "📦 Install",
  build: "🏗️ Build",
  test: "🧪 Test",
  serve: "🚀 Serve",
};
const RUN_TERMINAL = new Set(["passed", "failed", "cancelled", "stopped", "interrupted"]);

function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

export default function Build({ model }: Props) {
  const [templates, setTemplates] = useState<Template[]>([]);
  const [builds, setBuilds] = useState<BuildInfo[]>([]);
  const [name, setName] = useState("");
  const [template, setTemplate] = useState("static-html");
  const [desc, setDesc] = useState("");
  const [msg, setMsg] = useState("");
  const [fixName, setFixName] = useState("");
  const [fixError, setFixError] = useState("");
  const [fixDiff, setFixDiff] = useState("");
  const [runPath, setRunPath] = useState(""); // "" = workspace root
  const [job, setJob] = useState<RunJob | null>(null);
  const [wsInfo, setWsInfo] = useState<WorkspaceInfo | null>(null);
  const [cleaning, setCleaning] = useState(false);
  const pollRef = useRef<number | null>(null);

  const running = job !== null && !RUN_TERMINAL.has(job.status);

  const refresh = async () => {
    try {
      const [t, b, w] = await Promise.all([buildTemplates(), buildList(), getWorkspace()]);
      setTemplates(t);
      setBuilds(b);
      setWsInfo(w);
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "Load failed");
    }
  };

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(
    () => () => {
      if (pollRef.current) window.clearInterval(pollRef.current);
    },
    []
  );

  const run = async (action: RunAction) => {
    if (running) return;
    setMsg("");
    try {
      const started = await runJob(action, runPath);
      setJob(started);
      if (pollRef.current) window.clearInterval(pollRef.current);
      pollRef.current = window.setInterval(async () => {
        try {
          const next = await getRunJob(started.id);
          setJob(next);
          if (RUN_TERMINAL.has(next.status) && pollRef.current) {
            window.clearInterval(pollRef.current);
            pollRef.current = null;
          }
        } catch {
          if (pollRef.current) window.clearInterval(pollRef.current);
          pollRef.current = null;
        }
      }, 1000);
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "Run failed");
    }
  };

  const stopRun = async () => {
    if (!job) return;
    try {
      await cancelRunJob(job.id);
      if (pollRef.current) window.clearInterval(pollRef.current);
      pollRef.current = null;
      setJob(await getRunJob(job.id));
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "Stop failed");
    }
  };

  const clean = async () => {
    setCleaning(true);
    try {
      const res = await cleanupWorkspace(24);
      setWsInfo((w) => (w ? { ...w, usage: res.usage } : null));
      setMsg(`🧹 Cleaned ${res.removed_files} files (${fmtBytes(res.removed_bytes)})`);
      refresh();
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "Cleanup failed");
    } finally {
      setCleaning(false);
    }
  };

  const generate = async () => {
    if (!name.trim()) return;
    try {
      const res = await buildGenerate(name.trim().toLowerCase(), template, desc.trim());
      setMsg(`✅ Generated ${res.path} (${res.files.length} files)`);
      setName("");
      setDesc("");
      refresh();
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "Generate failed");
    }
  };

  const fix = async () => {
    if (!fixName || !fixError.trim()) return;
    try {
      const res = await buildFix(fixName, fixError.trim(), model);
      setFixDiff(res.diff);
      setMsg(`✅ Patch applied to ${res.path}`);
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "Fix failed");
    }
  };

  return (
    <div className="h-full overflow-y-auto p-6">
      <h2 className="font-bold text-lg mb-1">🏗️ Build Mode</h2>
      <p className="text-xs text-zinc-500 mb-4">
        Create a project, then <b>install → build → test → serve</b> for real. Errors are captured
        with exit codes; paste them below and let the agent fix them. <code>./workspace</code> only.
      </p>
      {msg && <div className="text-sm text-zinc-300 bg-zinc-900 border border-zinc-800 rounded-lg px-4 py-2 mb-4">{msg}</div>}

      {/* ------------------------------------------------------ run panel */}
      <div className="rounded-xl border border-zinc-800 bg-zinc-900/50 p-4 mb-6">
        <div className="flex items-center gap-3 mb-3">
          <h3 className="font-bold text-sm">⚙️ Run & Verify</h3>
          <select
            value={runPath}
            onChange={(e) => setRunPath(e.target.value)}
            className="ml-auto rounded-lg bg-zinc-950 border border-zinc-700 px-2 py-1.5 text-xs"
            title="Project to run (workspace root or a build)"
          >
            <option value="">workspace root</option>
            {builds.map((b) => (
              <option key={b.name} value={b.path}>
                {b.name}
              </option>
            ))}
          </select>
        </div>
        <div className="flex gap-2 flex-wrap">
          {ACTIONS.map((a) => (
            <button
              key={a}
              onClick={() => run(a)}
              disabled={running}
              className={`px-4 py-2 rounded-lg text-sm font-semibold disabled:opacity-40 ${
                a === "serve"
                  ? "bg-emerald-800 hover:bg-emerald-700"
                  : "bg-zinc-800 hover:bg-zinc-700"
              }`}
            >
              {RUN_LABEL[a]}
            </button>
          ))}
          {job && (
            <button
              onClick={stopRun}
              className="px-4 py-2 rounded-lg text-sm font-semibold bg-red-700 hover:bg-red-600"
            >
              ⏹ Stop
            </button>
          )}
        </div>
        {job && (
          <div className="mt-3 rounded-lg bg-zinc-950 border border-zinc-800 p-3">
            <div className="flex items-center gap-2 text-xs mb-2">
              <span className="font-mono text-indigo-300">{job.cmd}</span>
              <span
                className={`ml-auto font-semibold ${
                  job.status === "passed"
                    ? "text-emerald-400"
                    : job.status === "failed"
                      ? "text-red-400"
                      : job.status === "serving"
                        ? "text-emerald-300"
                        : "text-zinc-400"
                }`}
              >
                {job.status}
                {job.exit_code !== null && ` · exit ${job.exit_code}`}
                {job.duration !== null && ` · ${job.duration}s`}
              </span>
            </div>
            {job.url && (
              <div className="text-xs text-emerald-400 mb-2">
                🔗 <a href={job.url} target="_blank" rel="noreferrer" className="underline">{job.url}</a>
                {job.pid && <span className="text-zinc-600"> · pid {job.pid}</span>}
              </div>
            )}
            {job.error && <div className="text-xs text-red-400 mb-2">⚠️ {job.error}</div>}
            <pre className="whitespace-pre-wrap text-[11px] text-zinc-300 max-h-52 overflow-auto">
              {job.output || (job.status === "running" ? "running…" : "(no output)")}
            </pre>
          </div>
        )}
      </div>

      {/* ---------------------------------------------------- templates */}
      <h3 className="font-bold mb-2">🧩 Templates</h3>
      <div className="grid grid-cols-3 gap-3 mb-3">
        {templates.map((t) => (
          <button
            key={t.id}
            onClick={() => setTemplate(t.id)}
            className={`text-left rounded-xl border p-4 ${
              template === t.id ? "border-indigo-500 bg-indigo-950/20" : "border-zinc-800 hover:border-zinc-600"
            }`}
          >
            <div className="font-mono text-sm font-bold">{t.id}</div>
            <div className="text-xs text-zinc-400 mt-1">{t.description}</div>
            <div className="text-[11px] text-zinc-600 mt-2">{t.files.length} files</div>
          </button>
        ))}
      </div>

      <div className="flex gap-2 mb-6">
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="project-name (lowercase)"
          className="w-56 rounded-lg bg-zinc-900 border border-zinc-700 px-3 py-2 text-sm outline-none focus:border-indigo-500"
        />
        <input
          value={desc}
          onChange={(e) => setDesc(e.target.value)}
          placeholder="One-line description…"
          className="flex-1 rounded-lg bg-zinc-900 border border-zinc-700 px-3 py-2 text-sm outline-none focus:border-indigo-500"
        />
        <button onClick={generate} className="px-6 rounded-lg bg-indigo-600 text-sm font-semibold hover:bg-indigo-500">
          🚀 Generate
        </button>
      </div>

      {/* ------------------------------------------------------ projects */}
      <h3 className="font-bold mb-2">📦 Projects ({builds.length})</h3>
      <div className="space-y-1 mb-6">
        {builds.map((b) => (
          <div key={b.name} className="flex items-center gap-3 text-sm rounded-lg bg-zinc-900 border border-zinc-800 px-4 py-2">
            <span className="font-mono font-bold">{b.name}</span>
            <span className="text-zinc-500 text-xs">
              {b.path} · {b.files} files
            </span>
            <button onClick={() => { setFixName(b.name); setRunPath(b.path); }} className="ml-auto text-xs text-indigo-400 hover:underline">
              verify ↓
            </button>
          </div>
        ))}
        {builds.length === 0 && <div className="text-sm text-zinc-600">No projects yet.</div>}
      </div>

      {/* ------------------------------------------------ error fix loop */}
      <h3 className="font-bold mb-2">🩹 Error → Fix loop</h3>
      <div className="rounded-xl border border-zinc-800 bg-zinc-900/50 p-4 mb-6">
        <div className="flex gap-2 mb-2">
          <select
            value={fixName}
            onChange={(e) => setFixName(e.target.value)}
            className="rounded-lg bg-zinc-950 border border-zinc-700 px-3 py-2 text-sm"
          >
            <option value="">select project…</option>
            {builds.map((b) => (
              <option key={b.name} value={b.name}>
                {b.name}
              </option>
            ))}
          </select>
          <textarea
            value={fixError}
            onChange={(e) => setFixError(e.target.value)}
            rows={3}
            placeholder="Paste the build/test error output here…"
            className="flex-1 rounded-lg bg-zinc-900 border border-zinc-700 px-3 py-2 text-xs outline-none focus:border-indigo-500"
          />
          <button
            onClick={fix}
            disabled={!fixName || !fixError.trim()}
            className="px-5 rounded-lg bg-emerald-700 text-sm font-semibold disabled:opacity-40 hover:bg-emerald-600"
          >
            🤖 Fix
          </button>
        </div>
        {fixDiff && <pre className="arena-code whitespace-pre-wrap text-xs">{fixDiff}</pre>}
        <p className="text-[11px] text-zinc-600 mt-2">
          The agent receives the actual error + project files and applies a minimal patch (diff
          preview above). Run <b>Test</b> again to verify.
        </p>
      </div>

      {/* -------------------------------------------------- workspace info */}
      <h3 className="font-bold mb-2">🗂️ Workspace health</h3>
      <div className="rounded-xl border border-zinc-800 bg-zinc-900/50 p-4 flex items-center gap-4 text-sm">
        <span className="text-zinc-400">
          <code>{wsInfo?.usage.workspace ?? "…"}</code>
        </span>
        <span className="text-zinc-500 text-xs">
          .akdev: <b className="text-zinc-300">{wsInfo ? fmtBytes(wsInfo.usage.akdev_bytes) : "…"}</b>
          {" · "}limit {wsInfo ? fmtBytes(wsInfo.usage.limit_bytes) : "…"}
          {" · "}user files {wsInfo ? fmtBytes(wsInfo.usage.user_files_bytes) : "…"}
        </span>
        <button
          onClick={clean}
          disabled={cleaning}
          className="ml-auto px-4 py-1.5 rounded-lg bg-zinc-800 text-xs font-semibold hover:bg-zinc-700 disabled:opacity-40"
        >
          {cleaning ? "cleaning…" : "🧹 Clean temp (>24h)"}
        </button>
      </div>
    </div>
  );
}
