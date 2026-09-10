import { useEffect, useMemo, useRef, useState } from "react";
import {
  agentEventsUrl,
  approveTool,
  cancelAgentTask,
  createAgentTask,
  getAgentChanges,
  getAgentTask,
  getPending,
  getProfiles,
  planTask,
  revertAgentChange,
} from "../api";
import type { AgentTask, FileChange, Profile } from "../api";

interface Props {
  model: string;
}

const TOOL_ICON: Record<string, string> = {
  list_files: "📂",
  read_file: "📖",
  write_file: "✏️",
  edit_file: "🔧",
  delete_file: "🗑️",
  search: "🔍",
  run: "💻",
  run_build: "🏗️",
  run_tests: "🧪",
  install_dependency: "📦",
  start_server: "🚀",
  stop_server: "🛑",
  git_status: "🌿",
  git_diff: "📊",
  git_checkpoint: "💾",
  git_revert: "↩️",
  web_search: "🌐",
  web_fetch: "📄",
  todo: "☑️",
  mcp: "🔌",
  done: "🏁",
  error: "⚠️",
};

const STATUS_BADGE: Record<string, string> = {
  queued: "text-zinc-400 border-zinc-700",
  running: "text-indigo-300 border-indigo-800 animate-pulse",
  complete: "text-emerald-400 border-emerald-800",
  done: "text-emerald-400 border-emerald-800",
  failed: "text-red-400 border-red-800",
  cancelled: "text-amber-400 border-amber-800",
  timeout: "text-amber-400 border-amber-800",
  interrupted: "text-orange-400 border-orange-800",
};

const TERMINAL = new Set(["complete", "done", "failed", "cancelled", "timeout", "interrupted"]);

