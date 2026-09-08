import { useCallback, useEffect, useState } from "react";
import {
  gitCheckpoint,
  gitStatus,
  gitUndo,
  listFiles,
  previewEdit,
  readFile,
  searchFiles,
  writeFile,
} from "../api";
import type { FileEntry, GitStatus, SearchHit } from "../api";

export default function Code() {
  const [dir, setDir] = useState("");
  const [entries, setEntries] = useState<FileEntry[]>([]);
  const [file, setFile] = useState("");
  const [original, setOriginal] = useState("");
  const [content, setContent] = useState("");
  const [diff, setDiff] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<SearchHit[]>([]);
  const [git, setGit] = useState<GitStatus | null>(null);
  const [msg, setMsg] = useState("");

  const refresh = useCallback(async () => {
    try {
      const [ents, status] = await Promise.all([listFiles(dir), gitStatus()]);
      setEntries(ents);
      setGit(status);
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "Load failed");
    }
  }, [dir]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const openFile = async (path: string) => {
    try {
      const res = await readFile(path);
      setFile(res.path);
      setOriginal(res.content);
      setContent(res.content);
      setDiff(null);
      setMsg("");
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "Open failed");
    }
  };

  const doSave = async () => {
    if (!file) return;
    try {
      await writeFile(file, content);
      setOriginal(content);
      setDiff(null);
      setMsg(`✅ Saved ${file}`);
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "Save failed");
    }
  };

  const doPreview = async () => {
    if (!file) return;
    if (content === original) {
      setDiff("No changes.");
      return;
    }
    try {
      setDiff(await previewEdit(file, original, content));
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "Preview failed");
    }
  };

  const doSearch = async () => {
    if (!query.trim()) return;
    try {
      setHits(await searchFiles(query.trim()));
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "Search failed");
    }
  };

  const crumbs = dir ? dir.split("/") : [];

  return (
    <div className="h-full flex">
      {/* left: tree + search + git */}
      <div className="w-80 shrink-0 border-r border-zinc-800 flex flex-col">
        <div className="p-3 border-b border-zinc-800">
          <div className="flex items-center gap-1 text-sm mb-2 flex-wrap">
            <button onClick={() => setDir("")} className="text-indigo-400 hover:underline">
              workspace
            </button>
            {crumbs.map((c, i) => (
              <span key={i} className="flex items-center gap-1">
                <span className="text-zinc-600">/</span>
                <button
                  onClick={() => setDir(crumbs.slice(0, i + 1).join("/"))}
                  className="text-indigo-400 hover:underline"
                >
                  {c}
                </button>
              </span>
            ))}
          </div>
          <div className="flex-1 overflow-y-auto max-h-56 space-y-0.5">
            {entries.map((e) => (
              <button
                key={e.path}
                onClick={() => (e.type === "dir" ? setDir(e.path) : openFile(e.path))}
                className={`w-full text-left px-2 py-1 rounded text-sm truncate ${
                  e.path === file ? "bg-indigo-600/30 text-white" : "hover:bg-zinc-900 text-zinc-300"
                }`}
              >
                {e.type === "dir" ? "📁" : "📄"} {e.name}
              </button>
            ))}
            {entries.length === 0 && <div className="text-xs text-zinc-600 px-2">Empty folder.</div>}
          </div>
        </div>

        <div className="p-3 border-b border-zinc-800">
          <div className="flex gap-2">
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && doSearch()}
              placeholder="Search workspace…"
              className="flex-1 min-w-0 rounded bg-zinc-900 border border-zinc-700 px-2 py-1.5 text-sm outline-none focus:border-indigo-500"
            />
            <button onClick={doSearch} className="text-sm px-3 rounded bg-zinc-800 hover:bg-zinc-700">
              🔍
            </button>
          </div>
          <div className="mt-2 space-y-1 max-h-32 overflow-y-auto">
            {hits.map((h, i) => (
              <button
                key={i}
                onClick={() => openFile(h.path)}
                className="w-full text-left text-xs px-2 py-1 rounded hover:bg-zinc-900 truncate"
              >
                <span className="text-indigo-400">{h.path}:{h.line}</span>{" "}
                <span className="text-zinc-400">{h.text}</span>
              </button>
            ))}
          </div>
        </div>

        <div className="p-3 mt-auto border-t border-zinc-800 text-sm">
          <div className="flex items-center justify-between mb-2">
            <span className="font-semibold">⎇ Git</span>
            <span className="text-xs text-zinc-500">
              {git ? (git.is_repo ? `${git.branch} · ${git.clean ? "clean ✅" : "dirty ●"}` : "not a repo") : "…"}
            </span>
          </div>
          <div className="flex gap-2">
            <button
              onClick={async () => {
                const m = window.prompt("Checkpoint message:", "arena: checkpoint") ?? "arena: checkpoint";
                try {
                  const r = await gitCheckpoint(m);
                  setMsg(r.hash ? `✅ Checkpoint ${r.hash}` : r.message);
                  refresh();
                } catch (e) {
                  setMsg(e instanceof Error ? e.message : "Checkpoint failed");
                }
              }}
              className="flex-1 text-xs px-2 py-1.5 rounded bg-zinc-800 hover:bg-zinc-700"
            >
              📸 Checkpoint
            </button>
            <button
              onClick={async () => {
                if (!window.confirm("Undo last Arena checkpoint?")) return;
                try {
                  const r = await gitUndo();
                  setMsg(`↩️ Undone: ${r.reverted}`);
                  if (file) openFile(file);
                  refresh();
                } catch (e) {
                  setMsg(e instanceof Error ? e.message : "Undo failed");
                }
              }}
              className="flex-1 text-xs px-2 py-1.5 rounded bg-zinc-800 hover:bg-zinc-700"
            >
              ↩️ Undo
            </button>
          </div>
        </div>
      </div>

      {/* right: editor */}
      <div className="flex-1 min-w-0 flex flex-col">
        <div className="flex items-center gap-2 px-4 py-2.5 border-b border-zinc-800 text-sm">
          <span className="flex-1 truncate text-zinc-300">{file || "No file open — pick one from the tree."}</span>
          {file && content !== original && <span className="text-xs text-amber-400">● unsaved</span>}
          <button
            onClick={doPreview}
            disabled={!file}
            className="text-xs px-3 py-1.5 rounded bg-zinc-800 hover:bg-zinc-700 disabled:opacity-40"
          >
            👁️ Diff
          </button>
          <button
            onClick={doSave}
            disabled={!file}
            className="text-xs px-4 py-1.5 rounded bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 font-semibold"
          >
            💾 Save
          </button>
        </div>
        {msg && <div className="px-4 py-1.5 text-xs text-zinc-400 border-b border-zinc-800">{msg}</div>}
        {file ? (
          <>
            <textarea
              value={content}
              onChange={(e) => setContent(e.target.value)}
              spellCheck={false}
              className="flex-1 min-h-0 bg-zinc-950 text-[13px] leading-relaxed font-mono p-4 outline-none resize-none"
              style={{ fontFamily: "ui-monospace, 'JetBrains Mono', Menlo, monospace" }}
            />
            {diff !== null && (
              <div className="h-48 shrink-0 border-t border-zinc-800 overflow-auto p-3">
                <div className="text-[11px] uppercase tracking-widest text-zinc-500 mb-1">Diff preview</div>
                <pre className="arena-code whitespace-pre-wrap">{diff || "(empty)"}</pre>
              </div>
            )}
          </>
        ) : (
          <div className="flex-1 flex items-center justify-center text-zinc-600 text-sm">
            ⌨️ Code Mode — files live in <code className="mx-1 text-zinc-400">./workspace</code>
          </div>
        )}
      </div>
    </div>
  );
}
