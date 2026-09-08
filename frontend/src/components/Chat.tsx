import { useEffect, useRef, useState } from "react";
import type { ChatMessage } from "../api";

interface Props {
  messages: ChatMessage[];
  streaming: boolean;
  ready: boolean;
  onSend: (text: string) => void;
}

/** Minimal markdown-lite: ``` code blocks + paragraphs. No deps. */
function renderContent(content: string, keyPrefix: string) {
  const parts = content.split("```");
  return parts.map((part, i) => {
    if (i % 2 === 1) {
      const firstLineEnd = part.indexOf("\n");
      const lang = firstLineEnd > 0 ? part.slice(0, firstLineEnd).trim() : "";
      const code = firstLineEnd > 0 ? part.slice(firstLineEnd + 1) : part;
      return (
        <div key={`${keyPrefix}-${i}`} className="my-2">
          {lang && <div className="text-[11px] uppercase tracking-wide text-zinc-500 mb-1">{lang}</div>}
          <pre className="arena-code">{code.replace(/\n$/, "")}</pre>
        </div>
      );
    }
    return (
      <div key={`${keyPrefix}-${i}`} className="whitespace-pre-wrap">
        {part.trim() ? part : null}
      </div>
    );
  });
}

export default function Chat({ messages, streaming, ready, onSend }: Props) {
  const [input, setInput] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const send = () => {
    const text = input.trim();
    if (!text || streaming || !ready) return;
    setInput("");
    onSend(text);
  };

  return (
    <div className="flex flex-col h-full">
      <div className="flex-1 overflow-y-auto px-6 py-6 space-y-5">
        {messages.length === 0 && (
          <div className="h-full flex flex-col items-center justify-center text-center gap-3">
            <div className="text-5xl">🏟️</div>
            <h1 className="text-2xl font-bold">Welcome to AK Dev Arena</h1>
            <p className="text-zinc-400 max-w-md">
              {ready
                ? "Pick a model in the sidebar and start chatting. Code, Agent, Build and Voice modes are coming in the next phases."
                : "Add an API key via the 🔑 Keys button in the sidebar (or run Ollama locally) to start chatting."}
            </p>
          </div>
        )}
        {messages
          .filter((m) => m.role !== "system")
          .map((m, i) => (
            <div key={i} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
              <div
                className={`max-w-[80%] rounded-xl px-4 py-3 text-[15px] leading-relaxed ${
                  m.role === "user" ? "bg-indigo-600 text-white" : "bg-zinc-900 border border-zinc-800"
                }`}
              >
                {m.role === "assistant" ? renderContent(m.content, `m${i}`) : m.content}
              </div>
            </div>
          ))}
        <div ref={bottomRef} />
      </div>

      <div className="border-t border-zinc-800 p-4">
        <div className="flex gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send();
              }
            }}
            placeholder={ready ? "Ask anything… (Enter to send, Shift+Enter for new line)" : "Add an API key first…"}
            rows={2}
            className="flex-1 resize-none rounded-lg bg-zinc-900 border border-zinc-700 px-4 py-3 text-[15px] outline-none focus:border-indigo-500 placeholder:text-zinc-600"
          />
          <button
            onClick={send}
            disabled={streaming || !ready || !input.trim()}
            className="px-6 rounded-lg bg-indigo-600 font-semibold disabled:opacity-40 disabled:cursor-not-allowed hover:bg-indigo-500"
          >
            {streaming ? "…" : "Send"}
          </button>
        </div>
      </div>
    </div>
  );
}
