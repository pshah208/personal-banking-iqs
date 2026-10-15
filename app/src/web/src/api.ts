import { getToken } from "./auth";
import type { AppConfig, Citation, IQId, IQMeta, Story } from "./types";

async function authHeaders(): Promise<Record<string, string>> {
  const token = await getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export async function apiGet<T>(path: string): Promise<T> {
  const r = await fetch(path, { headers: await authHeaders() });
  if (!r.ok) throw new Error(`${path} ${r.status}`);
  return r.json();
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(path, {
    method: "POST",
    headers: { ...(await authHeaders()), "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`${path} ${r.status}`);
  return r.json();
}

/** POST and save the response as a file (Word drafts). */
export async function apiDownload(path: string, body: unknown, fallbackName: string): Promise<void> {
  const r = await fetch(path, {
    method: "POST",
    headers: { ...(await authHeaders()), "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`${path} ${r.status}`);
  const name = /filename="([^"]+)"/.exec(r.headers.get("Content-Disposition") ?? "")?.[1] ?? fallbackName;
  const url = URL.createObjectURL(await r.blob());
  const a = Object.assign(document.createElement("a"), { href: url, download: name });
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export async function fetchConfig(): Promise<AppConfig> {
  const r = await fetch("/api/config");
  if (!r.ok) throw new Error(`config ${r.status}`);
  return r.json();
}

export async function fetchIQs(): Promise<IQMeta[]> {
  const r = await fetch("/api/iqs");
  if (!r.ok) throw new Error(`iqs ${r.status}`);
  return r.json();
}

export async function fetchStory(): Promise<Story> {
  const r = await fetch("/api/story");
  if (!r.ok) throw new Error(`story ${r.status}`);
  return r.json();
}

export async function fetchMe(): Promise<import("./types").Me> {
  const r = await fetch("/api/me", { headers: await authHeaders() });
  if (!r.ok) throw new Error(`me ${r.status}`);
  return r.json();
}

export async function runDiagnostics(): Promise<unknown> {
  const r = await fetch("/api/diag", { headers: await authHeaders() });
  return r.json();
}

export interface StreamHandlers {
  onStatus?: (text: string) => void;
  onIQ?: (iq: IQId, status: "active" | "done", detail: string) => void;
  /** A chunk of the answer as it is generated. Appended, not replaced. */
  onToken?: (text: string) => void;
  onMessage?: (text: string, citations: Citation[]) => void;
  onError?: (text: string, detail: string) => void;
  onDone?: (payload: Record<string, unknown>) => void;
  /** Any other named event (mission harness steps, tool calls, reviewer stream). */
  onEvent?: (event: string, payload: any) => void;
}

/**
 * POST the question and consume the SSE stream.
 *
 * EventSource cannot POST, so the stream is read manually. Frames are
 * `event: <name>\ndata: <json>\n\n`.
 */
export async function streamChat(
  question: string,
  threadId: string | null,
  handlers: StreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  return streamSSE("/api/chat", { question, threadId }, handlers, signal);
}

/** POST `body` to any SSE endpoint (chat, scenario brief, compliance review) and dispatch frames. */
export async function streamSSE(
  path: string,
  body: unknown,
  handlers: StreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(await authHeaders()) },
    body: JSON.stringify(body),
    signal,
  });

  if (!res.ok || !res.body) {
    let detail = `HTTP ${res.status}`;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* response had no JSON body */
    }
    handlers.onError?.("Request failed.", String(detail));
    handlers.onDone?.({ ok: false });
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let split: number;
    while ((split = buffer.indexOf("\n\n")) !== -1) {
      const frame = buffer.slice(0, split);
      buffer = buffer.slice(split + 2);

      let event = "message";
      const dataLines: string[] = [];
      for (const line of frame.split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
      }
      if (!dataLines.length) continue;

      let payload: any;
      try {
        payload = JSON.parse(dataLines.join("\n"));
      } catch {
        continue;
      }

      switch (event) {
        case "status":
          handlers.onStatus?.(payload.text);
          break;
        case "iq_active":
          handlers.onIQ?.(payload.iq, payload.status, payload.detail ?? "");
          break;
        case "token":
          handlers.onToken?.(payload.text ?? "");
          break;
        case "message":
          handlers.onMessage?.(payload.text ?? "", payload.citations ?? []);
          break;
        case "error":
          handlers.onError?.(payload.text ?? "Error", payload.detail ?? "");
          break;
        case "done":
          handlers.onDone?.(payload);
          break;
        default:
          handlers.onEvent?.(event, payload);
          break;
      }
    }
  }
}
