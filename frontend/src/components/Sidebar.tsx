import { useState } from "react";
import type { ModelEntry, ProviderEntry, UsageSummary } from "../api";
import { deleteKey, saveKey } from "../api";

export interface ModeDef {
  key: string;
  icon: string;
  name: string;
  ready: boolean;
  hint: string;
}

interface Props {
  modes: ModeDef[];
  activeMode: string;
  onModeChange: (key: string) => void;
  models: ModelEntry[];
  currentModel: string;
  onModelChange: (id: string) => void;
  providers: ProviderEntry[];
  onKeysChanged: () => void;
  usage: UsageSummary | null;
  onPalette: () => void;
}

export default function Sidebar({
  modes,
  activeMode,
  onModeChange,
  models,
  currentModel,
  onModelChange,
  providers,
  onKeysChanged,
  usage,
  onPalette,
}: Props) {
  const [keysOpen, setKeysOpen] = useState(false);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const configuredCount = providers.filter((p) => p.configured).length;

  const handleSave = async (provider: string) => {
    const key = (drafts[provider] ?? "").trim();
    if (!key) return;
    setSaving(provider);
    setError(null);
    try {
      await saveKey(provider, key);
      setDrafts((d) => ({ ...d, [provider]: "" }));
      onKeysChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(null);
    }
  };

  const handleDelete = async (provider: string) => {
    setError(null);
    try {
      await deleteKey(provider);
      onKeysChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Delete failed");
    }
  };

  return (
    <aside className="w-72 shrink-0 h-full flex flex-col bg-zinc-950 border-r border-zinc-800">
      <div className="px-5 pt-5 pb-4">
        <div className="text-xl font-extrabold tracking-tight">🏟️ AK Dev Arena</div>
        <div className="text-xs text-zinc-500 mt-0.5">v1.0.0 · Full & Final</div>
      </div>

      <div className="px-3">
        <div className="text-[11px] uppercase tracking-widest text-zinc-500 px-2 mb-1">Modes</div>
        {modes.map((m) => (
          <button
            key={m.key}
            onClick={() => m.ready && onModeChange(m.key)}
            disabled={!m.ready}
            title={m.ready ? m.name : `Coming ${m.hint}`}
            className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg text-[15px] ${
              m.key === activeMode
                ? "bg-indigo-600/25 text-white font-semibold border border-indigo-700"
                : m.ready
                  ? "text-zinc-300 hover:bg-zinc-900"
                  : "text-zinc-600 cursor-not-allowed"
            }`}
          >
            <span className="text-lg">{m.icon}</span>
            <span className="flex-1 text-left">{m.name}</span>
            {!m.ready && (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-zinc-900 border border-zinc-800 text-zinc-500">
                {m.hint}
              </span>
            )}
          </button>
        ))}
        <button
          onClick={onPalette}
          className="w-full mt-2 px-3 py-2 rounded-lg text-sm text-zinc-500 hover:bg-zinc-900 border border-dashed border-zinc-800"
        >
          ⌘K Commands…
        </button>
      </div>

      <div className="px-5 mt-4">
        <div className="text-[11px] uppercase tracking-widest text-zinc-500 mb-1">Model</div>
        <select
          value={currentModel}
          onChange={(e) => onModelChange(e.target.value)}
          className="w-full rounded-lg bg-zinc-900 border border-zinc-700 px-3 py-2 text-sm outline-none focus:border-indigo-500"
        >
          {models.map((m) => (
            <option key={m.id} value={m.id}>
              {m.configured ? "🟢" : "🔴"} {m.label} — {m.best_for}
            </option>
          ))}
        </select>
      </div>

      <div className="flex-1" />

      {usage && (
        <div className="px-5 pb-2 text-[11px] text-zinc-600">
          📊 {usage.totals.calls} calls · {(usage.totals.total / 1000).toFixed(1)}k tokens
        </div>
      )}

      <div className="p-4 border-t border-zinc-800">
        <button
          onClick={() => setKeysOpen((v) => !v)}
          className="w-full rounded-lg bg-zinc-900 border border-zinc-700 px-4 py-2.5 text-sm font-semibold hover:border-indigo-500"
        >
          🔑 Keys ({configuredCount}/{providers.length} ready)
        </button>

        {keysOpen && (
          <div className="mt-3 space-y-3 max-h-64 overflow-y-auto">
            {error && <div className="text-xs text-red-400 bg-red-950/40 border border-red-900 rounded p-2">{error}</div>}
            {providers.map((p) => (
              <div key={p.provider} className="rounded-lg bg-zinc-900 border border-zinc-800 p-3">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-sm font-semibold capitalize">
                    {p.configured ? "🟢" : "🔴"} {p.provider}
                  </span>
                  {p.configured && p.needs_key && (
                    <button onClick={() => handleDelete(p.provider)} className="text-xs text-zinc-500 hover:text-red-400">
                      remove
                    </button>
                  )}
                </div>
                {p.needs_key && !p.configured && (
                  <div className="flex gap-2">
                    <input
                      type="password"
                      value={drafts[p.provider] ?? ""}
                      onChange={(e) => setDrafts((d) => ({ ...d, [p.provider]: e.target.value }))}
                      placeholder={p.env_var ?? "API key"}
                      className="flex-1 min-w-0 rounded bg-zinc-950 border border-zinc-700 px-2 py-1.5 text-xs outline-none focus:border-indigo-500"
                    />
                    <button
                      onClick={() => handleSave(p.provider)}
                      disabled={saving === p.provider}
                      className="text-xs font-semibold px-3 rounded bg-indigo-600 disabled:opacity-40"
                    >
                      {saving === p.provider ? "…" : "Save"}
                    </button>
                  </div>
                )}
                {!p.needs_key && <div className="text-[11px] text-zinc-500">Local — no key needed. Just run `ollama serve`.</div>}
              </div>
            ))}
          </div>
        )}
      </div>
    </aside>
  );
}
