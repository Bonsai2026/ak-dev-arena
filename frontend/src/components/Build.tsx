import { useEffect, useState } from "react";
import { buildFix, buildGenerate, buildList, buildTemplates } from "../api";
import type { BuildInfo, Template } from "../api";

interface Props {
  model: string;
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

  const refresh = async () => {
    try {
      const [t, b] = await Promise.all([buildTemplates(), buildList()]);
      setTemplates(t);
      setBuilds(b);
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "Load failed");
    }
  };

  useEffect(() => {
    refresh();
  }, []);

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
      <p className="text-xs text-zinc-500 mb-4">Prompt-to-project scaffolding under <code>./workspace/builds</code>.</p>
      {msg && <div className="text-sm text-zinc-300 bg-zinc-900 border border-zinc-800 rounded-lg px-4 py-2 mb-4">{msg}</div>}

      <div className="grid grid-cols-3 gap-3 mb-6">
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

      <div className="flex gap-2 mb-8">
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

      <h3 className="font-bold mb-2">📦 Projects ({builds.length})</h3>
      <div className="space-y-1 mb-8">
        {builds.map((b) => (
          <div key={b.name} className="flex items-center gap-3 text-sm rounded-lg bg-zinc-900 border border-zinc-800 px-4 py-2">
            <span className="font-mono font-bold">{b.name}</span>
            <span className="text-zinc-500 text-xs">
              {b.path} · {b.files} files
            </span>
            <button onClick={() => setFixName(b.name)} className="ml-auto text-xs text-indigo-400 hover:underline">
              select for fix ↓
            </button>
          </div>
        ))}
        {builds.length === 0 && <div className="text-sm text-zinc-600">No projects yet.</div>}
      </div>

      <h3 className="font-bold mb-2">🩹 AI Fix Loop</h3>
      <div className="flex gap-2 mb-2">
        <select
          value={fixName}
          onChange={(e) => setFixName(e.target.value)}
          className="rounded-lg bg-zinc-900 border border-zinc-700 px-3 py-2 text-sm"
        >
          <option value="">select project…</option>
          {builds.map((b) => (
            <option key={b.name} value={b.name}>
              {b.name}
            </option>
          ))}
        </select>
        <input
          value={fixError}
          onChange={(e) => setFixError(e.target.value)}
          placeholder="Paste the error message…"
          className="flex-1 rounded-lg bg-zinc-900 border border-zinc-700 px-3 py-2 text-sm outline-none focus:border-indigo-500"
        />
        <button onClick={fix} className="px-6 rounded-lg bg-emerald-700 text-sm font-semibold hover:bg-emerald-600">
          🩹 Fix
        </button>
      </div>
      {fixDiff && <pre className="arena-code whitespace-pre-wrap text-xs">{fixDiff}</pre>}
    </div>
  );
}
