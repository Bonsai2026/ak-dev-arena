import { useRef, useState } from "react";
import { speakText, transcribeAudio } from "../api";

interface Props {
  onTranscript: (text: string) => void;
  lastAssistant: string;
}

export default function Voice({ onTranscript, lastAssistant }: Props) {
  const [recording, setRecording] = useState(false);
  const [busy, setBusy] = useState(false);
  const [transcript, setTranscript] = useState("");
  const [error, setError] = useState("");
  const [speaking, setSpeaking] = useState(false);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);

  const supported = typeof window !== "undefined" && "MediaRecorder" in window;

  const start = async () => {
    setError("");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const rec = new MediaRecorder(stream);
      chunksRef.current = [];
      rec.ondataavailable = (e) => {
        if (e.data.size) chunksRef.current.push(e.data);
      };
      rec.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        const blob = new Blob(chunksRef.current, { type: "audio/webm" });
        if (!blob.size) return;
        setBusy(true);
        try {
          const res = await transcribeAudio(blob);
          setTranscript(res.text);
        } catch (e) {
          setError(e instanceof Error ? e.message : "Transcription failed");
        } finally {
          setBusy(false);
        }
      };
      recorderRef.current = rec;
      rec.start();
      setRecording(true);
    } catch {
      setError("Microphone blocked — allow mic access and retry.");
    }
  };

  const stop = () => {
    recorderRef.current?.stop();
    setRecording(false);
  };

  const speak = async () => {
    if (!lastAssistant || speaking) return;
    setSpeaking(true);
    setError("");
    try {
      const blob = await speakText(lastAssistant);
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      audio.onended = () => {
        URL.revokeObjectURL(url);
        setSpeaking(false);
      };
      await audio.play();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Speech failed");
      setSpeaking(false);
    }
  };

  return (
    <div className="h-full overflow-y-auto p-6">
      <h2 className="font-bold text-lg mb-1">🎙️ Voice Mode</h2>
      <p className="text-xs text-zinc-500 mb-6">
        Hands-free Arena. Backend needs <code>pip install faster-whisper edge-tts</code> (see error hints if missing).
      </p>

      {!supported && <div className="text-sm text-amber-400 mb-4">⚠️ This browser has no MediaRecorder — use Chrome/Edge.</div>}
      {error && <div className="text-sm text-red-400 bg-red-950/40 border border-red-900 rounded-lg p-3 mb-4">{error}</div>}

      <div className="flex flex-col items-center gap-4 py-6">
        <button
          onClick={recording ? stop : start}
          disabled={!supported || busy}
          className={`w-24 h-24 rounded-full text-4xl transition-all disabled:opacity-40 ${
            recording ? "bg-red-600 animate-pulse scale-110" : "bg-indigo-600 hover:bg-indigo-500"
          }`}
        >
          🎙️
        </button>
        <div className="text-sm text-zinc-400">
          {recording ? "🔴 Recording… click to stop" : busy ? "⏳ Transcribing…" : "Click the mic and speak"}
        </div>
      </div>

      {transcript && (
        <div className="rounded-xl bg-zinc-900 border border-zinc-800 p-4 mb-4">
          <div className="text-[11px] uppercase tracking-widest text-zinc-500 mb-1">You said</div>
          <div className="text-[15px] mb-3">“{transcript}”</div>
          <button
            onClick={() => onTranscript(transcript)}
            className="px-5 py-2 rounded-lg bg-indigo-600 text-sm font-semibold hover:bg-indigo-500"
          >
            💬 Send to Chat
          </button>
        </div>
      )}

      <div className="rounded-xl bg-zinc-900 border border-zinc-800 p-4">
        <div className="text-[11px] uppercase tracking-widest text-zinc-500 mb-1">Arena speaks</div>
        <div className="text-sm text-zinc-300 mb-3 max-h-32 overflow-auto">
          {lastAssistant ? lastAssistant.slice(0, 500) : "No assistant reply yet — chat first, then press Speak."}
        </div>
        <button
          onClick={speak}
          disabled={!lastAssistant || speaking}
          className="px-5 py-2 rounded-lg bg-emerald-700 text-sm font-semibold disabled:opacity-40 hover:bg-emerald-600"
        >
          {speaking ? "🔊 Speaking…" : "🔊 Speak last reply"}
        </button>
      </div>
    </div>
  );
}
