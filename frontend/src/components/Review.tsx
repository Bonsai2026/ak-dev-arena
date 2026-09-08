import { useState } from "react";
import { reviewDiff } from "../api";
import type { Finding } from "../api";

interface Props {
  model: string;
}

const SEV: Record<string, string> = {
  critical: "🔴",
  warning: "🟡",
  info: "🔵",
};

export default function Review({ model }: Props) {
  const [diff, setDiff] = useState("");
  const [summary, setSummary] = useState("");
  const [findings, setFindings] = useState<Finding[]>([]);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");

  const go = async () => {
    if (!diff.trim() || running) return;
    setRunning(true);
    setError("");
    try {
      const res = await reviewDiff(diff, model);
      setSummary(res.summary);
      setFindings(res.findings);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Review failed");
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="h-full flex">
      <div className="flex-1 min-w-0 flex flex-col border-r border-zinc-800">
        <div className="p-4 border-b border-zinc-800">
          <h2 className="font-bold mb-1">🔍 Review Mode</h2>
          <p className="text-xs text-zinc-500">Paste a diff — get senior-dev findings.</p>
        </div>
        <textarea
          value={diff}
          onChange={(e) => setDiff(e.target.value)}
          placeholder={"--- a/app.py\n+++ b/app.py\n@@ ...\n+your changed code here"}
          spellCheck={false}
          className="flex-1 min-h-0 bg-zinc-950 font-mono text-xs p-4 outline-none resize-none"
        />
        <div className="p-3 border-t border-zinc-800">
          <button
            onClick={go}
            disabled={running || !diff.trim()}
            className="w-full py-2.5 rounded-lg bg-indigo-600 text-sm font-semibold disabled:opacity-40 hover:bg-indigo-500"
          >
            {running ? "Reviewing…" : "🔍 Review diff"}
          </button>
          {error && <div className="mt-2 text-sm text-red-400">⚠️ {error}</div>}
        </div>
      </div>
      <div className="w-[42%] shrink-0 overflow-y-auto p-4 space-y-2">
        {summary && (
          <div className="rounded-lg border border-indigo-800 bg-indigo-950/30 p-3 text-sm">📌 {summary}</div>
        )}
        {findings.map((f, i) => (
          <div key={i} className="rounded-lg bg-zinc-900 border border-zinc-800 p-3 text-sm">
            <div className="flex items-center gap-2 text-xs mb-1">
              <span>{SEV[f.severity] ?? "⚪"}</span>
              <span className="font-bold uppercase">{f.severity}</span>
              <span className="font-mono text-zinc-500">
                {f.file}:{f.line}
              </span>
            </div>
            <div className="text-zinc-200">{f.message}</div>
          </div>
        ))}
        {!summary && findings.length === 0 && (
          <div className="h-full flex items-center justify-center text-zinc-600 text-sm">Findings appear here.</div>
        )}
      </div>
    </div>
  );
}
