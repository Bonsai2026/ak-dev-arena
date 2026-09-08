import { useEffect, useState } from "react";
import {
  cancelJob,
  clearTodos,
  createJob,
  createTodo,
  deleteTodo,
  deleteWorkflow,
  getJob,
  getProfiles,
  getWorkflowRun,
  jobArtifacts,
  listJobs,
  listTodos,
  listWorkflows,
  mcpCall,
  mcpStatus,
  patchTodo,
  runWorkflow,
  saveWorkflow,
  slashList,
  slashRun,
  webFetch,
  webSearch,
} from "../api";
import type { Job, Profile, SlashCmd, Todo, Workflow } from "../api";

interface Props {
  model: string;
}

type Tab = "jobs" | "todos" | "workflows" | "tools";

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
  const [tab, setTab] = useState<Tab>("jobs");
  // jobs
  const [jobs, setJobs] = useState<Job[]>([]);
  const [task, setTask] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<Job | null>(null);
  const [artifacts, setArtifacts] = useState<{ path: string; size: number }[]>([]);
  // todos
  const [todos, setTodos] = useState<Todo[]>([]);
  const [todoText, setTodoText] = useState("");
  // workflows
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [wfName, setWfName] = useState("");
  const [wfSteps, setWfSteps] = useState("");
  const [wfProfile, setWfProfile] = useState("coder");
  const [wfRun, setWfRun] = useState("");
  // tools
  const [cmds, setCmds] = useState<SlashCmd[]>([]);
  const [slashOut, setSlashOut] = useState("");
  const [mcp, setMcp] = useState<{ installed: boolean; servers: { id: string; ok: boolean; tools?: string[]; error?: string }[]; hint?: string } | null>(null);
  const [mcpForm, setMcpForm] = useState({ server: "", tool: "", args: "{}" });
  const [mcpOut, setMcpOut] = useState("");
  const [webQ, setWebQ] = useState("");
  const [webOut, setWebOut] = useState("");
  const [msg, setMsg] = useState("");

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
            setArtifacts(await jobArtifacts(selected));
          } catch {
            /* gone */
          }
        }
      } catch {
        /* hiccup */
      }
    };
    poll();
    const timer = setInterval(poll, 2000);
    getProfiles().then(setProfiles).catch(() => {});
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [selected]);

  useEffect(() => {
    if (tab === "todos") listTodos().then(setTodos).catch(() => {});
    if (tab === "workflows") listWorkflows().then(setWorkflows).catch(() => {});
    if (tab === "tools") {
      slashList().then(setCmds).catch(() => {});
      mcpStatus().then(setMcp).catch(() => {});
    }
  }, [tab]);

  const spawn = async () => {
    if (!task.trim()) return;
    const job = await createJob(task.trim(), model, 8);
    setTask("");
    setSelected(job.id);
  };

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center gap-2 px-4 py-2.5 border-b border-zinc-800 text-sm">
        <h2 className="font-bold mr-2">👁️ Manager</h2>
        {(["jobs", "todos", "workflows", "tools"] as Tab[]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-3 py-1.5 rounded capitalize ${tab === t ? "bg-zinc-800 font-semibold" : "text-zinc-500"}`}
          >
            {t === "jobs" ? "⚡ Jobs" : t === "todos" ? "☑️ Todos" : t === "workflows" ? "🔁 Workflows" : "🧰 Tools"}
          </button>
        ))}
      </div>
      {msg && <div className="px-4 py-1.5 text-xs text-zinc-400 border-b border-zinc-800">{msg}</div>}

      {tab === "jobs" && (
        <div className="flex-1 min-h-0 flex">
          <div className="w-96 shrink-0 border-r border-zinc-800 flex flex-col">
            <div className="p-4 border-b border-zinc-800">
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
                {artifacts.length > 0 && (
                  <div className="rounded-lg bg-zinc-900 border border-zinc-800 p-3">
                    <div className="text-[11px] uppercase tracking-widest text-zinc-500 mb-1">
                      📦 Artifacts ({artifacts.length})
                    </div>
                    {artifacts.map((a) => (
                      <div key={a.path} className="font-mono text-xs text-zinc-300">
                        {a.path} <span className="text-zinc-600">({a.size}b)</span>
                      </div>
                    ))}
                  </div>
                )}
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
      )}

      {tab === "todos" && (
        <div className="flex-1 min-h-0 overflow-y-auto p-4">
          <div className="flex gap-2 mb-3">
            <input
              value={todoText}
              onChange={(e) => setTodoText(e.target.value)}
              onKeyDown={async (e) => {
                if (e.key === "Enter" && todoText.trim()) {
                  await createTodo(todoText.trim());
                  setTodoText("");
                  setTodos(await listTodos());
                }
              }}
              placeholder="New todo… (agents + plans add here too)"
              className="flex-1 rounded-lg bg-zinc-900 border border-zinc-700 px-3 py-2 text-sm outline-none focus:border-indigo-500"
            />
            <button
              onClick={async () => {
                await clearTodos();
                setTodos(await listTodos());
              }}
              className="text-xs px-3 rounded bg-zinc-800 hover:bg-zinc-700"
            >
              🧹 Clear done
            </button>
          </div>
          <div className="space-y-1">
            {todos.map((t) => (
              <div key={t.id} className="flex items-center gap-3 rounded-lg bg-zinc-900 border border-zinc-800 px-3 py-2 text-sm">
                <input
                  type="checkbox"
                  checked={t.done}
                  onChange={async () => {
                    await patchTodo(t.id, !t.done);
                    setTodos(await listTodos());
                  }}
                  className="accent-indigo-600"
                />
                <span className={`flex-1 ${t.done ? "line-through text-zinc-500" : ""}`}>{t.text}</span>
                <button onClick={async () => {
                  await deleteTodo(t.id);
                  setTodos(await listTodos());
                }} className="text-xs text-zinc-600 hover:text-red-400">
                  ✕
                </button>
              </div>
            ))}
            {todos.length === 0 && <div className="text-sm text-zinc-600">No todos. Use Agent Plan mode to generate.</div>}
          </div>
        </div>
      )}

      {tab === "workflows" && (
        <div className="flex-1 min-h-0 overflow-y-auto p-4">
          <h3 className="font-bold mb-1">🔁 Reusable workflows</h3>
          <p className="text-xs text-zinc-500 mb-3">Save multi-step agent routines. Steps run sequentially.</p>
          <div className="flex gap-2 mb-2">
            <input
              value={wfName}
              onChange={(e) => setWfName(e.target.value)}
              placeholder="workflow-name"
              className="w-48 rounded-lg bg-zinc-900 border border-zinc-700 px-3 py-2 text-sm outline-none focus:border-indigo-500"
            />
            <select
              value={wfProfile}
              onChange={(e) => setWfProfile(e.target.value)}
              className="rounded-lg bg-zinc-900 border border-zinc-700 px-2 text-sm"
            >
              {profiles.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
            <button
              onClick={async () => {
                const steps = wfSteps.split("\n").map((t) => t.trim()).filter(Boolean);
                if (!wfName.trim() || !steps.length) return;
                try {
                  await saveWorkflow(wfName.trim().toLowerCase(), steps.map((task) => ({ task, profile: wfProfile })));
                  setMsg(`✅ Saved workflow ${wfName.trim().toLowerCase()}`);
                  setWfName("");
                  setWfSteps("");
                  setWorkflows(await listWorkflows());
                } catch (e) {
                  setMsg(e instanceof Error ? e.message : "Save failed");
                }
              }}
              className="px-5 rounded-lg bg-indigo-600 text-sm font-semibold hover:bg-indigo-500"
            >
              💾 Save
            </button>
          </div>
          <textarea
            value={wfSteps}
            onChange={(e) => setWfSteps(e.target.value)}
            placeholder={"One task per line:\nResearch the best cache library\nWrite notes/cache.md with findings\nReview notes/cache.md"}
            rows={4}
            className="w-full rounded-lg bg-zinc-900 border border-zinc-700 px-3 py-2 text-sm outline-none focus:border-indigo-500 mb-4"
          />
          <div className="space-y-2">
            {workflows.map((w) => (
              <div key={w.name} className="rounded-lg bg-zinc-900 border border-zinc-800 p-3 text-sm">
                <div className="flex items-center gap-2 mb-1">
                  <span className="font-mono font-bold">{w.name}</span>
                  <span className="text-xs text-zinc-500">{w.steps.length} steps</span>
                  <span className="flex-1" />
                  <button
                    onClick={async () => {
                      const run = await runWorkflow(w.name, model);
                      setMsg(`▶ Started run ${run.id} (${w.name}) — polling…`);
                      const timer = setInterval(async () => {
                        const r = await getWorkflowRun(run.id);
                        if (r.status === "done" || r.status === "failed") {
                          clearInterval(timer);
                          setMsg(`🏁 ${w.name}: ${r.status} — ${r.results.map((x) => x.summary).join(" / ").slice(0, 200)}`);
                        }
                      }, 2000);
                    }}
                    className="text-xs px-3 py-1.5 rounded bg-emerald-700 hover:bg-emerald-600 font-semibold"
                  >
                    ▶ Run
                  </button>
                  <button
                    onClick={async () => {
                      await deleteWorkflow(w.name);
                      setWorkflows(await listWorkflows());
                    }}
                    className="text-xs text-zinc-600 hover:text-red-400"
                  >
                    ✕
                  </button>
                </div>
                <ol className="text-xs text-zinc-400 list-decimal ml-5">
                  {w.steps.map((s, i) => (
                    <li key={i}>
                      {s.task} <span className="text-zinc-600">({s.profile})</span>
                    </li>
                  ))}
                </ol>
              </div>
            ))}
            {workflows.length === 0 && <div className="text-sm text-zinc-600">No workflows yet.</div>}
          </div>
          {wfRun && <div className="mt-2 text-xs text-zinc-500">{wfRun}</div>}
        </div>
      )}

      {tab === "tools" && (
        <div className="flex-1 min-h-0 overflow-y-auto p-4 space-y-6 text-sm">
          <section>
            <h3 className="font-bold mb-1">⌨️ Slash commands</h3>
            <div className="text-xs text-zinc-500 mb-2">
              {cmds.map((c) => c.name).join(" · ") || "loading…"} — also type <code>/cmd</code> in Chat.
            </div>
            <SlashRunner model={model} onOut={setSlashOut} />
            {slashOut && <pre className="arena-code whitespace-pre-wrap text-xs mt-2 max-h-48 overflow-auto">{slashOut}</pre>}
          </section>
          <section>
            <h3 className="font-bold mb-1">🔌 MCP {mcp && (mcp.installed ? "(installed ✅)" : `(missing — ${mcp.hint})`)}</h3>
            <div className="text-xs text-zinc-500 mb-2">
              {mcp?.servers.length
                ? mcp.servers.map((s) => `${s.id}: ${s.ok ? (s.tools ?? []).join(", ") || "no tools" : s.error}`).join(" · ")
                : "No servers configured. Add under mcp_servers in config.yaml."}
            </div>
            <div className="flex gap-2 mb-2">
              <input value={mcpForm.server} onChange={(e) => setMcpForm({ ...mcpForm, server: e.target.value })} placeholder="server id"
                className="w-32 rounded bg-zinc-900 border border-zinc-700 px-2 py-1.5 text-sm" />
              <input value={mcpForm.tool} onChange={(e) => setMcpForm({ ...mcpForm, tool: e.target.value })} placeholder="tool name"
                className="w-40 rounded bg-zinc-900 border border-zinc-700 px-2 py-1.5 text-sm" />
              <input value={mcpForm.args} onChange={(e) => setMcpForm({ ...mcpForm, args: e.target.value })} placeholder='args JSON'
                className="flex-1 rounded bg-zinc-900 border border-zinc-700 px-2 py-1.5 text-sm font-mono" />
              <button
                onClick={async () => {
                  try {
                    setMcpOut(await mcpCall(mcpForm.server, mcpForm.tool, JSON.parse(mcpForm.args || "{}")));
                  } catch (e) {
                    setMcpOut(e instanceof Error ? e.message : "Call failed");
                  }
                }}
                className="px-4 rounded bg-zinc-800 hover:bg-zinc-700 text-sm"
              >
                Call
              </button>
            </div>
            {mcpOut && <pre className="arena-code whitespace-pre-wrap text-xs max-h-48 overflow-auto">{mcpOut}</pre>}
          </section>
          <section>
            <h3 className="font-bold mb-1">🌐 Web (research tools)</h3>
            <WebTester onOut={setWebOut} />
            {webOut && <pre className="arena-code whitespace-pre-wrap text-xs mt-2 max-h-64 overflow-auto">{webOut}</pre>}
          </section>
        </div>
      )}
    </div>
  );
}

function SlashRunner({ model, onOut }: { model: string; onOut: (s: string) => void }) {
  const [cmd, setCmd] = useState("help");
  const [args, setArgs] = useState("");
  return (
    <div className="flex gap-2">
      <input value={cmd} onChange={(e) => setCmd(e.target.value)} placeholder="command (without /)"
        className="w-40 rounded bg-zinc-900 border border-zinc-700 px-2 py-1.5 text-sm font-mono" />
      <input value={args} onChange={(e) => setArgs(e.target.value)} placeholder="args…"
        className="flex-1 rounded bg-zinc-900 border border-zinc-700 px-2 py-1.5 text-sm" />
      <button
        onClick={async () => {
          try {
            onOut(await slashRun(cmd.replace(/^\//, ""), args, model));
          } catch (e) {
            onOut(e instanceof Error ? e.message : "Run failed");
          }
        }}
        className="px-4 rounded bg-zinc-800 hover:bg-zinc-700"
      >
        Run
      </button>
    </div>
  );
}

function WebTester({ onOut }: { onOut: (s: string) => void }) {
  const [q, setQ] = useState("");
  const [url, setUrl] = useState("");
  return (
    <div className="space-y-2">
      <div className="flex gap-2">
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search the web…"
          className="flex-1 rounded bg-zinc-900 border border-zinc-700 px-2 py-1.5 text-sm" />
        <button
          onClick={async () => {
            try {
              const res = await webSearch(q);
              onOut(res.map((r) => `• ${r.title}\n  ${r.url}\n  ${r.snippet}`).join("\n\n") || "No results.");
            } catch (e) {
              onOut(e instanceof Error ? e.message : "Search failed");
            }
          }}
          className="px-4 rounded bg-zinc-800 hover:bg-zinc-700"
        >
          🔍 Search
        </button>
      </div>
      <div className="flex gap-2">
        <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://… fetch as text"
          className="flex-1 rounded bg-zinc-900 border border-zinc-700 px-2 py-1.5 text-sm" />
        <button
          onClick={async () => {
            try {
              const res = await webFetch(url);
              onOut(`${res.title}\n${res.url}\n\n${res.text.slice(0, 3000)}`);
            } catch (e) {
              onOut(e instanceof Error ? e.message : "Fetch failed");
            }
          }}
          className="px-4 rounded bg-zinc-800 hover:bg-zinc-700"
        >
          📄 Fetch
        </button>
      </div>
    </div>
  );
}
