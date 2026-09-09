import { useEffect, useState } from "react";
import {
  deleteProjectRules,
  getInstructions,
  saveGlobalInstructions,
  saveProjectRules,
  type InstructionsState,
} from "../api";

interface Props {
  open: boolean;
  onClose: () => void;
  onSaved?: (state: InstructionsState) => void;
}

const GLOBAL_PLACEHOLDER = `How should Arena behave everywhere?

Example:
- Always answer in the user's language.
- When showing code, keep explanations short.
- Never invent file paths.`;

const PROJECT_PLACEHOLDER = `Project rules for ./workspace (like Cursor .cursorrules / Claude CLAUDE.md).

Example:
- Use TypeScript strict mode.
- Python: type hints + 88-char lines.
- Run \`pytest backend/tests -q\` before declaring a task done.
- Never delete user files without asking.`;

export default function Instructions({ open, onClose, onSaved }: Props) {
  const [state, setState] = useState<InstructionsState | null>(null);
  const [global, setGlobal] = useState("");
  const [project, setProject] = useState("");
  const [saving, setSaving] = useState<"global" | "project" | null>(null);
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    if (!open) return;
    setMsg("");
    setError("");
    getInstructions()
      .then((s) => {
        setState(s);
        setGlobal(s.global);
        setProject(s.project);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load instructions"));
  }, [open]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    if (open) window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  const save = async (kind: "global" | "project") => {
    setSaving(kind);
    setError("");
    setMsg("");
    try {
      const next =
        kind === "global"
          ? await saveGlobalInstructions(global)
          : await saveProjectRules(project);
      setState(next);
      setMsg(kind === "global" ? "✅ Global instructions saved — active in all modes." : "✅ Project rules saved to .akrules.");
      onSaved?.(next);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(null);
    }
  };

  const clearProject = async () => {
    setSaving("project");
    setError("");
    setMsg("");
    try {
      const next = await deleteProjectRules();
      setState(next);
      setProject("");
      setMsg("🗑️ Project rules removed.");
      onSaved?.(next);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Delete failed");
    } finally {
      setSaving(null);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" onClick={onClose}>
      <div
        className="w-full max-w-2xl max-h-[85vh] flex flex-col rounded-2xl bg-zinc-950 border border-zinc-800 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-3 px-6 py-4 border-b border-zinc-800">
          <div className="text-2xl">📋</div>
          <div className="flex-1">
            <h2 className="font-bold text-lg">Chat Instructions</h2>
            <p className="text-xs text-zinc-500">
              Like Cursor rules · Claude CLAUDE.md · Codex AGENTS.md — auto-injected into Chat, Agent, Code, Build & Review.
            </p>
          </div>
          <button onClick={onClose} className="text-zinc-500 hover:text-zinc-300 text-xl leading-none">✕</button>
        </div>

        <div className="flex-1 min-h-0 overflow-y-auto px-6 py-5 space-y-6">
          {error && <div className="text-sm text-red-400 bg-red-950/40 border border-red-900 rounded-lg p-3">{error}</div>}
          {msg && <div className="text-sm text-emerald-400 bg-emerald-950/40 border border-emerald-900 rounded-lg p-3">{msg}</div>}

          <section>
            <div className="flex items-center justify-between mb-1">
              <h3 className="text-sm font-semibold">
                🌍 Global instructions
                <span className="ml-2 text-[11px] font-normal text-zinc-500">
                  {state?.global_found ? "🟢 active — all modes" : "⚪ not set"}
                </span>
              </h3>
              <button
                onClick={() => save("global")}
                disabled={saving !== null}
                className="text-xs font-semibold px-4 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40"
              >
                {saving === "global" ? "…" : "💾 Save"}
              </button>
            </div>
            <p className="text-[11px] text-zinc-600 mb-2">Applies everywhere, on every machine where you run Arena. Stored locally, never in git.</p>
            <textarea
              value={global}
              onChange={(e) => setGlobal(e.target.value)}
              placeholder={GLOBAL_PLACEHOLDER}
              rows={6}
              className="w-full rounded-lg bg-zinc-900 border border-zinc-700 px-3 py-2.5 text-sm outline-none focus:border-indigo-500 placeholder:text-zinc-700 resize-y"
            />
          </section>

          <section>
            <div className="flex items-center justify-between mb-1">
              <h3 className="text-sm font-semibold">
                🗂️ Project rules <code className="text-[11px] text-zinc-500 font-normal">.akrules</code>
                <span className="ml-2 text-[11px] font-normal text-zinc-500">
                  {state?.project_found ? "🟢 active — this workspace" : "⚪ not set"}
                </span>
              </h3>
              <div className="flex gap-2">
                {state?.project_found && (
                  <button
                    onClick={clearProject}
                    disabled={saving !== null}
                    className="text-xs px-3 py-1.5 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-zinc-400 disabled:opacity-40"
                  >
                    🗑️ Clear
                  </button>
                )}
                <button
                  onClick={() => save("project")}
                  disabled={saving !== null}
                  className="text-xs font-semibold px-4 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40"
                >
                  {saving === "project" ? "…" : "💾 Save"}
                </button>
              </div>
            </div>
            <p className="text-[11px] text-zinc-600 mb-2">Saved as <code>.akrules</code> in <code>./workspace</code> — this project's rules for every model.</p>
            <textarea
              value={project}
              onChange={(e) => setProject(e.target.value)}
              placeholder={PROJECT_PLACEHOLDER}
              rows={7}
              className="w-full rounded-lg bg-zinc-900 border border-zinc-700 px-3 py-2.5 text-sm outline-none focus:border-indigo-500 placeholder:text-zinc-700 resize-y"
            />
          </section>

          <div className="rounded-lg bg-zinc-900 border border-zinc-800 p-3 text-[11px] text-zinc-500">
            💡 <span className="text-zinc-400">Tip:</span> in Chat you can also <code>@mentions</code> files, folders or <code>@codebase</code> for instant context.
          </div>
        </div>

        <div className="px-6 py-3 border-t border-zinc-800 text-[11px] text-zinc-600">
          Instructions are prompt text only — never API keys. Keys live in the 🔑 Vault.
        </div>
      </div>
    </div>
  );
}
