import { useState } from "react";
import { runAgent } from "../api";
import type { AgentResult } from "../api";

interface Props {
  model: string;
}

const TOOL_ICON: Record<string, string> = {
  list_files: "📂",
  read_file: "📖",
  write_file: "✏️",
  search: "🔍",
  run: "💻",
  done: "🏁",
  error: "⚠️",
};

export default function Agent({ model }: Props) {
  const [task, setTask] = useState("");
  const [maxSteps, setMaxSteps] = useState(8);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<AgentResult | null>(null);
  const [error, setError] = useState("");

  const go = async () => {
    if (!task.trim() || running) return;
    setRunning(true);
    setError("");
    setResult(null);
    try {
      setResult(await runAgent(task.trim(), model, maxSteps));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Agent run failed");
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="h-full flex flex-col">
      <div className="p-4 border-b border-zinc-800">
        <h2 className="font-bold mb-1">🤖 Agent Mode</h2>
        <p className="text-xs text-zinc-500 mb-3">
          Describe a task — the agent plans, uses file/shell tools in <code>./workspace</code>, and verifies. Shell is
          allow-listed; use git Checkpoints in Code Mode for undo.
        </p>
        <div className="flex gap-2">
          <input
            value={task}
            onChange={(e) => setTask(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && go()}
            placeholder="e.g. Create notes/todo.md with 5 project ideas, then list the workspace"
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
          <button
            onClick={go}
            disabled={running || !task.trim()}
            className="px-6 rounded-lg bg-indigo-600 font-semibold text-sm disabled:opacity-40 hover:bg-indigo-500"
          >
            {running ? "Running…" : "▶ Run"}
          </button>
        </div>
        {error && <div className="mt-2 text-sm text-red-400">⚠️ {error}</div>}
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {!result && !running && (
          <div className="h-full flex items-center justify-center text-zinc-600 text-sm">
            No run yet. Give the agent a task above. Model: <code className="mx-1 text-zinc-400">{model}</code>
          </div>
        )}
        {running && <div className="text-sm text-zinc-400 animate-pulse">🤔 Agent is working…</div>}
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
