import { useCallback, useEffect, useRef, useState } from "react";
import {
  composerApply,
  composerPreview,
  completeCode,
  getRules,
  gitCheckpoint,
  gitStatus,
  gitUndo,
  listFiles,
  previewEdit,
  readFile,
  repomap,
  searchFiles,
  writeFile,
} from "../api";
import type { ComposerPatchView, FileEntry, GitStatus, SearchHit } from "../api";

interface Props {
  model: string;
}

export default function Code({ model }: Props) {
  const [tab, setTab] = useState<"editor" | "composer">("editor");
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
  const [rulesFound, setRulesFound] = useState(false);
  const [completing, setCompleting] = useState(false);
  // composer
  const [instructions, setInstructions] = useState("");
  const [patches, setPatches] = useState<ComposerPatchView[]>([]);
  const [patchTexts, setPatchTexts] = useState<Record<string, { old_text: string; new_text: string }>>({});
  const [composing, setComposing] = useState(false);
  const editorRef = useRef<HTMLTextAreaElement>(null);

  const refresh = useCallback(async () => {
    try {
      const [ents, status, rules] = await Promise.all([listFiles(dir), gitStatus(), getRules()]);
      setEntries(ents);
      setGit(status);
      setRulesFound(rules.found);
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

  const doMap = async () => {
    try {
      const res = await repomap(dir);
      setDiff(`🗺 Repo map [engine: ${res.engine}]\n\n${res.map}`);
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "Map failed");
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

  const doTabComplete = async () => {
    const el = editorRef.current;
    if (!el || !file || completing) return;
    const pos = el.selectionStart ?? content.length;
    setCompleting(true);
    try {
      const suggestion = await completeCode(file, content.slice(0, pos), content.slice(pos), model);
      if (suggestion) {
        const next = content.slice(0, pos) + suggestion + content.slice(pos);
        setContent(next);
        requestAnimationFrame(() => {
          el.focus();
          el.selectionStart = el.selectionEnd = pos + suggestion.length;
        });
      } else {
        setMsg("No suggestion.");
      }
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "Complete failed");
    } finally {
      setCompleting(false);
    }
  };

  const doCompose = async () => {
    if (!instructions.trim() || composing) return;
    setComposing(true);
    setMsg("");
    try {
      const res = await composerPreview(instructions.trim(), model);
      setPatches(res);
      const texts: Record<string, { old_text: string; new_text: string }> = {};
      res.forEach((p) => {
        if (p.ok) texts[p.path] = { old_text: p.old_text ?? "", new_text: p.new_text ?? "" };
      });
      setPatchTexts(texts);
      setMsg(res.length ? `Got ${res.length} patch(es). Review → Apply.` : "No patches proposed.");
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "Composer failed");
    } finally {
      setComposing(false);
    }
  };

  const doApplyPatches = async () => {
    const ok = patches.filter((p) => p.ok);
    if (!ok.length) return;
    // Re-fetch full patch texts for apply: ask preview again is wasteful, so store on preview.
    const payload = ok.map((p) => ({ path: p.path, ...(patchTexts[p.path] ?? { old_text: "", new_text: "" }) }));
    if (payload.some((x) => !x.path || (x.old_text === "" && x.new_text === ""))) {
      setMsg("Patch texts missing — preview again, then apply.");
      return;
    }
    try {
      const res = await composerApply(payload);
      setMsg(`✅ Applied: ${(res.applied ?? []).join(", ") || "none"}` +
        (res.failed?.length ? ` · Failed: ${res.failed.map((f: { path: string }) => f.path).join(", ")}` : "") +
        (res.checkpoint ? ` · Checkpoint ${res.checkpoint}` : ""));
      setPatches([]);
      if (file) openFile(file);
      refresh();
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "Apply failed");
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

      {/* right: editor / composer */}
      <div className="flex-1 min-w-0 flex flex-col">
        <div className="flex items-center gap-2 px-4 py-2 border-b border-zinc-800 text-sm">
          <button
            onClick={() => setTab("editor")}
            className={`px-3 py-1.5 rounded ${tab === "editor" ? "bg-zinc-800 font-semibold" : "text-zinc-500"}`}
          >
            ⌨️ Editor
          </button>
          <button
            onClick={() => setTab("composer")}
            className={`px-3 py-1.5 rounded ${tab === "composer" ? "bg-zinc-800 font-semibold" : "text-zinc-500"}`}
          >
            🎼 Composer
          </button>
          <span className="flex-1" />
          <span className="text-xs text-zinc-500" title=".akrules project rules (Cursor-style)">
            {rulesFound ? "🛡 rules on" : "🛡 no .akrules"}
          </span>
        </div>

        {msg && <div className="px-4 py-1.5 text-xs text-zinc-400 border-b border-zinc-800">{msg}</div>}

        {tab === "editor" ? (
          <>
            <div className="flex items-center gap-2 px-4 py-2 border-b border-zinc-800 text-sm">
              <span className="flex-1 truncate text-zinc-300">{file || "No file open — pick one from the tree."}</span>
              {file && content !== original && <span className="text-xs text-amber-400">● unsaved</span>}
              <button
                onClick={doMap}
                className="text-xs px-3 py-1.5 rounded bg-zinc-800 hover:bg-zinc-700"
                title="Repo map (Aider engine or fallback)"
              >
                🗺 Map
              </button>
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
            {file ? (
              <>
                <textarea
                  ref={editorRef}
                  value={content}
                  onChange={(e) => setContent(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Tab") {
                      e.preventDefault();
                      doTabComplete();
                    }
                  }}
                  spellCheck={false}
                  placeholder="Type code… press Tab for AI completion."
                  className="flex-1 min-h-0 bg-zinc-950 text-[13px] leading-relaxed p-4 outline-none resize-none"
                  style={{ fontFamily: "ui-monospace, 'JetBrains Mono', Menlo, monospace" }}
                />
                {completing && <div className="px-4 py-1 text-xs text-indigo-400 animate-pulse">✨ completing…</div>}
                {diff !== null && (
                  <div className="h-48 shrink-0 border-t border-zinc-800 overflow-auto p-3">
                    <div className="text-[11px] uppercase tracking-widest text-zinc-500 mb-1">Diff / Map</div>
                    <pre className="arena-code whitespace-pre-wrap">{diff || "(empty)"}</pre>
                  </div>
                )}
              </>
            ) : (
              <div className="flex-1 flex items-center justify-center text-zinc-600 text-sm">
                ⌨️ Code Mode — files live in <code className="mx-1 text-zinc-400">./workspace</code> · Tab = AI complete
              </div>
            )}
          </>
        ) : (
          <div className="flex-1 min-h-0 overflow-y-auto p-4">
            <h3 className="font-bold mb-1">🎼 Composer (Cursor-style multi-file edits)</h3>
            <p className="text-xs text-zinc-500 mb-3">Describe a change — AI proposes patches across files. You review, then apply.</p>
            <div className="flex gap-2 mb-3">
              <input
                value={instructions}
                onChange={(e) => setInstructions(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && doCompose()}
                placeholder="e.g. Add a dark-mode toggle to the settings page"
                className="flex-1 rounded-lg bg-zinc-900 border border-zinc-700 px-3 py-2 text-sm outline-none focus:border-indigo-500"
              />
              <button
                onClick={doCompose}
                disabled={composing || !instructions.trim()}
                className="px-5 rounded-lg bg-indigo-600 text-sm font-semibold disabled:opacity-40 hover:bg-indigo-500"
              >
                {composing ? "…" : "Preview"}
              </button>
            </div>
            {patches.length > 0 && (
              <>
                <button
                  onClick={doApplyPatches}
                  className="mb-3 px-5 py-2 rounded-lg bg-emerald-700 text-sm font-semibold hover:bg-emerald-600"
                >
                  ✅ Apply {patches.filter((p) => p.ok).length} patch(es) + checkpoint
                </button>
                <div className="space-y-3">
                  {patches.map((p, i) => (
                    <div key={i} className="rounded-lg bg-zinc-900 border border-zinc-800 p-3">
                      <div className="font-mono text-sm mb-1">
                        {p.ok ? "✅" : "❌"} {p.path}
                      </div>
                      {p.ok ? (
                        <>
                          <pre className="arena-code whitespace-pre-wrap text-xs max-h-48 overflow-auto">{p.diff}</pre>
                          <details className="mt-2 text-xs">
                            <summary className="cursor-pointer text-zinc-500">Edit texts (advanced)</summary>
                            <textarea
                              placeholder="old_text (exact)"
                              onChange={(e) =>
                                setPatchTexts((t) => ({
                                  ...t,
                                  [p.path]: { old_text: e.target.value, new_text: t[p.path]?.new_text ?? "" },
                                }))
                              }
                              className="w-full mt-1 rounded bg-zinc-950 border border-zinc-700 p-2 font-mono text-xs"
                              rows={3}
                            />
                            <textarea
                              placeholder="new_text"
                              onChange={(e) =>
                                setPatchTexts((t) => ({
                                  ...t,
                                  [p.path]: { old_text: t[p.path]?.old_text ?? "", new_text: e.target.value },
                                }))
                              }
                              className="w-full mt-1 rounded bg-zinc-950 border border-zinc-700 p-2 font-mono text-xs"
                              rows={3}
                            />
                          </details>
                        </>
                      ) : (
                        <div className="text-xs text-red-400">{p.error}</div>
                      )}
                    </div>
                  ))}
                </div>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
