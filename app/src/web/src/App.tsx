import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties } from "react";
import {
  fetchConfig, fetchIQs, fetchMe, fetchStory, runDiagnostics, streamChat,
} from "./api";
import { account, authEnabled, login, logout } from "./auth";
import { applyBrand, brandOrder, getBrand, initialBrand, rebrand, type BrandId } from "./brand";
import { ChatPanel, SuggestionButton } from "./components/ChatPanel";
import { SplitHandle, SplitRail, useChatSplit } from "./components/ChatSplit";
import { FabricCapacityControl } from "./components/FabricCapacityControl";
import { ProductMenu, isProductMode } from "./components/ProductMenu";
import { IQPanel } from "./components/IQPanel";
import { StoryPanel } from "./components/StoryPanel";
import { BookView } from "./books/BookView";
import { CardsView } from "./cards/CardsView";
import { Dashboard } from "./dashboard/Dashboard";
import { ScenariosView } from "./scenarios/ScenariosView";
import type {
  AppConfig, ChatMessage, Citation, IQId, IQMeta, IQState, Me, Story,
} from "./types";

type Mode = "story" | "chat" | "dashboard" | "cards" | "banking" | "borrowing" | "investing" | "newcomers" | "insurance" | "security" | "scenarios";

/** Views that own the page (and their own arrow keys) instead of the Guided/Explore layout. */
const ownsPage = (m: Mode) => m === "scenarios" || isProductMode(m);

function BrandPicker({ value, onChange, variant }: {
  value: BrandId; onChange: (id: BrandId) => void; variant: "topbar" | "signin";
}) {
  const ids = brandOrder();
  // A single deployed bank needs no switcher.
  if (ids.length < 2) return null;
  return (
    <label className={`brand-picker brand-picker-${variant}`}>
      <span className="brand-picker-label">Bank</span>
      <select value={value} onChange={(e) => onChange(e.target.value as BrandId)} aria-label="Bank branding">
        {ids.map((id) => <option key={id} value={id}>{getBrand(id).name}</option>)}
      </select>
    </label>
  );
}

