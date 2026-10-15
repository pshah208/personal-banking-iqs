import { useEffect, useRef, useState } from "react";
import { Citations, Markdown } from "./Markdown";
import { useBrand } from "../useBrand";
import type { ChatMessage, Suggestion } from "../types";

const TICKER_MESSAGES = [
  "Reading the renewal book",
  "Reconciling what people said",
  "Checking the pricing guardrails",
  "Ranking by value at risk",
  "Looking up the approval path",
  "Cross-checking the evidence",
  "Pressure-testing the claim",
] as const;

function ActivityTicker({ status }: { status: string }) {
  const [index, setIndex] = useState(0);

  useEffect(() => {
    const timer = window.setInterval(
      () => setIndex((v) => (v + 1) % TICKER_MESSAGES.length),
      2200,
    );
    return () => window.clearInterval(timer);
  }, []);

  const label = status || TICKER_MESSAGES[index];

  return (
    <span className="activity-ticker">
      <span key={label} className="activity-ticker-text">{label}</span>
      <span className="activity-ticker-dots" aria-hidden>
        <i /><i /><i />
      </span>
    </span>
  );
}

/**
 * Copy the answer as the agent wrote it — raw markdown, not the rendered DOM.
 * Pasting a table into Excel or Teams is the most common thing a user does next.
 */
function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    } catch {
      /* clipboard blocked (insecure origin or denied permission) — stay silent */
    }
  }

  return (
    <button className="msg-action" onClick={copy} title="Copy as markdown">
      {copied ? "Copied" : "Copy"}
    </button>
  );
}

interface Props {
  id?: string;
  hidden?: boolean;
  onCollapse?: () => void;
  messages: ChatMessage[];
  busy: boolean;
  status: string;
  suggestions: Suggestion[];
  agentName: string;
  onSend: (q: string) => void;
  onStop: () => void;
}

const LAYER_LABEL: Record<string, string> = {
  work: "Work IQ",
  fabric: "Fabric IQ",
  foundry: "Foundry IQ",
  web: "Web IQ",
  all: "Cross-layer",
};

/**
 * A starter question, tagged with the layer it exercises.
 *
 * The tag is the point: four layers are an abstraction until you can see which
 * question reaches which one, and that a few questions need more than one.
 */
export function SuggestionButton({ s, onSend, disabled }: {
  s: Suggestion; onSend: (q: string) => void; disabled?: boolean;
}) {
  return (
    <button
      className="suggestion"
      onClick={() => onSend(s.text)}
      disabled={disabled}
    >
      <span className={`suggestion-iq iq-tag-${s.iq}`}>
        {LAYER_LABEL[s.iq] ?? s.iq}
      </span>
      <span className="suggestion-text">{s.text}</span>
      <span className="suggestion-arrow" aria-hidden>↗</span>
    </button>
  );
}

export function ChatPanel({
  id, hidden, onCollapse, messages, busy, status, suggestions, agentName, onSend, onStop,
}: Props) {
  const brand = useBrand();
  const [draft, setDraft] = useState("");
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, status]);

  function submit(e?: React.FormEvent) {
    e?.preventDefault();
    const q = draft.trim();
    if (!q || busy) return;
    setDraft("");
    onSend(q);
  }

  return (
    <section className="chat-panel" id={id} hidden={hidden}>
      <header className="chat-head">
        <div className="chat-brand">
          <span className="chat-mark" aria-hidden>◆</span>
          <div>
            <div className="chat-title">Mortgage Renewal Concierge</div>
            <div className="chat-sub">
              Ask about renewals, risk, retention offers and approvals
            </div>
          </div>
        </div>
        <span className="chat-agent" title="Foundry agent">{agentName}</span>
        {onCollapse && (
          <button type="button" className="chat-collapse" onClick={onCollapse} aria-label="Collapse chat" title="Collapse chat">
            <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden><path d="M6 3.5 10.5 8 6 12.5" /></svg>
          </button>
        )}
      </header>

      <div className="chat-body">
        {messages.length === 0 && (
          <div className="chat-empty">
            <div className="empty-eyebrow">{brand.short} intelligence</div>
            <h2 className="empty-title">What do you need<br />to decide?</h2>
            <p className="empty-sub">
              Grounded across the renewal book, the campaign's email and Teams
              history, and the pricing and policy rulebook.
            </p>
            <div className="suggestions">
              {suggestions.slice(0, 4).map((s) => (
                <SuggestionButton key={s.text} s={s} onSend={onSend} />
              ))}
            </div>
          </div>
        )}

        {messages.map((m, i) => (
          <div className={`msg msg-${m.role}`} key={i}>
            {m.role === "assistant" && (
              <div className="msg-chrome">
                <div className="msg-layers">
                  {(m.layers ?? []).map((l) => (
                    <span className={`layer-tag layer-${l}`} key={l}>
                      <i className="layer-dot" aria-hidden />
                      {LAYER_LABEL[l] ?? l}
                    </span>
                  ))}
                  {!m.layers?.length && (
                    <span className="layer-tag layer-none">Model only</span>
                  )}
                </div>
                <CopyButton text={m.content} />
              </div>
            )}
            <div className="msg-body">
              {m.role === "user" ? <p>{m.content}</p> : <Markdown text={m.content} />}
              {m.streaming && <span className="stream-caret" aria-hidden />}
            </div>
            {m.citations?.length ? <Citations items={m.citations} /> : null}
          </div>
        ))}

        {/* The ticker is only meaningful before the first token lands. Once
            prose is streaming, the text itself is the progress indicator. */}
        {busy && !messages[messages.length - 1]?.streaming && (
          <div className="msg msg-assistant">
            <div className="thinking">
              <ActivityTicker status={status} />
            </div>
          </div>
        )}
        <div ref={endRef} />
      </div>

      <form className="chat-input" onSubmit={submit}>
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Ask about the renewal book…"
          disabled={busy}
          aria-label="Ask the concierge"
        />
        {busy ? (
          <button type="button" className="btn-stop" onClick={onStop}>Stop</button>
        ) : (
          <button type="submit" className="btn-send" disabled={!draft.trim()}>
            Ask
          </button>
        )}
      </form>
    </section>
  );
}
