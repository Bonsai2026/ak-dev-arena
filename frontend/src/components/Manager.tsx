import { useEffect, useState } from "react";
import { cancelJob, createJob, getJob, listJobs } from "../api";
import type { Job } from "../api";

interface Props {
  model: string;
}

const STATUS_COLOR: Record<string, string> = {
  queued: "text-amber-400",
  running: "text-indigo-400",
  done: "text-green-400",
  complete: "text-green-400",
  max_steps: "text-amber-400",
  failed: "text-red-400",
  cancelled: "text-zinc-500",
  error: "text-red-400",
};

export default function Manager({ model }: Props) {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [task, setTask] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<Job | null>(null);

  useEffect(() => {
    let alive = true;
    const poll = async () => {
      try {
        const js = await listJobs();
        if (!alive) return;
        setJobs(js);
        if (selected) {
          try {
            setDetail(await getJob(selected));
          } catch {
            /* job may be gone */
          }
        }
      } catch {
        /* backend hiccup — keep polling */
      }
    };
    poll();
    const timer = setInterval(poll, 2000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [selected]);

  const spawn = async () => {
    if (!task.trim()) return;
    const job = await createJob(task.trim(), model, 8);
    setTask("");
    setSelected(job.id);
  };

  return (
    <div className="h-full flex">
      <div className="w-96 shrink-0 border-r border-zinc-800 flex flex-col">
        <div className="p-4 border-b border-zinc-800">
          <h2 className="font-bold mb-1">👁️ Manager</h2>
          <p className="text-xs text-zinc-500 mb-3">Parallel agents — each in its own isolated workspace.</p>
          <div className="flex gap-2">
            <input
              value={task}
              onChange={(e) => setTask(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && spawn()}
              placeholder="New job task…"
              className="flex-1 min-w-0 rounded-lg bg-zinc-900 border border-zinc-700 px-3 py-2 text-sm outline-none focus:border-indigo-500"
            />
            <button onClick={spawn} className="px-4 rounded-lg bg-indigo-600 text-sm font-semibold hover:bg-indigo-500">
              ＋
            </button>
          </div>
        </div>
        <div className="flex-1 overflow-y-auto p-2 space-y-1">
          {jobs.length === 0 && <div className="text-xs text-zinc-600 p-3">No jobs yet.</div>}
          {jobs.map((j) => (
            <button
              key={j.id}
              onClick={() => setSelected(j.id)}
              className={`w-full text-left rounded-lg p-3 border text-sm ${
                selected === j.id ? "bg-zinc-900 border-indigo-700" : "border-zinc-800 hover:bg-zinc-900"
              }`}
            >
              <div className="flex items-center gap-2">
                <span className={`font-mono text-xs ${STATUS_COLOR[j.status] ?? "text-zinc-400"}`}>●</span>
                <span className="font-mono text-xs text-zinc-500">{j.id}</span>
                <span className={`ml-auto text-xs ${STATUS_COLOR[j.status] ?? ""}`}>{j.status}</span>
              </div>
              <div className="truncate mt-1">{j.task}</div>
            </button>
          ))}
        </div>
      </div>

      <div className="flex-1 min-w-0 overflow-y-auto p-4">
        {!detail && <div className="h-full flex items-center justify-center text-zinc-600 text-sm">Select a job.</div>}
        {detail && (
          <div className="space-y-3 text-sm">
            <div className="flex items-center gap-3">
              <h3 className="font-bold flex-1 truncate">{detail.task}</h3>
              {(detail.status === "queued" || detail.status === "running") && (
                <button
                  onClick={() => cancelJob(detail.id)}
                  className="text-xs px-3 py-1.5 rounded bg-red-900/50 border border-red-800 hover:bg-red-900"
                >
                  ⏹ Cancel
                </button>
              )}
            </div>
            <div className="text-xs text-zinc-500">
              id <code>{detail.id}</code> · model <code>{detail.model}</code> · {detail.status}
            </div>
            {detail.error && <div className="text-red-400">⚠️ {detail.error}</div>}
            {(detail.steps ?? []).map((s, i) => (
              <div key={i} className="rounded-lg bg-zinc-900 border border-zinc-800 p-3">
                <div className="font-mono text-indigo-300 text-xs mb-1">
                  #{i + 1} {s.tool}
                </div>
                <pre className="whitespace-pre-wrap text-xs text-zinc-300 max-h-32 overflow-auto">{s.result}</pre>
              </div>
            ))}
            {detail.summary && (
              <div className="rounded-lg border border-indigo-800 bg-indigo-950/30 p-3">📌 {detail.summary}</div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