export default function App() {
  const [brandId, setBrandId] = useState<BrandId>(initialBrand);
  const brand = getBrand(brandId);
  useEffect(() => { applyBrand(brandId); }, [brandId]);
  const [rawConfig, setConfig] = useState<AppConfig | null>(null);
  const [rawStory, setStory] = useState<Story | null>(null);
  const config = useMemo(() => (rawConfig ? { ...rebrand(rawConfig, brandId), bank: brand.name } : null),
    [rawConfig, brandId, brand.name]);
  const story = useMemo(() => (rawStory ? rebrand(rawStory, brandId) : null), [rawStory, brandId]);
  const [iqMeta, setIqMeta] = useState<IQMeta[]>([]);
  const [iqs, setIqs] = useState<IQState[]>([]);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("");
  const [threadId, setThreadId] = useState<string | null>(null);
  const [chapter, setChapter] = useState(0);
  const [mode, setMode] = useState<Mode>("story");
  const [me, setMe] = useState<Me | null>(null);
  const [bootError, setBootError] = useState("");
  const [diag, setDiag] = useState<unknown>(null);
  const chat = useChatSplit("pbi.chat", 42, 25, 65);
  const layoutRef = useRef<HTMLElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  const signedIn = !authEnabled || Boolean(account());

  useEffect(() => {
    (async () => {
      try {
        const [c, s, m] = await Promise.all([fetchConfig(), fetchStory(), fetchIQs()]);
        setConfig(c);
        setStory(s);
        setIqMeta(m);
        setIqs(m.map((x) => ({ ...x, status: "idle", detail: "" })));
      } catch (e) {
        setBootError(String(e));
      }
    })();
  }, []);

  useEffect(() => {
    if (!signedIn) return;
    fetchMe().then(setMe).catch(() => setMe(null));
  }, [signedIn]);

  const resetIQs = useCallback(() => {
    setIqs(iqMeta.map((x) => ({ ...x, status: "idle", detail: "" })));
  }, [iqMeta]);

  const send = useCallback(async (question: string) => {
    if (busy) return;
    setMode("chat");
    chat.setOpen(true);
    setMessages((prev) => [...prev, { role: "user", content: question }]);
    resetIQs();
    setBusy(true);
    setStatus("");

    const layers: IQId[] = [];
    const controller = new AbortController();
    abortRef.current = controller;

    await streamChat(question, threadId, {
      onStatus: setStatus,
      onIQ: (iq, st, detail) => {
        if (st === "active" && !layers.includes(iq)) layers.push(iq);
        setIqs((prev) =>
          prev.map((x) => (x.id === iq ? { ...x, status: st, detail } : x)),
        );
      },
      onToken: (text: string) => {
        // Append to an in-flight assistant message, creating it on the first
        // chunk. The final `message` event replaces this text wholesale with
        // the complete answer and its citations, so a partial render can never
        // become the thing citations get attached to.
        setMessages((prev) => {
          const last = prev[prev.length - 1];
          if (last?.role === "assistant" && last.streaming) {
            return [...prev.slice(0, -1), { ...last, content: last.content + text }];
          }
          return [
            ...prev,
            { role: "assistant", content: text, streaming: true, layers: [...layers] },
          ];
        });
      },
      onMessage: (text: string, citations: Citation[]) => {
        setMessages((prev) => {
          const last = prev[prev.length - 1];
          const done = {
            role: "assistant" as const,
            content: text,
            citations,
            layers: [...layers],
            streaming: false,
          };
          // Replace the streamed placeholder rather than appending a duplicate.
          if (last?.role === "assistant" && last.streaming) {
            return [...prev.slice(0, -1), done];
          }
          return [...prev, done];
        });
      },
      onError: (text, detail) => {
        setMessages((prev) => [
          ...prev,
          { role: "error", content: `${text}\n\n${detail}` },
        ]);
      },
      onDone: (payload) => {
        setBusy(false);
        setStatus("");
        if (typeof payload.threadId === "string") setThreadId(payload.threadId);
      },
    }, controller.signal).catch((e) => {
      if (e?.name !== "AbortError") {
        setMessages((prev) => [...prev, { role: "error", content: String(e) }]);
      }
      setBusy(false);
    });
  }, [busy, resetIQs, threadId]);

  const stop = useCallback(() => {
    abortRef.current?.abort();
    setBusy(false);
    setStatus("");
  }, []);

  const suggestions = useMemo(() => story?.suggestions ?? [], [story]);

  /**
   * Whether the last exchange produced an answer, used to drive the story
   * action pill from "ask" to "response complete". Reset per chapter so moving
   * on always offers the next prompt fresh.
   */
  const answered = useMemo(
    () => !busy && messages.length > 0 && messages[messages.length - 1].role !== "user",
    [busy, messages],
  );

  const goTo = useCallback((i: number) => {
    if (story) setChapter(Math.max(0, Math.min(story.chapters.length - 1, i)));
  }, [story]);

  /* Keyboard navigation: arrows, space */
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      // Product books and scenarios own their arrow handling (tables, menus, sliders, splitter).
      if (ownsPage(mode)) return;
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      if (e.key === "ArrowRight") {
        e.preventDefault();
        setChapter((c) => story ? Math.min(story.chapters.length - 1, c + 1) : c);
      } else if (e.key === "ArrowLeft") {
        e.preventDefault();
        setChapter((c) => Math.max(0, c - 1));
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [story, mode]);

  /**
   * The persona card describes whoever is actually signed in.
   *
   * Name and title come from Microsoft Graph (the 14 demo accounts carry real
   * displayName / jobTitle values in Entra). Goal and objectives come from the
   * app role in the user's token, so a Branch Manager sees branch framing and an
   * Advisor sees advisor framing. Falls back to the story's default persona if
   * Graph or the role claim is unavailable.
   */
  const persona = useMemo(() => {
    const base = story?.persona;
    if (!base) return null;
    if (!me) return base;
    const byRole = story?.personaByRole?.[me.role];
    return {
      org: base.org,
      name: me.name || base.name,
      title: me.jobTitle || base.title,
      goal: byRole?.goal ?? base.goal,
      objectives: byRole?.objectives ?? base.objectives,
      points: byRole?.points,
    };
  }, [story, me]);

  /**
   * Given name of the signed-in user, used to personalise the narrative copy.
   * Derived only from Graph - never from the story's fallback persona - so a
   * failed /api/me call reads neutrally rather than naming the wrong person.
   */
  const firstName = useMemo(() => {
    const given = me?.name?.trim().split(/\s+/)[0];
    return given || "the user";
  }, [me]);

  if (bootError) {
    return (
      <div className="boot-error">
        <h1>Could not reach the API</h1>
        <pre>{bootError}</pre>
        <p>Is the BFF running? Try <code>GET /health</code>.</p>
      </div>
    );
  }

  if (!config || !story) {
    return <div className="boot">Loading…</div>;
  }

  if (authEnabled && !signedIn) {
    return (
      <div className="signin">
        <div className="signin-card">
          <BrandPicker value={brandId} onChange={setBrandId} variant="signin" />
          <img className="signin-mark" src={brand.assets.lockup} alt={config.bank} />
          <h1>Personal Banking Intelligence</h1>
          <p className="signin-sub">{config.bank} · Mortgage renewals, customers and financial wellness</p>
          <p className="signin-why">
            Sign in with your work account. The concierge answers using
            <strong> your</strong> email, Teams and document context — so it must
            know who you are before it can ground anything.
          </p>
          <button className="btn-primary" onClick={() => login()}>
            Sign in with Microsoft
          </button>
          <p className="signin-disclaimer">{config.disclaimer}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <img className="brand-mark" src={brand.assets.mark} alt="" aria-hidden />
          <span className="brand-name">{config.bank}</span>
          <span className="brand-divider" />
          <span className="brand-app">Personal Banking Intelligence</span>
        </div>

        <div className="topbar-right">
          {signedIn && <FabricCapacityControl />}
          <BrandPicker value={brandId} onChange={setBrandId} variant="topbar" />
          <nav className="mode-toggle" aria-label="Views">
            <button
              type="button"
              className={mode === "story" ? "on" : ""}
              onClick={() => setMode("story")}
              aria-current={mode === "story" ? "page" : undefined}
            >Guided</button>
            <button
              type="button"
              className={mode === "chat" ? "on" : ""}
              onClick={() => setMode("chat")}
              aria-current={mode === "chat" ? "page" : undefined}
            >Explore</button>
            <ProductMenu mode={mode} onSelect={setMode} />
            <button
              type="button"
              className={mode === "scenarios" ? "on" : ""}
              onClick={() => setMode("scenarios")}
              aria-current={mode === "scenarios" ? "page" : undefined}
            >Scenarios</button>
          </nav>
          {config.mockMode && <span className="pill pill-warn">MOCK MODE</span>}
          {me && (
            <div className="who" title={me.upn}>
              <span className="who-avatar" aria-hidden>
                {me.name.split(" ").map((p) => p[0]).slice(0, 2).join("")}
              </span>
              <span className="who-text">
                <span className="who-name">{me.name}</span>
                {me.role && <span className="who-role">{me.role}</span>}
              </span>
            </div>
          )}
          {authEnabled && (
            <button className="btn-ghost" onClick={() => logout()}>Sign out</button>
          )}
        </div>
      </header>

      <div className="disclaimer-strip">{config.disclaimer}</div>

      {/* Mounted in every mode so dashboard selection, filters and local
          conversations survive switching to Guided or Explore and back. */}
      <Dashboard active={mode === "dashboard"} />
      <CardsView active={mode === "cards"} bankName={brand.name} />
      <BookView book="banking" active={mode === "banking"} bankName={brand.name} />
      <BookView book="borrowing" active={mode === "borrowing"} bankName={brand.name} />
      <BookView book="investing" active={mode === "investing"} bankName={brand.name} />
      <BookView book="newcomers" active={mode === "newcomers"} bankName={brand.name} />
      <BookView book="insurance" active={mode === "insurance"} bankName={brand.name} />
      <BookView book="security" active={mode === "security"} bankName={brand.name} />
      <ScenariosView active={mode === "scenarios"} bankName={brand.name} />

      <main
        id="main-content"
        ref={layoutRef}
        className={`layout layout-${mode}${chat.open ? "" : " chat-collapsed"}`}
        style={{
          "--split-w": `${chat.width}%`,
          ...(ownsPage(mode) ? { display: "none" } : {}),
        } as CSSProperties}
      >
        {mode === "story" ? (
          <StoryPanel
            story={story}
            persona={persona ?? story.persona}
            firstName={firstName}
            answered={answered}
            index={chapter}
            iqs={iqs}
            busy={busy}
            onPrev={() => setChapter((c) => Math.max(0, c - 1))}
            onNext={() => setChapter((c) => Math.min(story.chapters.length - 1, c + 1))}
            onGoTo={goTo}
            onRunPrompt={send}
          />
        ) : (
          <section className="explore-panel">
            <IQPanel iqs={iqs} />
            <div className="explore-suggestions">
              <div className="panel-head">
                <h2 className="panel-title">Try asking</h2>
              </div>
              {suggestions.map((s) => (
                <SuggestionButton key={s.text} s={s} onSend={send} disabled={busy} />
              ))}
            </div>
            <details className="diag">
              <summary>Connection diagnostics</summary>
              <button
                className="btn-ghost"
                onClick={() => runDiagnostics().then(setDiag)}
              >Run checks</button>
              {diag ? <pre>{JSON.stringify(diag, null, 2)}</pre> : null}
            </details>
          </section>
        )}

        {chat.open
          ? <SplitHandle split={chat} container={layoutRef} controls="app-chat" />
          : <SplitRail split={chat} controls="app-chat" />}

        <ChatPanel
          id="app-chat"
          hidden={!chat.open}
          onCollapse={() => chat.setOpen(false)}
          messages={messages}
          busy={busy}
          status={status}
          suggestions={suggestions}
          agentName={config.agentName}
          onSend={send}
          onStop={stop}
        />
      </main>
    </div>
  );
}
