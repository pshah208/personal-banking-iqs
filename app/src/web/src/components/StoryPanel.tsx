import { useEffect, useRef, useState } from "react";
import type { Chapter, Persona, Story } from "../types";
import { FlowScene } from "./FlowScene";
import { useBrand } from "../useBrand";
import { IQPanel } from "./IQPanel";
import { IQDiagram } from "./IQDiagram";
import { DIAGRAMS } from "../lib/iqDiagram";
import type { IQState } from "../types";

interface Props {
  story: Story;
  persona: Persona;
  /** Given name of the signed-in user, substituted into `{firstName}` in the narrative. */
  firstName: string;
  index: number;
  iqs: IQState[];
  busy: boolean;
  /** True once this chapter's prompt has produced an answer. */
  answered: boolean;
  onPrev: () => void;
  onNext: () => void;
  onGoTo: (index: number) => void;
  onRunPrompt: (prompt: string) => void;
}

function initials(name: string): string {
  return name.split(/\s+/).filter(Boolean).map((p) => p[0]).slice(0, 2).join("");
}

/**
 * The narrative is written about whoever is signed in, so no persona name is
 * hard-coded in story.json. Chapter copy carries a `{firstName}` token that is
 * replaced here with the given name from Microsoft Graph.
 */
function fill(text: string, firstName: string): string {
  return text.replace(/\{firstName\}/g, firstName);
}

function fillChapter(ch: Chapter, firstName: string): Chapter {
  return {
    ...ch,
    title: fill(ch.title, firstName),
    kicker: fill(ch.kicker, firstName),
    body: ch.body ? fill(ch.body, firstName) : ch.body,
    note: ch.note ? fill(ch.note, firstName) : ch.note,
    stakes: ch.stakes ? fill(ch.stakes, firstName) : ch.stakes,
    expect: ch.expect?.map((e) => fill(e, firstName)),
    prompt: ch.prompt ? fill(ch.prompt, firstName) : ch.prompt,
  };
}

