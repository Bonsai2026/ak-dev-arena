import { useEffect, useRef, useState } from "react";

export interface PaletteAction {
  label: string;
  hint?: string;
  run: () => void;
}

interface Props {
  open: boolean;
  actions: PaletteAction[];
  onClose: () => void;
}

export default function Palette({ open, actions, onClose }: Props) {
  const [query, setQuery] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (open) {
      setQuery("");
      setTimeout(() => inputRef.current?.focus(), 10);
    }
  }, [open ]);

  if (!open) return null;

  const filtered = actions.filter((a) => a.label.toLowerCase().includes(query.toLowerCase()));

  const fire = (a: PaletteAction) => {
    onClose();
    a.run();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center pt-24" onClick={onClose}>
      <div className="absolute inset-0 bg-black/70" />
      <div
        className="relative w-[560px] max-w-[90vw] rounded-xl bg-zinc-950 border border-zinc-700 shadow-2xl overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <input
          ref={inputRef}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && filtered[0]) fire(filtered[0]);
            if (e.key === "Escape") onClose();
          }}
          placeholder="Type a command… (Esc to close)"
          className="w-full bg-transparent px-5 py-4 text-[15px] outline-none border-b border-zinc-800 placeholder:text-zinc-600"
        />
        <div className="max-h-80 overflow-y-auto py-2">
          {filtered.length === 0 && <div className="px-5 py-4 text-sm text-zinc-500">No matches.</div>}
          {filtered.map((a, i) => (
            <button
              key={i}
              onClick={() => fire(a)}
              className="w-full text-left px-5 py-2.5 text-sm hover:bg-zinc-900 flex items-center gap-3"
            >
              <span className="flex-1">{a.label}</span>
              {a.hint && <span className="text-xs text-zinc-500">{a.hint}</span>}
            </button>
          ))}
        </div>
        <div className="px-5 py-2 border-t border-zinc-800 text-[11px] text-zinc-600">
          Ctrl/⌘+K to open · Enter to run · Shortcuts: modes in sidebar
        </div>
      </div>
    </div>
  );
}