export default function Agent({ model }: Props) {
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [profile, setProfile] = useState("coder");
  const [taskText, setTaskText] = useState("");
  const [maxSteps, setMaxSteps] = useState(8);
  const [taskState, setTaskState] = useState<AgentTask | null>(null);
  const [plan, setPlan] = useState<string[]>([]);
  const [planning, setPlanning] = useState(false);
  const [pending, setPending] = useState<{ tool: string }[]>([]);
  const [error, setError] = useState("");
  const pollRef = useRef<number | null>(null);
  const esRef = useRef<EventSource | null>(null);
  const [autoPlan, setAutoPlan] = useState(true);
  const [changes, setChanges] = useState<FileChange[]>([]);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [msg, setMsg] = useState("");

  const running = taskState !== null && !TERMINAL.has(taskState.status);

  useEffect(() => {
    getProfiles().then(setProfiles).catch(() => {});
    getPending().then(setPending).catch(() => {});
  }, []);

  useEffect(() => () => {
    if (pollRef.current) window.clearInterval(pollRef.current);
    if (esRef.current) esRef.current.close();
  }, []);

  // Load the agent's file changes (diff review) — refresh on progress.
  useEffect(() => {
    if (!taskState) { setChanges([]); return; }
    const id = taskState.id;
    getAgentChanges(id).then(setChanges).catch(() => {});
  }, [taskState?.id, taskState?.status, taskState?.steps?.length]);

  const poll = async (id: string) => {
    try {
      const state = await getAgentTask(id);
      setTaskState(state);
      if (TERMINAL.has(state.status)) {
        if (pollRef.current) window.clearInterval(pollRef.current);
        pollRef.current = null;
        setError(state.error || "");
        getPending().then(setPending).catch(() => {});
      }
    } catch (e) {
      if (pollRef.current) window.clearInterval(pollRef.current);
      pollRef.current = null;
      setError(e instanceof Error ? e.message : "Task lookup failed");
    }
  };

  const closeStream = () => {
    if (esRef.current) { esRef.current.close(); esRef.current = null; }
  };

  // Live updates via SSE; falls back to 1.2s polling if the stream fails.
  const stream = (id: string) => {
    closeStream();
    if (pollRef.current) { window.clearInterval(pollRef.current); pollRef.current = null; }
    try {
      const es = new EventSource(agentEventsUrl(id));
      esRef.current = es;
      es.onmessage = (ev) => {
        try {
          const state = JSON.parse(ev.data) as AgentTask;
          if ((state as unknown as { detail?: string }).detail) return; // task gone
          setTaskState(state);
          if (TERMINAL.has(state.status)) {
            closeStream();
            setError(state.error || "");
            getPending().then(setPending).catch(() => {});
          }
        } catch { /* ignore malformed frame */ }
      };
      es.onerror = () => {
        closeStream();
        if (!pollRef.current) pollRef.current = window.setInterval(() => poll(id), 1200);
      };
    } catch {
      pollRef.current = window.setInterval(() => poll(id), 1200);
    }
  };

  const go = async () => {
    if (!taskText.trim() || running) return;
    setError("");
    setMsg("");
    setTaskState(null);
    setPlan([]);
    setChanges([]);
    setExpanded(null);
    try {
      if (autoPlan) {
        const res = await planTask(taskText.trim(), model);
        setPlan(res.plan ?? []);
      }
      const state = await createAgentTask(taskText.trim(), model, maxSteps, profile);
      setTaskState(state);
      stream(state.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Agent run failed");
    }
  };

  const stop = async () => {
    if (!taskState) return;
    try {
      await cancelAgentTask(taskState.id);
      await poll(taskState.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Cancel failed");
    }
  };

  const doPlan = async () => {
    if (!taskText.trim() || planning) return;
    setPlanning(true);
    setError("");
    try {
      const res = await planTask(taskText.trim(), model);
      setPlan(res.plan ?? []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Plan failed");
    } finally {
      setPlanning(false);
    }
  };

  const steps = taskState?.steps ?? [];
  const lastStep = steps[steps.length - 1];
  const verification = taskState?.verification;
  const criteria = taskState?.criteria ?? [];

  const evidenceLine = useMemo(() => {
    if (!verification) return "";
    const parts: string[] = [];
    if (verification.build) parts.push(`Build ${verification.build}`);
    if (verification.tests) parts.push(`Tests ${verification.tests}`);
    return parts.join(" · ");
  }, [verification]);

  return (
    <div className="h-full flex flex-col">
      <div className="p-4 border-b border-zinc-800">
        <h2 className="font-bold mb-1">🤖 Agent Mode</h2>
        <p className="text-xs text-zinc-500 mb-3">
          Plan → act → build → test → verify. The agent runs real commands and reports evidence — it never
          claims success without running it. Works in <code>./workspace</code>.
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
            value={taskText}
            onChange={(e) => setTaskText(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && go()}
            placeholder="e.g. Fix the login button, then run the build and tests"
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
        <div className="flex gap-2 items-center">
          <button
            onClick={doPlan}
            disabled={planning || !taskText.trim() || running}
            className="px-5 py-2 rounded-lg bg-zinc-800 text-sm font-semibold disabled:opacity-40 hover:bg-zinc-700"
          >
            {planning ? "Planning…" : "🗺 Plan only"}
          </button>
          {running ? (
            <button
              onClick={stop}
              className="px-6 py-2 rounded-lg bg-red-700 font-semibold text-sm hover:bg-red-600"
            >
              ⏹ Stop
            </button>
          ) : (
            <button
              onClick={go}
              disabled={!taskText.trim()}
              className="px-6 py-2 rounded-lg bg-indigo-600 font-semibold text-sm disabled:opacity-40 hover:bg-indigo-500"
            >
              ▶ Run Agent
            </button>
          )}
          <label className="ml-auto flex items-center gap-1.5 text-xs text-zinc-500">
            <input type="checkbox" checked={autoPlan} onChange={(e) => setAutoPlan(e.target.checked)} />
            auto-plan first
          </label>
        </div>
        {error && <div className="mt-2 text-sm text-red-400">⚠️ {error}</div>}
        {msg && <div className="mt-2 text-sm text-emerald-400">✅ {msg}</div>}
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
        {taskState && (
          <div className="rounded-lg border border-zinc-800 bg-zinc-900/60 p-3 text-sm flex items-center gap-3">
            <span className={`text-xs font-semibold px-2 py-1 rounded border ${STATUS_BADGE[taskState.status] ?? "text-zinc-400"}`}>
              {taskState.status.toUpperCase()}
            </span>
            <span className="text-zinc-400 truncate flex-1">
              {running
                ? taskState.current
                  ? `${TOOL_ICON[taskState.current.tool] ?? "🔧"} ${taskState.current.tool} — ${taskState.current.thought || taskState.current.result.slice(0, 80)}`
                  : "Planning…"
                : taskState.summary || taskState.error}
            </span>
            {taskState.finished && (
              <span className="text-[11px] text-zinc-600">
                {(taskState.finished - taskState.started!) / 1000 < 60
                  ? `${Math.round((taskState.finished - taskState.started!) / 1000)}s`
                  : `${Math.round((taskState.finished - taskState.started!) / 60000)}m`}
              </span>
            )}
          </div>
        )}

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

        {criteria.length > 0 && (
          <div className="rounded-lg border border-zinc-800 bg-zinc-900/60 p-3 text-sm">
            <div className="font-semibold mb-1">✅ Success criteria</div>
            <ul className="space-y-0.5">
              {criteria.map((c, i) => (
                <li key={i}>
                  <span className={c.status === "pass" ? "text-emerald-400" : c.status === "fail" ? "text-red-400" : "text-zinc-500"}>
                    {c.status === "pass" ? "✔" : c.status === "fail" ? "✘" : "⚠"} {c.criteria}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {verification && (
          <div className="rounded-lg border border-zinc-800 bg-zinc-900/60 p-3 text-sm flex items-center gap-3">
            <span className="font-semibold">🔬 Verification</span>
            <span className={verification.has_evidence ? "text-emerald-400" : "text-zinc-500"}>
              {evidenceLine || (verification.has_evidence ? "evidence collected" : "no build/test evidence — agent did not run verification")}
            </span>
          </div>
        )}

        {taskState?.files && taskState.files.length > 0 && (
          <div className="rounded-lg border border-zinc-800 bg-zinc-900/60 p-3 text-sm">
            <div className="font-semibold mb-1">📁 Files changed</div>
            <div className="flex flex-wrap gap-1.5">
              {taskState.files.slice(-15).map((f, i) => (
                <code key={i} className="text-xs px-2 py-0.5 rounded bg-zinc-800 text-indigo-300">{f}</code>
              ))}
            </div>
          </div>
        )}

        {changes.length > 0 && (
          <div className="rounded-lg border border-zinc-800 bg-zinc-900/60 p-3 text-sm">
            <div className="font-semibold mb-2">🔍 Change review <span className="text-zinc-500 font-normal text-xs">— diff + 1-click undo (session-only)</span></div>
            {changes.map((c) => (
              <div key={c.path} className="mb-2 border border-zinc-800 rounded-md overflow-hidden">
                <div className="flex items-center gap-2 px-2 py-1.5 bg-zinc-900">
                  <span className={
                    c.status === "added" ? "text-emerald-400" :
                    c.status === "deleted" ? "text-red-400" : "text-amber-300"
                  }>{c.status === "added" ? "＋" : c.status === "deleted" ? "－" : "✎"}</span>
                  <code className="text-xs text-indigo-300 flex-1 truncate">{c.path}</code>
                  <span className="text-[11px] text-emerald-400">+{c.additions}</span>
                  <span className="text-[11px] text-red-400">−{c.deletions}</span>
                  <button
                    className="text-[11px] px-2 py-0.5 rounded border border-zinc-700 text-zinc-300 hover:bg-zinc-800"
                    onClick={() => setExpanded(expanded === c.path ? null : c.path)}
                  >{expanded === c.path ? "hide diff" : "diff"}</button>
                  <button
                    className="text-[11px] px-2 py-0.5 rounded border border-amber-900 text-amber-300 hover:bg-amber-950/40 disabled:opacity-40"
                    disabled={running}
                    title={running ? "Wait for the task to finish before reverting" : "Undo this change"}
                    onClick={async () => {
                      if (!taskState || !confirm(`Revert ${c.path} to its before-state?`)) return;
                      try {
                        const res = await revertAgentChange(taskState.id, c.path);
                        setChanges((prev) => prev.filter((x) => x.path !== c.path));
                        setError("");
                        setMsg(`Reverted ${c.path} — ${res.action}`);
                      } catch (e) {
                        setError(e instanceof Error ? e.message : "Revert failed");
                      }
                    }}
                  >↩ undo</button>
                </div>
                {expanded === c.path && (
                  <pre className="text-[11px] leading-4 p-2 overflow-auto max-h-64 bg-black/40 whitespace-pre">{
                    c.diff.split("\n").map((l, i) => (
                      <div key={i} className={
                        l.startsWith("+") ? "text-emerald-400" :
                        l.startsWith("-") ? "text-red-400" :
                        l.startsWith("@@") ? "text-indigo-300" : "text-zinc-500"
                      }>{l || " "}</div>
                    ))
                  }</pre>
                )}
              </div>
            ))}
          </div>
        )}

        {steps.length === 0 && !running && !taskState && !plan.length && (
          <div className="h-full flex items-center justify-center text-zinc-600 text-sm">
            No run yet. Model: <code className="mx-1 text-zinc-400">{model}</code>
          </div>
        )}

        {steps.map((s, i) => (
          <div key={i} className={`rounded-lg border p-3 text-sm ${s.tool === "error" ? "border-red-900 bg-red-950/20" : "bg-zinc-900 border-zinc-800"}`}>
            <div className="flex items-center gap-2 mb-1">
              <span className="text-zinc-500 text-xs">#{i + 1}</span>
              <span>{TOOL_ICON[s.tool] ?? "🔧"}</span>
              <span className="font-mono text-indigo-300">{s.tool}</span>
              {i === steps.length - 1 && running && <span className="text-[10px] text-indigo-300 animate-pulse">running</span>}
            </div>
            {s.thought && <div className="text-zinc-400 italic mb-1">💭 {s.thought}</div>}
            <pre className="whitespace-pre-wrap text-xs text-zinc-300 max-h-40 overflow-auto">{s.result}</pre>
          </div>
        ))}
        {lastStep?.result.startsWith("ERROR:") && running && (
          <div className="text-xs text-zinc-500">Agent got an error — it will try to recover on the next step.</div>
        )}
      </div>
    </div>
  );
}