function PersonaSlide({ persona, ch }: { persona: Persona; ch: Chapter }) {
  const brand = useBrand();
  const points = persona.points ?? ch.points ?? [];
  return (
    <div className="slide slide-persona slide-transition">
      <div className="persona-split">
        <div className="persona-brand-panel">
          <img
            className="persona-brand-logo"
            src={brand.assets.mark}
            alt=""
            aria-hidden
          />
          <div className="persona-brand-org">{persona.org}</div>
          <div className="persona-brand-role">{persona.title}</div>
          <h2 className="persona-brand-name">{persona.name}</h2>
          <div className="persona-brand-goal">{persona.goal}</div>
          <div className="persona-brand-avatar" aria-hidden>
            {initials(persona.name)}
          </div>
        </div>
        <div className="persona-goals-panel">
          <div className="persona-goals-label">{ch.kicker}</div>
          <h3 className="persona-goals-title">{ch.title || "Assignment"}</h3>
          <p className="slide-lede" style={{ marginTop: 10 }}>{ch.body}</p>
          <ol className="persona-goals-list">
            {persona.objectives.map((o, i) => (
              <li key={i}>
                <span className="goal-num">{i + 1}</span>
                <span>{o}</span>
              </li>
            ))}
          </ol>
          {points.length > 0 && (
            <div className="persona-goals-points">
              {points.map((p) => (
                <div className="point" key={p}>{p}</div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function ArchFlowRail() {
  return (
    <div className="arch-rail" aria-hidden>
      <div className="arch-rail-line" />
      <div className="arch-rail-dot" />
      <div className="arch-rail-arrow">→</div>
    </div>
  );
}

function ArchitectureSlide({ ch }: { ch: Chapter }) {
  return (
    <div className="slide slide-arch slide-transition">
      <div className="slide-eyebrow">{ch.kicker}</div>
      <h2 className="slide-title">{ch.title}</h2>
      <p className="slide-lede">{ch.body}</p>
      <div className="arch-grid">
        {ch.columns?.map((col, i) => {
          const isLast = i === (ch.columns?.length ?? 1) - 1;
          return (
            <>{/* Fragment key on outer element */}
              <div className={`arch-col arch-col-${i}`} key={`col-${col.title}`}>
                <div className="arch-tag">{col.tag}</div>
                <div className="arch-col-title">{col.title}</div>
                {col.items.map((it) => (
                  <div className="arch-item" key={it.name}>
                    <div className="arch-item-name">{it.name}</div>
                    <div className="arch-item-detail">{it.detail}</div>
                  </div>
                ))}
              </div>
              {!isLast && <ArchFlowRail key={`rail-${i}`} />}
            </>
          );
        })}
      </div>
      {ch.assurances?.length ? (
        <div className="arch-assurances">
          {ch.assurances.map((a) => (
            <span className="assurance" key={a}>✓ {a}</span>
          ))}
        </div>
      ) : null}
    </div>
  );
}

/**
 * The four-IQ flow, played as an animated sequence rather than described.
 *
 * The architecture slide states the shape; this one shows the traffic — which
 * layer answers which part of a question, and that the agent has to reconcile
 * all four before anything reaches the advisor.
 */
function VideoSlide({ ch }: { ch: Chapter }) {
  return (
    <div className="slide slide-video slide-transition">
      <div className="slide-eyebrow">{ch.kicker}</div>
      <h2 className="slide-title">{ch.title}</h2>
      <p className="slide-lede">{ch.body}</p>

      <FlowScene />

      {ch.assurances?.length ? (
        <div className="arch-assurances">
          {ch.assurances.map((a) => (
            <span className="assurance" key={a}>✓ {a}</span>
          ))}
        </div>
      ) : null}

      {ch.note && <div className="slide-note">{ch.note}</div>}
    </div>
  );
}

/**
 * The prompt this chapter will send, shown verbatim before it is sent.
 *
 * Seeing the exact question builds far more trust in a demo than a button
 * labelled "run" — the audience can read what was asked and judge the answer
 * against it, rather than taking the narrator's word for what was requested.
 */
function RequestCard({ prompt }: { prompt: string }) {
  return (
    <div className="request-card">
      <div className="request-head">Request to the concierge</div>
      <p className="request-body">{prompt}</p>
    </div>
  );
}

type RunState = "ready" | "sending" | "complete";

function ActionPill({ state, disabled, onRun }: {
  state: RunState; disabled: boolean; onRun: () => void;
}) {
  const label = state === "sending" ? "Prompt sent"
    : state === "complete" ? "Response complete · ask again"
    : "Ask the concierge";

  return (
    <button
      className={`run-prompt state-${state}`}
      disabled={disabled}
      onClick={onRun}
    >
      <span className="run-prompt-label">{label}</span>
      <span className="run-prompt-arrow" aria-hidden>
        {state === "sending" ? "" : "→"}
      </span>
    </button>
  );
}

function IQSlide({ ch, iqs, busy, answered, onRunPrompt }: {
  ch: Chapter; iqs: IQState[]; busy: boolean; answered: boolean;
  onRunPrompt: (p: string) => void;
}) {
  const focus = ch.iq && ch.iq !== "all"
    ? iqs.filter((i) => i.id === ch.iq)
    : iqs;

  const state: RunState = busy ? "sending" : answered ? "complete" : "ready";

  /* A chapter about one layer gets that layer's architecture diagram; the
     chapter that brings all four together keeps the summary cards, because four
     diagrams side by side would be unreadable at presenter distance. */
  const single = focus.length === 1 && focus[0].id in DIAGRAMS ? focus[0] : null;

  return (
    <div className="slide slide-iq slide-transition">
      <div className="slide-eyebrow">{ch.kicker}</div>
      <h2 className="slide-title">{ch.title}</h2>
      <p className="slide-lede">{ch.body}</p>

      {single ? <IQDiagram iq={single} /> : <IQPanel iqs={focus} />}

      {ch.stakes && (
        <div className="stakes">
          <div className="stakes-head">Without this layer</div>
          <p className="stakes-body">{ch.stakes}</p>
        </div>
      )}

      {ch.expect?.length ? (
        <div className="expect">
          <div className="expect-head">What a good answer contains</div>
          <ul>
            {ch.expect.map((e) => <li key={e}>{e}</li>)}
          </ul>
        </div>
      ) : null}

      {ch.note && <div className="slide-note">{ch.note}</div>}

      {ch.prompt && (
        <>
          <RequestCard prompt={ch.prompt} />
          <ActionPill
            state={state}
            disabled={busy}
            onRun={() => onRunPrompt(ch.prompt as string)}
          />
        </>
      )}
    </div>
  );
}

export function StoryPanel({
  story, persona, firstName, index, iqs, busy, answered, onPrev, onNext, onGoTo,
  onRunPrompt,
}: Props) {
  const raw = story.chapters[index];
  const stageRef = useRef<HTMLElement>(null);
  const [full, setFull] = useState(false);

  /* Keep local state in step with the browser, which can exit fullscreen on Esc
     without ever calling our toggle. */
  useEffect(() => {
    const sync = () => setFull(Boolean(document.fullscreenElement));
    document.addEventListener("fullscreenchange", sync);
    return () => document.removeEventListener("fullscreenchange", sync);
  }, []);

  function toggleFullscreen() {
    if (document.fullscreenElement) void document.exitFullscreen();
    else void stageRef.current?.requestFullscreen?.();
  }

  if (!raw) return null;
  const ch = fillChapter(raw, firstName);
  const pct = ((index + 1) / story.chapters.length) * 100;
  const total = story.chapters.length;

  /* The status line mirrors the run state, so a presenter glancing at the top of
     the screen knows whether the agent is mid-flight without watching the chat. */
  const runLine = busy ? "Running · streaming response"
    : answered ? "Response complete · ready when you are"
    : ch.prompt ? "Ready · prompt loaded"
    : "Ready";

  return (
    <section className="story-panel" ref={stageRef}>
      {/* Vertical dot stepper */}
      <nav className="story-dots" aria-label="Story chapters">
        {story.chapters.map((item, i) => (
          <button
            key={item.id}
            className={`story-dot${i === index ? " active" : ""}${i < index ? " completed" : ""}`}
            onClick={() => onGoTo(i)}
            aria-label={`Go to ${item.title}`}
            aria-current={i === index ? "step" : undefined}
          >
            <span className="story-dot-tooltip">
              {String(i + 1).padStart(2, "0")} · {item.title}
            </span>
          </button>
        ))}
      </nav>

      <div className="story-chrome">
        <div className="chrome-id">
          <span className="chrome-num">{String(index + 1).padStart(2, "0")}</span>
          <div className="chrome-titles">
            <div className="chrome-title">{ch.title}</div>
            <div className={`chrome-status${busy ? " live" : ""}`}>{runLine}</div>
          </div>
        </div>

        <div className="chrome-transport" role="group" aria-label="Presenter controls">
          <button onClick={onPrev} disabled={index === 0}
                  title="Previous chapter" aria-label="Previous chapter">‹</button>
          <button onClick={() => onGoTo(0)} title="Back to start"
                  aria-label="Back to start" disabled={index === 0}>⟲</button>
          <button onClick={onNext} disabled={index === total - 1}
                  title="Next chapter" aria-label="Next chapter">›</button>
          <span className="chrome-sep" aria-hidden />
          <button onClick={toggleFullscreen}
                  title={full ? "Exit presenter mode" : "Presenter mode"}
                  aria-label="Toggle presenter mode">
            {full ? "⤡" : "⤢"}
          </button>
        </div>

        <div className="chrome-count">
          {String(index + 1).padStart(2, "0")}
          <span className="chrome-count-sep">/</span>
          {String(total).padStart(2, "0")}
        </div>

        <div className="chrome-rail">
          <div className="chrome-rail-fill" style={{ width: `${pct}%` }} />
        </div>
      </div>

      <div className="story-stage" key={index}>
        {ch.layout === "persona" && <PersonaSlide persona={persona} ch={ch} />}
        {ch.layout === "architecture" && <ArchitectureSlide ch={ch} />}
        {ch.layout === "video" && <VideoSlide ch={ch} />}
        {ch.layout === "iq" && (
          <IQSlide ch={ch} iqs={iqs} busy={busy} answered={answered}
                   onRunPrompt={onRunPrompt} />
        )}
      </div>
    </section>
  );
}
