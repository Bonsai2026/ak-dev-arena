import { useCallback, useEffect, useMemo, useState } from "react";
import Sidebar from "./components/Sidebar";
import Chat from "./components/Chat";
import { getModels, getProviders, streamChat } from "./api";
import type { ChatMessage, ModelEntry, ProviderEntry } from "./api";

export default function App() {
  const [models, setModels] = useState<ModelEntry[]>([]);
  const [providers, setProviders] = useState<ProviderEntry[]>([]);
  const [currentModel, setCurrentModel] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [backendUp, setBackendUp] = useState<boolean | null>(null);

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

  useEffect(() => {
    refreshCatalog();
  }, [refreshCatalog]);

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
    }
  };

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
        models={models}
        currentModel={currentModel}
        onModelChange={setCurrentModel}
        providers={providers}
        onKeysChanged={refreshCatalog}
      />
      <main className="flex-1 min-w-0 h-full">
        <Chat messages={messages} streaming={streaming} ready={ready} onSend={handleSend} />
      </main>
    </div>
  );
}
