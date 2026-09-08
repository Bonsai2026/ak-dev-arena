import { useCallback, useEffect, useMemo, useState } from "react";
import Sidebar, { type ModeDef } from "./components/Sidebar";
import Chat from "./components/Chat";
import Code from "./components/Code";
import Agent from "./components/Agent";
import Manager from "./components/Manager";
import Build from "./components/Build";
import Review from "./components/Review";
import Voice from "./components/Voice";
import Palette, { type PaletteAction } from "./components/Palette";
import { getModels, getProviders, getUsage, streamChat } from "./api";
import type { ChatMessage, ModelEntry, ProviderEntry, UsageSummary } from "./api";

const MODES: ModeDef[] = [
  { key: "chat", icon: "💬", name: "Chat", ready: true, hint: "" },
  { key: "code", icon: "⌨️", name: "Code", ready: true, hint: "" },
  { key: "agent", icon: "🤖", name: "Agent", ready: true, hint: "" },
  { key: "manager", icon: "👁️", name: "Manager", ready: true, hint: "" },
  { key: "build", icon: "🏗️", name: "Build", ready: true, hint: "" },
  { key: "review", icon: "🔍", name: "Review", ready: true, hint: "" },
  { key: "voice", icon: "🎙️", name: "Voice", ready: true, hint: "" },
];

export default function App() {
  const [mode, setMode] = useState("chat");
  const [models, setModels] = useState<ModelEntry[]>([]);
  const [providers, setProviders] = useState<ProviderEntry[]>([]);
  const [currentModel, setCurrentModel] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [backendUp, setBackendUp] = useState<boolean | null>(null);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [usage, setUsage] = useState<UsageSummary | null>(null);

  const refreshCatalog = useCallback(async () => {
    try {
      const [{ models: ms, defaults }, { providers: ps }] = await Promise.all([getModels(), getProviders()]);
      setModels(ms);
      setProviders(ps);
      setBackendUp(true);
      setCurrentModel((cur) => cur || defaults.chat || ms[0]?.id || "");
    } catch {
      setBackendUp(false);
    }
  }, []);

  const refreshUsage = useCallback(async () => {
    try {
      setUsage(await getUsage());
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    refreshCatalog();
    refreshUsage();
  }, [refreshCatalog, refreshUsage]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPaletteOpen((v) => !v);
      }
      if (e.key === "Escape") setPaletteOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const activeEntry = useMemo(() => models.find((m) => m.id === currentModel), [models, currentModel]);
  const ready = backendUp === true && (activeEntry?.configured ?? false);

  const handleSend = async (text: string) => {
    if (!ready || streaming) return;
    const next: ChatMessage[] = [...messages, { role: "user" as const, content: text }];
    setMessages([...next, { role: "assistant" as const, content: "" }]);
    setStreaming(true);
    let acc = "";
    try {
      await streamChat(currentModel, next, (token) => {
        acc += token;
        const snapshot = acc;
        setMessages((prev) => {
          const copy = [...prev];
          copy[copy.length - 1] = { role: "assistant", content: snapshot };
          return copy;
        });
      });
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Request failed";
      setMessages((prev) => {
        const copy = [...prev];
        copy[copy.length - 1] = { role: "assistant", content: `⚠️ ${msg}` };
        return copy;
      });
    } finally {
      setStreaming(false);
      refreshUsage();
    }
  };

  const handleTranscript = (text: string) => {
    setMode("chat");
    handleSend(text);
  };

  const lastAssistant = useMemo(
    () => [...messages].reverse().find((m) => m.role === "assistant")?.content ?? "",
    [messages]
  );

  const paletteActions: PaletteAction[] = useMemo(
    () => [
      ...MODES.filter((m) => m.ready).map((m) => ({
        label: `${m.icon} Go to ${m.name}`,
        hint: "mode",
        run: () => setMode(m.key),
      })),
      { label: "🧹 Clear chat", hint: "chat", run: () => setMessages([]) },
      { label: "🔄 Refresh models & keys", hint: "catalog", run: () => refreshCatalog() },
      { label: "📊 Refresh usage", hint: "usage", run: () => refreshUsage() },
    ],
    [refreshCatalog, refreshUsage]
  );

  if (backendUp === false) {
    return (
      <div className="h-full flex flex-col items-center justify-center gap-3 text-center px-6">
        <div className="text-5xl">🔌</div>
        <h1 className="text-xl font-bold">Backend not reachable</h1>
        <p className="text-zinc-400 max-w-md text-sm">
          Start the Python sidecar first:
          <br />
          <code className="text-indigo-300">python -m uvicorn backend.app.main:app --port 8000</code>
        </p>
        <button onClick={refreshCatalog} className="mt-2 px-5 py-2 rounded-lg bg-indigo-600 text-sm font-semibold">
          Retry
        </button>
      </div>
    );
  }

  return (
    <div className="h-full flex">
      <Sidebar
        modes={MODES}
        activeMode={mode}
        onModeChange={setMode}
        models={models}
        currentModel={currentModel}
        onModelChange={setCurrentModel}
        providers={providers}
        onKeysChanged={() => {
          refreshCatalog();
          refreshUsage();
        }}
        usage={usage}
        onPalette={() => setPaletteOpen(true)}
      />
      <main className="flex-1 min-w-0 h-full">
        {mode === "chat" && <Chat messages={messages} streaming={streaming} ready={ready} onSend={handleSend} />}
        {mode === "code" && <Code />}
        {mode === "agent" && <Agent model={currentModel} />}
        {mode === "manager" && <Manager model={currentModel} />}
        {mode === "build" && <Build model={currentModel} />}
        {mode === "review" && <Review model={currentModel} />}
        {mode === "voice" && <Voice onTranscript={handleTranscript} lastAssistant={lastAssistant} />}
      </main>
      <Palette open={paletteOpen} actions={paletteActions} onClose={() => setPaletteOpen(false)} />
    </div>
  );
}
