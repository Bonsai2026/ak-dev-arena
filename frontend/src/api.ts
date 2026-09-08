/* Typed client for the Arena backend (FastAPI sidecar). */

export interface ChatMessage {
  role: "system" | "user" | "assistant";
  content: string;
}

export interface ModelEntry {
  id: string;
  label: string;
  provider: string;
  best_for: string;
  needs_key: boolean;
  configured: boolean;
}

export interface ProviderEntry {
  provider: string;
  env_var: string | null;
  needs_key: boolean;
  configured: boolean;
}

async function asJson(res: Response): Promise<any> {
  if (!res.ok) {
    const detail = await res
      .json()
      .then((b) => (b as any)?.detail ?? res.statusText)
      .catch(() => res.statusText);
    throw new Error(typeof detail === "string" ? detail : res.statusText);
  }
  return res.json();
}

export async function getModels(): Promise<{ models: ModelEntry[]; defaults: Record<string, string> }> {
  const res = await fetch("/api/models");
  return asJson(res);
}

export async function getProviders(): Promise<{ providers: ProviderEntry[] }> {
  const res = await fetch("/api/providers");
  return asJson(res);
}

export async function saveKey(provider: string, key: string): Promise<void> {
  const res = await fetch("/api/keys", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ provider, key }),
  });
  await asJson(res);
}

export async function deleteKey(provider: string): Promise<void> {
  const res = await fetch(`/api/keys/${provider}`, { method: "DELETE" });
  await asJson(res);
}

/** POST /api/chat/stream and invoke onToken per SSE delta. */
export async function streamChat(
  model: string,
  messages: ChatMessage[],
  onToken: (token: string) => void
): Promise<void> {
  const res = await fetch("/api/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model, messages }),
  });
  if (!res.ok || !res.body) {
    const detail = await res
      .json()
      .then((b) => (b as any)?.detail ?? res.statusText)
      .catch(() => res.statusText);
    throw new Error(typeof detail === "string" ? detail : res.statusText);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed.startsWith("data:")) continue;
      const payload = trimmed.slice(5).trim();
      if (payload === "[DONE]") return;
      try {
        const obj = JSON.parse(payload);
        if (obj.error) throw new Error(obj.error);
        if (obj.token) onToken(obj.token);
      } catch (e) {
        if (e instanceof Error && !payload.startsWith("{")) continue;
        if (e instanceof SyntaxError) continue;
        throw e;
      }
    }
  }
}
