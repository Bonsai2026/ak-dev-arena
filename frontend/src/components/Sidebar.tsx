import { useEffect, useState } from "react";
import type { CustomProvider, InstructionsState, ModelEntry, ModelQuery, ProviderEntry, UsageSummary } from "../api";
import { addCustomProvider, deleteCustomProvider, deleteKey, getCustomProviders, refreshCatalog, saveKey } from "../api";

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
  catalogTotal: number;
  modelQuery: ModelQuery;
  onQueryChange: (q: ModelQuery) => void;
  currentModel: string;
  onModelChange: (id: string) => void;
  providers: ProviderEntry[];
  onKeysChanged: () => void;
  usage: UsageSummary | null;
  onPalette: () => void;
  onOpenInstructions: () => void;
  instructions?: InstructionsState | null;
}

export default function Sidebar({
  modes,
  activeMode,
  onModeChange,
  models,
  catalogTotal,
  modelQuery,
  onQueryChange,
  currentModel,
  onModelChange,
  providers,
  onKeysChanged,
  usage,
  onPalette,
  onOpenInstructions,
  instructions,
}: Props) {
  const [keysOpen, setKeysOpen] = useState(false);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState(modelQuery.search ?? "");
  const [refreshing, setRefreshing] = useState(false);
  const [customs, setCustoms] = useState<CustomProvider[]>([]);
  const [customForm, setCustomForm] = useState({ id: "", name: "", base_url: "", model: "" });
  const [customSaving, setCustomSaving] = useState(false);

  const loadCustoms = async () => {
    try {
      setCustoms(await getCustomProviders());
    } catch {
      /* sidebar must never crash on provider list failure */
    }
  };

  useEffect(() => {
    loadCustoms();
  }, []);

  const configuredCount = providers.filter((p) => p.configured).length;

  // Debounced server-side model search (OpenCode-style).
  useEffect(() => {
    const t = setTimeout(() => {
      if (draft !== (modelQuery.search ?? "")) onQueryChange({ ...modelQuery, search: draft });
    }, 400);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draft]);

  // Auto-pick first visible model when the current one is filtered out.
  useEffect(() => {
    if (models.length > 0 && !models.some((m) => m.id === currentModel)) {
      onModelChange(models[0].id);
    }
  }, [models, currentModel, onModelChange]);

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

  const handleRefresh = async () => {
    setRefreshing(true);
    try {
      await refreshCatalog();
      onKeysChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Refresh failed");
    } finally {
      setRefreshing(false);
    }
  };

  const handleAddCustom = async () => {
    if (!customForm.id.trim() || !customForm.base_url.trim()) return;
    setCustomSaving(true);
    setError(null);
    try {
      await addCustomProvider(customForm);
      setCustomForm({ id: "", name: "", base_url: "", model: "" });
      await loadCustoms();
      onKeysChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Add failed");
    } finally {
      setCustomSaving(false);
    }
  };

  const handleDeleteCustom = async (id: string) => {
    setError(null);
    try {
      await deleteCustomProvider(id);
      await loadCustoms();
      onKeysChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Delete failed");
    }
  };

  return (
    <aside className="w-72 shrink-0 h-full flex flex-col bg-zinc-950 border-r border-zinc-800">
      <div className="px-5 pt-5 pb-4">
        <div className="text-xl font-extrabold tracking-tight">🏟️ AK Dev Arena</div>
        <div className="text-xs text-zinc-500 mt-0.5">v1.2.0 · {providers.length} providers</div>
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

      <div className="px-5 mt-4 space-y-2">
        <div className="flex items-center justify-between">
          <div className="text-[11px] uppercase tracking-widest text-zinc-500">Model</div>
          <button onClick={handleRefresh} title="Re-fetch models.dev registry" className="text-xs text-zinc-500 hover:text-indigo-400">
            {refreshing ? "…" : "⟳ update"}
          </button>
        </div>
        <select
          value={modelQuery.provider ?? ""}
          onChange={(e) => onQueryChange({ ...modelQuery, provider: e.target.value || undefined })}
          className="w-full rounded-lg bg-zinc-900 border border-zinc-700 px-3 py-2 text-sm outline-none focus:border-indigo-500"
        >
          <option value="">All providers ({providers.length})</option>
          {providers.map((p) => (
            <option key={p.provider} value={p.provider}>
              {p.configured ? "🟢" : "⚪"} {p.name ?? p.provider} ({p.models ?? 0}
              {(p.free_models ?? 0) > 0 ? `, ${p.free_models} free` : ""})
            </option>
          ))}
        </select>
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={`Search ${(catalogTotal || 7500).toLocaleString()}+ models…`}
          className="w-full rounded-lg bg-zinc-900 border border-zinc-700 px-3 py-2 text-sm outline-none focus:border-indigo-500 placeholder:text-zinc-600"
        />
        <label className="flex items-center gap-2 text-xs text-zinc-400 cursor-pointer">
          <input
            type="checkbox"
            checked={modelQuery.free_only ?? false}
            onChange={(e) => onQueryChange({ ...modelQuery, free_only: e.target.checked || undefined })}
            className="accent-indigo-600"
          />
          🆓 Free models only
        </label>
        <select
          value={models.some((m) => m.id === currentModel) ? currentModel : ""}
          onChange={(e) => onModelChange(e.target.value)}
          className="w-full rounded-lg bg-zinc-900 border border-zinc-700 px-3 py-2 text-sm outline-none focus:border-indigo-500"
        >
          {models.length === 0 && <option value="">No models match.</option>}
          {models.map((m) => (
            <option key={m.id} value={m.id}>
              {m.configured ? "🟢" : "🔴"} {m.free ? "🆓" : "💰"} {m.label} — {m.provider}
            </option>
          ))}
        </select>
        <div className="text-[11px] text-zinc-600">
          {models.length} shown · {(catalogTotal || 0).toLocaleString()} total in catalog
        </div>
      </div>

      <div className="flex-1" />

      {usage && (
        <div className="px-5 pb-2 text-[11px] text-zinc-600">
          📊 {usage.totals.calls} calls · {(usage.totals.total / 1000).toFixed(1)}k tokens
          {usage.totals.cost > 0 && <> · ~${usage.totals.cost.toFixed(3)} (est.)</>}
        </div>
      )}

      <div className="p-4 border-t border-zinc-800 space-y-2">
        <button
          onClick={onOpenInstructions}
          className="flex items-center justify-between w-full rounded-lg bg-zinc-900 border border-zinc-700 px-4 py-2.5 text-sm font-semibold hover:border-indigo-500"
        >
          <span>📋 Instructions</span>
          <span className={`text-[11px] font-normal ${instructions?.global_found || instructions?.project_found ? "text-emerald-400" : "text-zinc-600"}`}>
            {instructions?.global_found || instructions?.project_found ? "on" : "off"}
          </span>
        </button>
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
                <div className="flex items-center justify-between mb-1">
                  <span className="text-sm font-semibold capitalize">
                    {p.configured ? "🟢" : "🔴"} {p.name ?? p.provider}
                  </span>
                  {p.configured && p.needs_key && (
                    <button onClick={() => handleDelete(p.provider)} className="text-xs text-zinc-500 hover:text-red-400">
                      remove
                    </button>
                  )}
                </div>
                <div className="text-[11px] text-zinc-600 mb-2">
                  {p.models ?? 0} models{(p.free_models ?? 0) > 0 ? ` · ${p.free_models} free` : ""}
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

            {/* custom OpenAI-compatible providers (saved locally, keys via
                ARENA_CUSTOM_<ID>_KEY — never uploaded) */}
            <div className="rounded-lg bg-zinc-900 border border-zinc-800 p-3">
              <div className="text-sm font-semibold mb-2">🔌 Custom provider</div>
              {customs.map((c) => (
                <div key={c.id} className="flex items-center gap-2 text-xs mb-1.5">
                  <span className="font-mono text-emerald-400">{c.id}</span>
                  <span className="text-zinc-500 truncate flex-1">{c.base_url}</span>
                  <button onClick={() => handleDeleteCustom(c.id)} className="text-zinc-600 hover:text-red-400">✕</button>
                </div>
              ))}
              {customs.length === 0 && (
                <div className="text-[11px] text-zinc-600 mb-2">Any OpenAI-compatible endpoint (OpenRouter, OpenCode, local llm…)</div>
              )}
              <input
                value={customForm.id}
                onChange={(e) => setCustomForm({ ...customForm, id: e.target.value })}
                placeholder="id (myai)"
                className="w-full rounded bg-zinc-950 border border-zinc-700 px-2 py-1.5 text-xs mb-1.5 outline-none focus:border-indigo-500"
              />
              <input
                value={customForm.base_url}
                onChange={(e) => setCustomForm({ ...customForm, base_url: e.target.value })}
                placeholder="https://api.myai.dev/v1"
                className="w-full rounded bg-zinc-950 border border-zinc-700 px-2 py-1.5 text-xs mb-1.5 outline-none focus:border-indigo-500"
              />
              <input
                value={customForm.model}
                onChange={(e) => setCustomForm({ ...customForm, model: e.target.value })}
                placeholder="default model (optional)"
                className="w-full rounded bg-zinc-950 border border-zinc-700 px-2 py-1.5 text-xs mb-1.5 outline-none focus:border-indigo-500"
              />
              <button
                onClick={handleAddCustom}
                disabled={customSaving || !customForm.id.trim() || !customForm.base_url.trim()}
                className="w-full text-xs font-semibold py-1.5 rounded bg-indigo-700 disabled:opacity-40 hover:bg-indigo-600"
              >
                {customSaving ? "saving…" : "+ Add provider"}
              </button>
              <div className="text-[10px] text-zinc-600 mt-2">
                Key: set env <code>ARENA_CUSTOM_{customForm.id || "ID"}_KEY</code> — or use any provider key above.
              </div>
            </div>
          </div>
        )}
      </div>
    </aside>
  );
}
