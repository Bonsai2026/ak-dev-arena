import { useEffect, useState } from "react";
import { approveTool, getPending, getProfiles, planTask, runAgent } from "../api";
import type { AgentResult, Profile } from "../api";

interface Props {
  model: string;
}

const TOOL_ICON: Record<string, string> = {
  list_files: "📂",
  read_file: "📖",
  write_file: "✏️",
  search: "🔍",
  run: "💻",
  web_search: "🌐",
  web_fetch: "📄",
  todo: "☑️",
  mcp: "🔌",
  done: "🏁",
  error: "⚠️",
};

export default function Agent({ model }: Props) {
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [profile, setProfile] = useState("coder");
  const [task, setTask] = useState("");
  const [maxSteps, setMaxSteps] = useState(8);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<AgentResult | null>(null);
  const [plan, setPlan] = useState<string[]>([]);
  const [planning, setPlanning] = useState(false);
  const [pending, setPending] = useState<{ tool: string }[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    getProfiles().then(setProfiles).catch(() => {});
    getPending().then(setPending).catch(() => {});
  }, []);

  const go = async () => {
    if (!task.trim() || running) return;
    setRunning(true);
    setError("");
    setResult(null);
    try {
      setResult(await runAgent(task.trim(), model, maxSteps, profile));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Agent run failed");
    } finally {
      setRunning(false);
      getPending().then(setPending).catch(() => {});
    }
  };

  const doPlan = async () => {
    if (!task.trim() || planning) return;
    setPlanning(true);
    setError("");
    try {
      const res = await planTask(task.trim(), model);
      setPlan(res.plan ?? []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Plan failed");
    } finally {
      setPlanning(false);
    }
  };

  return (
    <div className="h-full flex flex-col">
      <div className="p-4 border-b border-zinc-800">
        <h2 className="font-bold mb-1">🤖 Agent Mode</h2>
        <p className="text-xs text-zinc-500 mb-3">
          Specialized profiles · Plan mode · tool approvals · web + todos + MCP tools. Works in{" "}
          <code>./workspace</code>.
        </p>
        <div className="flex gap-2 mb-2">
          <select
            value={profile}
            onChange={(e) => setProfile(e.target.value)}
            className="rounded-lg bg-zinc-900 border border-zinc-700 px-3 py-2.5 text-sm"
            title="Agent profile"
          >
            {profiles.map((p) => (
              <option key={p.id} value={p.id} title={p.description}>
                {p.name} — {p.tools.length} tools
              </option>
            ))}
          </select>
          <input
            value={task}
            onChange={(e) => setTask(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && go()}
            placeholder="e.g. Research vector DBs, then write notes/vectordb.md"
            className="flex-1 rounded-lg bg-zinc-900 border border-zinc-700 px-4 py-2.5 text-sm outline-none focus:border-indigo-500"
          />
          <select
            value={maxSteps}
            onChange={(e) => setMaxSteps(Number(e.target.value))}
            className="rounded-lg bg-zinc-900 border border-zinc-700 px-2 text-sm"
            title="Max steps"
          >
            {[4, 8, 12, 16, 25].map((n) => (
              <option key={n} value={n}>
                {n} steps
              </option>
            ))}
          </select>
        </div>
        <div className="flex gap-2">
          <button
            onClick={doPlan}
            disabled={planning || !task.trim()}
            className="px-5 py-2 rounded-lg bg-zinc-800 text-sm font-semibold disabled:opacity-40 hover:bg-zinc-700"
          >
            {planning ? "Planning…" : "🗺 Plan (no tools)"}
          </button>
          <button
            onClick={go}
            disabled={running || !task.trim()}
            className="px-6 py-2 rounded-lg bg-indigo-600 font-semibold text-sm disabled:opacity-40 hover:bg-indigo-500"
          >
            {running ? "Running…" : "▶ Run"}
          </button>
        </div>
        {error && <div className="mt-2 text-sm text-red-400">⚠️ {error}</div>}
        {pending.length > 0 && (
          <div className="mt-2 flex items-center gap-2 text-sm flex-wrap">
            <span className="text-amber-400">⏳ Needs approval:</span>
            {pending.map((p, i) => (
              <button
                key={i}
                onClick={async () => {
                  await approveTool(p.tool);
                  setPending(await getPending());
                }}
                className="text-xs px-2 py-1 rounded bg-amber-900/50 border border-amber-700 hover:bg-amber-900"
              >
                ✅ {p.tool}
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {plan.length > 0 && (
          <div className="rounded-lg border border-emerald-800 bg-emerald-950/30 p-3 text-sm">
            <div className="font-semibold mb-1">🗺 Plan (also saved to Todos):</div>
            <ol className="list-decimal ml-5 space-y-0.5">
              {plan.map((s, i) => (
                <li key={i}>{s}</li>
              ))}
            </ol>
          </div>
        )}
        {!result && !running && plan.length === 0 && (
          <div className="h-full flex items-center justify-center text-zinc-600 text-sm">
            No run yet. Model: <code className="mx-1 text-zinc-400">{model}</code>
          </div>
        )}
        {running && <div className="text-sm text-zinc-400 animate-pulse">🤔 Agent ({profile}) is working…</div>}
        {result?.steps.map((s, i) => (
          <div key={i} className="rounded-lg bg-zinc-900 border border-zinc-800 p-3 text-sm">
            <div className="flex items-center gap-2 mb-1">
              <span className="text-zinc-500 text-xs">#{i + 1}</span>
              <span>{TOOL_ICON[s.tool] ?? "🔧"}</span>
              <span className="font-mono text-indigo-300">{s.tool}</span>
            </div>
            {s.thought && <div className="text-zinc-400 italic mb-1">💭 {s.thought}</div>}
            <pre className="whitespace-pre-wrap text-xs text-zinc-300 max-h-40 overflow-auto">{s.result}</pre>
          </div>
        ))}
        {result && (
          <div className="rounded-lg border border-indigo-800 bg-indigo-950/30 p-3 text-sm">
            <span className="font-semibold">📌 {result.status.toUpperCase()}:</span> {result.summary}
          </div>
        )}
      </div>
    </div>
  );
}
