/**
 * Scenarios - "what if rates, jobs or prices move?"
 *
 * Pick a preset, a live Web IQ household signal or move the seven factor sliders; the
 * BFF's deterministic renewal engine (pass-through and income betas from the
 * governed Fabric IQ table renewal_scenario_sensitivity) re-prices every renewal:
 * rate -> payment shock -> affordability (RP-013) -> delinquency / attrition ->
 * relationship value. Renewals that breach the TDS guideline flip to support-first.
 * The Scenario Analyst Foundry agent then writes the Retail Risk Committee brief.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties } from "react";
import { apiGet, apiPost, streamSSE } from "../api";
import { Markdown } from "../components/Markdown";
import { SplitHandle, SplitRail, SplitToggle, useChatSplit } from "../components/ChatSplit";
import { MethodFlow } from "./MethodFlow";
import { cad, cadShort, signed, tdsTone, tone } from "./format";
import type { Action, EmergingRisk, Factor, Library, Portfolio, RenewalRun, Rollup, ScenarioRun, WorldPulse, WorldTheme } from "./types";
import "./scenarios.css";

const DEFAULT_PRESET = "base";
const SEV_LABEL: Record<string, string> = { dormant: "Quiet", low: "Faint", elevated: "Building", high: "Strong", severe: "Very strong" };

const fmtFactor = (v: number, f: Pick<Factor, "unit" | "step">) =>
  `${signed(v, f.step < 1 ? 2 : 0)}${f.unit}`;

function annuity(v: Record<string, number>): number {
  const d = (v.discount_pct ?? 6) / 100;
  let s = 0;
  for (let t = 1; t <= (v.horizon_years ?? 5); t++) s += 1 / (1 + d) ** t;
  return s;
}

/* ---------------------------------------------------------------- bridge --- */

function Bridge({ p, ann }: { p: Portfolio; ann: number }) {
  const revenue = (p.nii_after - p.nii_before) * ann;
  const loss = -(p.el_after - p.el_before) * ann;
  const rows = [
    { label: "Retained revenue", sub: `${cad(p.nii_before)} → ${cad(p.nii_after)} / yr`, v: revenue },
    { label: "Expected loss", sub: `${cad(p.el_before)} → ${cad(p.el_after)} / yr`, v: loss },
  ];
  const max = Math.max(1, ...rows.map((r) => Math.abs(r.v)));
  return (
    <div className="sc-wf" role="table" aria-label="Relationship value bridge">
      <div className="sc-wf-row total" role="row">
        <span role="cell">Today's 5-yr value</span><b role="cell" className="num">{cad(p.value_before)}</b><span role="cell" />
      </div>
      {rows.map((r) => (
        <div key={r.label} className="sc-wf-row" role="row">
          <span role="cell">{r.label}<small>{r.sub}</small></span>
          <b role="cell" className={`num t-${tone(r.v, 0.5)}`}>{cad(r.v, true)}</b>
          <span role="cell" className="sc-bar" aria-hidden>
            <i className={tone(r.v, 0.5)} style={{ width: `${(Math.abs(r.v) / max) * 50}%` }} />
          </span>
        </div>
      ))}
      <div className="sc-wf-row total" role="row">
        <span role="cell">Scenario 5-yr value</span>
        <b role="cell" className="num">{cad(p.value_after)}</b>
        <span role="cell" className={`sc-wf-delta t-${tone(p.value_change, 0.5)}`}>{cad(p.value_change, true)} ({signed(p.value_change_pct)}%)</span>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------- breakdown --- */

function Breakdown({ branches, segments }: { branches: Rollup[]; segments: Rollup[] }) {
  const [by, setBy] = useState<"branch" | "segment">("branch");
  const rows = [...(by === "branch" ? branches : segments)].sort((a, b) => a.value_change - b.value_change);
  const max = Math.max(1, ...rows.map((r) => Math.abs(r.value_change)));
  return (
    <article className="sc-card">
      <div className="sc-card-head">
        <h3>Where it lands</h3>
        <div className="sc-seg" role="tablist" aria-label="Break down by">
          <button type="button" role="tab" aria-selected={by === "branch"} className={by === "branch" ? "on" : ""} onClick={() => setBy("branch")}>Branch</button>
          <button type="button" role="tab" aria-selected={by === "segment"} className={by === "segment" ? "on" : ""} onClick={() => setBy("segment")}>Segment</button>
        </div>
      </div>
      <div className="sc-break">
        {rows.map((r) => (
          <div key={r.key} className="sc-break-row">
            <span className="sc-break-name">
              <b>{r.key}</b>
              <small>{r.count} renewals · {r.above_tds} above TDS{r.flipped ? <> · <em>{r.flipped} flip{r.flipped === 1 ? "" : "s"}</em></> : ""}</small>
            </span>
            <span className="sc-bar" aria-hidden><i className={tone(r.value_change, 0.5)} style={{ width: `${(Math.abs(r.value_change) / max) * 50}%` }} /></span>
            <b className={`num t-${tone(r.value_change, 0.5)}`}>{cad(r.value_change, true)}</b>
          </div>
        ))}
      </div>
    </article>
  );
}

/* ----------------------------------------------------------------- table --- */

const actTone = (a: Action) => (a === "Support first" ? "flip" : a === "Retain" ? "retain" : "renew");

function RenewalRow({ r, maxAbs, open, onToggle, gds, tds }: {
  r: RenewalRun; maxAbs: number; open: boolean; onToggle: () => void; gds: number; tds: number;
}) {
  const changed = r.action_after !== r.action_before;
  return (
    <>
      <tr className={`${open ? "open" : ""}${r.flipped ? " flipped" : ""}`}>
        <th scope="row">
          <button type="button" className="sc-link" aria-expanded={open} onClick={onToggle}>
            <span className="sc-chev" aria-hidden>›</span>
            <span><code>{r.renewal_id}</code> {r.name}</span>
          </button>
          <small>{r.segment} · {r.branch}</small>
        </th>
        <td className="num sc-col-rate">{r.rate_before.toFixed(2)}% → <b>{r.rate_after.toFixed(2)}%</b></td>
        <td className="num">{r.shock_before_pct.toFixed(0)}% → <b className={r.shock_after_pct > r.shock_before_pct + 0.05 ? "t-down" : r.shock_after_pct < r.shock_before_pct - 0.05 ? "t-up" : ""}>{r.shock_after_pct.toFixed(0)}%</b></td>
        <td className="num">
          <span className="sc-muted-num">{r.tds_before_pct.toFixed(1)}</span> → <span className={`sc-pill p-${tdsTone(r.tds_after_pct, gds, tds)}`}>{r.tds_after_pct.toFixed(1)}%</span>
        </td>
        <td>
          {changed
            ? <span className="sc-actflow"><span className="sc-act-from">was {r.action_before}</span><span className={`sc-act a-${actTone(r.action_after)}`}>→ {r.action_after}</span></span>
            : <span className={`sc-act a-${actTone(r.action_after)} quiet`}>{r.action_after}</span>}
        </td>
        <td>
          <div className="sc-delta">
            <span className="sc-bar" aria-hidden>
              <i className={tone(r.value_change, 0.5)} style={{ width: `${(Math.abs(r.value_change) / maxAbs) * 50}%` }} />
            </span>
            <b className={`num t-${tone(r.value_change, 0.5)}`}>{cad(r.value_change, true)}</b>
          </div>
        </td>
      </tr>
      {open && (
        <tr className="sc-detail-row">
          <td colSpan={6}>
            <div className="sc-detail">
              <p>
                <b>{r.product}</b> · {cad(r.balance)} balance · matures in {r.days_to_maturity} days · {r.insured ? "CMHC insured" : "uninsured"} ·
                wellness <span className={`sc-well w-${r.wellness_band.toLowerCase().replace(/\s+/g, "-")}`}>{r.wellness_band}</span>
                {r.vulnerable && <span className="sc-pill p-warn">Vulnerable · RP-012</span>}
              </p>
              <div className="sc-detail-grid">
                <span><small>Renewal rate</small><span>{r.rate_before.toFixed(2)}% → <b>{r.rate_after.toFixed(2)}%</b></span></span>
                <span><small>Monthly payment</small><span>{cad(r.payment_now)} today → {cad(r.payment_before)} → <b>{cad(r.payment_after)}</b></span></span>
                <span><small>GDS (limit {gds}%)</small><span>{r.gds_before_pct.toFixed(1)}% → <b>{r.gds_after_pct.toFixed(1)}%</b></span></span>
                <span><small>TDS (limit {tds}%)</small><span>{r.tds_before_pct.toFixed(1)}% → <b>{r.tds_after_pct.toFixed(1)}%</b></span></span>
                <span><small>12m delinquency PD</small><span>{r.pd_before_pct.toFixed(2)}% → <b>{r.pd_after_pct.toFixed(2)}%</b></span></span>
                <span><small>Attrition</small><span>{(r.attrition_before * 100).toFixed(0)}% → <b>{(r.attrition_after * 100).toFixed(0)}%</b></span></span>
                <span><small>Loan-to-value</small><span>{r.ltv_before_pct.toFixed(1)}% → <b>{r.ltv_after_pct.toFixed(1)}%</b></span></span>
                <span><small>Retained revenue / yr</small><span>{cad(r.nii_before)} → <b>{cad(r.nii_after)}</b></span></span>
                <span><small>Expected loss / yr</small><span>{cad(r.el_before)} → <b>{cad(r.el_after)}</b></span></span>
                <span><small>5-yr relationship value</small><span>{cad(r.value_before)} → <b>{cad(r.value_after)}</b></span></span>
              </div>
              {r.flipped && (
                <p className="sc-flipnote">
                  Scenario TDS {r.tds_after_pct.toFixed(1)}% breaches the {tds}% guideline: this client leaves the retention queue and
                  is offered a support-first conversation (RP-013, RP-012). No pricing push until affordability is reviewed.
                </p>
              )}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

/* ------------------------------------------------------- world / radar --- */

function WorldEvents({ world, busy, error, selected, onPick, onRefresh }: {
  world: WorldPulse | null; busy: boolean; error: string; selected: string;
  onPick: (id: string) => void; onRefresh: () => void;
}) {
  const live = world?.status === "live";
  const when = world?.fetchedAt ? new Date(world.fetchedAt).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "";
  return (
    <section className="sc-world" aria-label="Household signals with live Web IQ">
      <div className="sc-world-head">
        <h2>Household signals</h2>
        <span className={`sc-webiq ${busy ? "busy" : live ? "live" : "off"}`}>
          <i aria-hidden />{busy ? "Web IQ searching…" : live ? `Web IQ · ${when}${world?.stale ? " (stale)" : ""}` : "Governed baseline"}
        </span>
        <button type="button" className="sc-world-refresh" onClick={onRefresh} disabled={busy} title="Re-check the public web now" aria-label="Refresh from Web IQ">
          <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" aria-hidden className={busy ? "spin" : ""}>
            <path d="M13.5 8a5.5 5.5 0 1 1-1.6-3.9M13.5 2.5v3h-3" />
          </svg>
        </button>
      </div>
      <p className="sc-world-sub">
        Signal strength is read from today's public web; the governed preset is scaled
        {world?.intensity ? ` (faint ×${world.intensity.low} · strong ×${world.intensity.high} · very strong ×${world.intensity.severe})` : ""}.
      </p>
      {(error || (world && !live && world.detail && !busy)) && <p className="sc-world-err">Web IQ unavailable - running the governed baseline.</p>}
      <div className="sc-presets" role="radiogroup" aria-label="Household signals">
        {!world && <><div className="sc-skel sc-skel-card sm" /><div className="sc-skel sc-skel-card sm" /><div className="sc-skel sc-skel-card sm" /></>}
        {world?.themes?.map((t, i) => (
          <button key={t.id} type="button" role="radio" aria-checked={selected === t.id} style={{ "--i": i } as CSSProperties}
                  className={`sc-wcard ${selected === t.id ? "on" : ""}${busy ? " loading" : ""}`} onClick={() => onPick(t.id)}>
            <span className="sc-wcard-top">
              <b>{t.name}</b>
              <span className={`sc-sev s-${t.severity}`}>{SEV_LABEL[t.severity] ?? t.severity}</span>
            </span>
            {t.live && t.headline
              ? <small className="sc-wcard-news"><span className={`sc-dot d-${t.status}`} aria-label={t.status} />{t.headline}</small>
              : <small>{t.note}</small>}
            {t.live && (t.source || t.date) && <small className="sc-wcard-src">{[t.source, t.date].filter(Boolean).join(" · ")}</small>}
          </button>
        ))}
      </div>
    </section>
  );
}

function EmergingRadar({ items, selected, onRun }: { items: EmergingRisk[]; selected: string; onRun: (e: EmergingRisk) => void }) {
  if (!items.length) return null;
  return (
    <section className="sc-radar" aria-label="Other signals spotted by Web IQ">
      <div className="sc-world-head">
        <h2>Other signals</h2>
        <span className="sc-radar-tag">Web IQ radar · not yet governed</span>
      </div>
      <p className="sc-world-sub">
        Live household signals outside the library. Run one through its closest governed scenario as a labelled proxy; to make it a
        scenario of its own, add it to the governed library (Fabric IQ).
      </p>
      <ul className="sc-radar-list">
        {items.map((e, i) => {
          const id = `emerging:${e.title}`;
          return (
            <li key={e.title} className={selected === id ? "on" : ""} style={{ "--i": i } as CSSProperties}>
              <span className="sc-wcard-top"><b>{e.title}</b><span className={`sc-sev s-${e.severity}`}>{SEV_LABEL[e.severity] ?? e.severity}</span></span>
              <small className="sc-wcard-news">{e.headline}</small>
              {e.why && <small className="sc-radar-why">{e.why}</small>}
              <span className="sc-radar-foot">
                <small className="sc-wcard-src">{e.url ? <a href={e.url} target="_blank" rel="noreferrer">{e.source || "Source"} ↗</a> : e.source}{e.date ? ` · ${e.date}` : ""}</small>
                {e.closest
                  ? <button type="button" className="sc-radar-run" onClick={() => onRun(e)} aria-pressed={selected === id}
                            title={`Approximates this signal with the governed "${e.closest_name}" preset`}>
                      Proxy: {e.closest_name} ›
                    </button>
                  : <small className="sc-radar-none">No close proxy - needs a new governed scenario</small>}
              </span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function WorldBanner({ t }: { t: WorldTheme }) {
  return (
    <article className={`sc-wbanner s-${t.severity}`}>
      <div className="sc-wbanner-icon" aria-hidden>
        <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="9" /><path d="M3 12h18M12 3c2.5 2.6 3.8 5.6 3.8 9s-1.3 6.4-3.8 9c-2.5-2.6-3.8-5.6-3.8-9S9.5 5.6 12 3z" />
        </svg>
      </div>
      <div className="sc-wbanner-main">
        <small>{t.live ? "Live Web IQ · public web" : "Governed baseline · Web IQ not available"}</small>
        <b>{t.live && t.headline ? t.headline : t.note}</b>
        <span>{t.channels}</span>
        {t.live && (t.source || t.url) && (
          <span className="sc-wbanner-src">
            {t.url ? <a href={t.url} target="_blank" rel="noreferrer">{t.source || "Source"} ↗</a> : t.source}{t.date ? ` · ${t.date}` : ""}
          </span>
        )}
      </div>
      <div className="sc-wbanner-scale">
        <span className={`sc-sev s-${t.severity}`}>{SEV_LABEL[t.severity] ?? t.severity}</span>
        <b>×{t.intensity}</b>
        <small>of the governed shock</small>
      </div>
    </article>
  );
}

/* --------------------------------------------------------------- analyst --- */

function Analyst({ run, factors, hidden, worldId }: { run: ScenarioRun; factors: Record<string, number>; hidden?: boolean; worldId?: string | null }) {
  const [text, setText] = useState("");
  const [layers, setLayers] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("");
  const [briefKey, setBriefKey] = useState("");
  const abort = useRef<AbortController | null>(null);
  useEffect(() => () => abort.current?.abort(), []);

  const key = `${run.name}|${JSON.stringify(factors)}`;
  const stale = !!briefKey && briefKey !== key;

  const brief = async () => {
    abort.current?.abort();
    const ctrl = new AbortController();
    abort.current = ctrl;
    setText(""); setLayers([]); setBusy(true); setStatus("Connecting to the Scenario Analyst…");
    setBriefKey(key);
    await streamSSE("/api/scenarios/narrate", { factors, name: run.name, worldId: worldId ?? null }, {
      onStatus: setStatus,
      onIQ: (iq) => setLayers((l) => (l.includes(iq) ? l : [...l, iq])),
      onToken: (t) => setText((a) => a + t),
      onMessage: (t) => setText(t),
      onError: (t, d) => setText(`**${t}**\n\n${d}`),
      onDone: () => { setBusy(false); setStatus(""); },
    }, ctrl.signal).catch((e) => {
      if (e?.name !== "AbortError") setText(`**Could not reach the Scenario Analyst.**\n\n${String(e)}`);
      setBusy(false);
    });
  };

  return (
    <aside className="sc-analyst" id="sc-analyst" hidden={hidden} aria-label="Scenario Analyst agent">
      <header>
        <span className="sc-analyst-mark" aria-hidden>✦</span>
        <div><b>Scenario Analyst</b><small>Foundry agent · pb-scenario-analyst · Fabric IQ + Foundry IQ</small></div>
      </header>
      <p className="sc-muted">
        Turns this run into a Retail Risk Committee brief. The engine figures are given; the agent verifies affordability
        and wellness in Fabric IQ and grounds the response in RP-013, RP-012, RP-014 and RP-015. Clients are referred to by
        renewal ID only.
        {worldId ? " For household signals it also receives the public Web IQ headline behind the signal strength." : ""}
      </p>
      <button type="button" className="sc-primary" onClick={brief} disabled={busy}>
        {busy ? "Writing brief…" : text ? "Regenerate brief" : "Write committee brief"}
      </button>
      {stale && !busy && <p className="sc-stale">The scenario changed after this brief. Regenerate to refresh it.</p>}
      <div className="sc-analyst-body" aria-live="polite">
        {layers.length > 0 && <div className="sc-layers">{layers.map((l) => <span key={l} className={`sc-layer l-${l}`}>{l} IQ</span>)}</div>}
        {busy && !text && (
          <div aria-busy="true" className="sc-analyst-wait">
            <div className="sc-skel sc-skel-line w90" /><div className="sc-skel sc-skel-line w75" /><div className="sc-skel sc-skel-line w60" />
            <small className="sc-muted">{status}</small>
          </div>
        )}
        {text && <div className="sc-analyst-text"><Markdown text={text} /></div>}
        {!text && !busy && (
          <div className="sc-analyst-empty">
            <b>What you'll get</b>
            <ul>
              <li>A one-line headline for the committee</li>
              <li>Most exposed branches and segments, and why</li>
              <li>What RP-013 / RP-012 / RP-014 / RP-015 require</li>
              <li>Three actions with owner roles</li>
            </ul>
          </div>
        )}
      </div>
    </aside>
  );
}

/* ------------------------------------------------------------------ view --- */

export function ScenariosView({ active, bankName }: { active: boolean; bankName: string }) {
  const [lib, setLib] = useState<Library | null>(null);
  const [factors, setFactors] = useState<Record<string, number>>({});
  const [presetId, setPresetId] = useState(DEFAULT_PRESET);
  const [run, setRun] = useState<ScenarioRun | null>(null);
  const [error, setError] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const [showMethod, setShowMethod] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const seq = useRef(0);
  const results = useRef<HTMLElement>(null);
  const body = useRef<HTMLDivElement>(null);
  const chat = useChatSplit("pbi.scn.chat", 28, 20, 50);
  const [world, setWorld] = useState<WorldPulse | null>(null);
  const [worldBusy, setWorldBusy] = useState(false);
  const [worldErr, setWorldErr] = useState("");

  const loadWorld = (refresh = false) => {
    setWorldBusy(true); setWorldErr("");
    apiGet<WorldPulse>(`/api/scenarios/world${refresh ? "?refresh=true" : ""}`)
      .then((w) => { if (Array.isArray(w?.themes)) setWorld(w); else setWorldErr("Unexpected Web IQ response"); })
      .catch((e) => setWorldErr(String(e)))
      .finally(() => setWorldBusy(false));
  };
  useEffect(() => {
    if (!active || world || worldBusy) return;
    apiGet<WorldPulse>("/api/scenarios/world?cached=true").then((w) => {
      if (!Array.isArray(w?.themes)) { loadWorld(); return; }
      setWorld(w);
      if (w.status !== "live") loadWorld();
    }).catch(() => loadWorld());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active]);

  useEffect(() => {
    if (!active || lib) return;
    apiGet<Library>("/api/scenarios/library").then((l) => {
      if (!Array.isArray(l?.presets) || !l.presets.length) { setError("Scenario library unavailable"); return; }
      const first = l.presets.find((p) => p.id === DEFAULT_PRESET) ?? l.presets[0];
      setLib(l);
      setPresetId(first.id);
      setFactors({ ...first.factors });
    }).catch((e) => setError(String(e)));
  }, [active, lib]);

  const theme: WorldTheme | undefined = world?.themes?.find((t) => t.id === presetId);
  const emerging: EmergingRisk | undefined = presetId.startsWith("emerging:")
    ? world?.emerging?.find((e) => `emerging:${e.title}` === presetId) : undefined;
  const name = theme
    ? `${theme.name} (${theme.live ? `Web IQ severity: ${theme.severity}` : "governed baseline"})`
    : emerging
      ? `Emerging: ${emerging.title} (proxy: ${emerging.closest_name}, ${emerging.severity})`
      : lib?.presets.find((p) => p.id === presetId)?.name ?? "Custom scenario";

  useEffect(() => {
    if (!lib || !Object.keys(factors).length) return;
    const id = ++seq.current;
    const t = window.setTimeout(() => {
      apiPost<ScenarioRun>("/api/scenarios/run", { factors, name })
        .then((r) => {
          if (id !== seq.current) return;
          if (!Array.isArray(r?.renewals) || !r.portfolio) { setError("Unexpected scenario response"); return; }
          setRun(r); setError("");
        })
        .catch((e) => setError(String(e)));
    }, 180);
    return () => window.clearTimeout(t);
  }, [lib, factors, name]);

  // Web IQ refresh changes a theme's severity: re-apply it if that theme is selected.
  useEffect(() => {
    const t = world?.themes?.find((x) => x.id === presetId);
    if (t) setFactors({ ...t.factors });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [world]);

  const pickPreset = (id: string) => {
    const t = world?.themes?.find((x) => x.id === id);
    const pr = lib?.presets.find((x) => x.id === id);
    if (!t && !pr) return;
    setPresetId(id);
    setFactors({ ...(t ? t.factors : pr!.factors) });
  };
  const runEmerging = (e: EmergingRisk) => {
    if (!e.proxy_factors) return;
    setPresetId(`emerging:${e.title}`);
    setFactors({ ...e.proxy_factors });
  };
  const nudge = (fid: string, v: number) => {
    setPresetId("custom");
    setFactors((f) => ({ ...f, [fid]: v }));
  };

  const p = run?.portfolio;
  const v = lib?.valuation ?? {};
  const gds = v.gds_limit_pct ?? 39;
  const tds = v.tds_limit_pct ?? 44;
  const ann = useMemo(() => annuity(lib?.valuation ?? {}), [lib]);
  const maxAbs = useMemo(() => Math.max(1, ...(run?.renewals ?? []).map((r) => Math.abs(r.value_change))), [run]);
  const firstFlip = run?.renewals.find((r) => r.flipped)?.renewal_id ?? run?.renewals[0]?.renewal_id ?? null;
  const LIMIT = 15;
  const visible = run ? (showAll ? run.renewals : run.renewals.slice(0, Math.max(LIMIT, run.portfolio.flipped))) : [];
  const good = lib?.good_dir ?? {};

  return (
    <section className="sc-root" hidden={!active} aria-label="Scenario intelligence">
      <header className="sc-head">
        <div className="sc-head-text">
          <div className="sc-eyebrow">{bankName} · Scenario intelligence</div>
          <h1>What if rates, jobs or prices move?</h1>
          <p>Shock seven governed factors and every renewal in the 180-day book is re-priced: payment shock, affordability, delinquency, attrition and relationship value.</p>
        </div>
        <div className="sc-head-meta">
          <span className="sc-badge">Synthetic scenario · decision support only (RP-015)</span>
          {lib && <span className="sc-asof">As of <time dateTime={lib.as_of}>{lib.as_of}</time></span>}
          <button type="button" className={`sc-howbtn${showMethod ? " on" : ""}`} aria-expanded={showMethod}
                  onClick={() => { setShowMethod(!showMethod); if (!showMethod) results.current?.scrollTo({ top: 0, behavior: "smooth" }); }}>
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden>
              <circle cx="5" cy="12" r="2" /><circle cx="12" cy="12" r="2" /><circle cx="19" cy="12" r="2" /><path d="M7 12h3M14 12h3" />
            </svg>
            {showMethod ? "Hide method" : "How it works"}
          </button>
          <SplitToggle split={chat} controls="sc-analyst" />
        </div>
      </header>
      {error && <div className="sc-error" role="alert">Could not run the scenario: {error}</div>}

      <div ref={body} className={`sc-body${chat.open ? "" : " sc-collapsed"}`} style={{ "--split-w": `${chat.width}%` } as CSSProperties}>
        <nav className="sc-controls" aria-label="Scenario controls">
          <h2>Market scenarios</h2>
          <div className="sc-presets" role="radiogroup" aria-label="Market scenarios">
            {!lib && <><div className="sc-skel sc-skel-card sm" /><div className="sc-skel sc-skel-card sm" /></>}
            {(lib?.presets ?? []).filter((pr) => pr.group !== "world").map((pr) => (
              <button key={pr.id} type="button" role="radio" aria-checked={presetId === pr.id}
                      className={presetId === pr.id ? "on" : ""} onClick={() => pickPreset(pr.id)}>
                <b>{pr.name}</b><small>{pr.note}</small>
              </button>
            ))}
            {presetId === "custom" && <div className="sc-custom">Custom scenario - adjusted by hand</div>}
          </div>
          <WorldEvents world={world} busy={worldBusy} error={worldErr} selected={presetId}
                       onPick={pickPreset} onRefresh={() => loadWorld(true)} />
          <EmergingRadar items={world?.emerging ?? []} selected={presetId} onRun={runEmerging} />
          <h2>Factors</h2>
          {(lib?.factors ?? []).map((f) => {
            const x = factors[f.id] ?? 0;
            const t = tone(x * (good[f.id] ?? 1), 1e-9);
            const pos = ((x - f.min) / (f.max - f.min)) * 100;
            const zero = ((0 - f.min) / (f.max - f.min)) * 100;
            return (
              <label key={f.id} className={`sc-factor f-${t}`}
                     style={{ "--lo": `${Math.min(pos, zero)}%`, "--hi": `${Math.max(pos, zero)}%`, "--zero": `${zero}%` } as CSSProperties}>
                <span className="sc-factor-head"><span>{f.label}</span><b className={`num t-${t}`}>{fmtFactor(x, f)}</b></span>
                <input type="range" min={f.min} max={f.max} step={f.step} value={x}
                       onChange={(e) => nudge(f.id, Number(e.target.value))}
                       aria-valuetext={fmtFactor(x, f)} />
                <span className="sc-range"><small>{fmtFactor(f.min, f)}</small><small>{fmtFactor(f.max, f)}</small></span>
              </label>
            );
          })}
          <button type="button" className="sc-reset" onClick={() => pickPreset(DEFAULT_PRESET)}>Reset to today's renewal book</button>
        </nav>

        <main ref={results} className="sc-results" tabIndex={0} aria-label="Scenario results" aria-busy={!run}>
          {!run || !p ? (
            <div aria-busy="true" className="sc-loading">
              <div className="sc-skel sc-skel-title" /><div className="sc-skel sc-skel-card" /><div className="sc-skel sc-skel-card" />
            </div>
          ) : (
            <>
              {theme && <WorldBanner t={theme} />}
              {emerging && (
                <article className="sc-wbanner s-elevated sc-proxy">
                  <div className="sc-wbanner-icon" aria-hidden>≈</div>
                  <div className="sc-wbanner-main">
                    <small>Other signal · proxy run · not a governed scenario</small>
                    <b>{emerging.headline || emerging.title}</b>
                    <span>Approximated with the governed <b>{emerging.closest_name}</b> shock at {SEV_LABEL[emerging.severity]?.toLowerCase() ?? emerging.severity} strength. {emerging.why}</span>
                  </div>
                  <div className="sc-wbanner-scale"><span className={`sc-sev s-${emerging.severity}`}>{SEV_LABEL[emerging.severity] ?? emerging.severity}</span><small>proxy</small></div>
                </article>
              )}
              {showMethod && lib && <MethodFlow key={firstFlip ?? "x"} run={run} lib={lib} initialId={open ?? firstFlip} />}

              <div className="sc-kpis">
                <article className={`sc-kpi hero${p.flipped ? " flip" : ""}`}>
                  <small>Support-first clients</small>
                  <strong className="num">{p.support_first_after}<em>of {p.renewals}</em></strong>
                  <span className="sc-kpi-flip">
                    {p.flipped
                      ? <><b className="sc-flipcount">+{p.flipped} newly flipped</b><span>was {p.support_first_before}</span></>
                      : <>no new flips · was {p.support_first_before}</>}
                  </span>
                </article>
                <article className="sc-kpi">
                  <small>Avg payment shock</small>
                  <strong className="num">{p.avg_shock_after_pct.toFixed(1)}%</strong>
                  <span>from {p.avg_shock_before_pct.toFixed(1)}% · balance-weighted</span>
                </article>
                <article className={`sc-kpi${p.above_tds_after > p.above_tds_before ? " warn" : ""}`}>
                  <small>Above {tds}% TDS guideline</small>
                  <strong className="num">{p.above_tds_after}<em>renewals</em></strong>
                  <span>from {p.above_tds_before} · RP-013</span>
                </article>
                <article className="sc-kpi">
                  <small>Expected delinquencies · 12m</small>
                  <strong className="num">{p.expected_delinquencies_after.toFixed(2)}</strong>
                  <span>from {p.expected_delinquencies_before.toFixed(2)} renewals</span>
                </article>
                <article className="sc-kpi">
                  <small>Expected attrition</small>
                  <strong className="num">{p.expected_attrition_after.toFixed(1)}<em>renewals</em></strong>
                  <span>from {p.expected_attrition_before.toFixed(1)} · {cadShort(p.balance_at_risk_after)} at risk</span>
                </article>
                <article className="sc-kpi">
                  <small>5-yr relationship value</small>
                  <strong className="num">{cadShort(p.value_after)}</strong>
                  <span className={`t-${tone(p.value_change, 0.5)}`}>{cad(p.value_change, true)} ({signed(p.value_change_pct)}%)</span>
                </article>
              </div>

              <div className="sc-grid">
                <article className="sc-card">
                  <div className="sc-card-head"><h3>Value bridge</h3><span>CAD · 5-yr PV @ {v.discount_pct ?? 6}%</span></div>
                  <Bridge p={p} ann={ann} />
                </article>
                <Breakdown branches={run.branches} segments={run.segments} />
              </div>

              <article className="sc-card">
                <div className="sc-card-head">
                  <h3>Renewals - flips first</h3>
                  <span>{p.flipped ? `${p.flipped} flip to support-first, then worst value change` : "worst value change first"} · select a renewal for the full re-pricing</span>
                </div>
                <div className="sc-table-wrap">
                  <table className="sc-table">
                    <thead><tr>
                      <th scope="col">Renewal</th><th scope="col" className="sc-col-rate">Rate</th><th scope="col">Payment shock</th>
                      <th scope="col">TDS</th><th scope="col">Action</th><th scope="col">Value Δ</th>
                    </tr></thead>
                    <tbody>
                      {visible.map((r) => (
                        <RenewalRow key={r.renewal_id} r={r} maxAbs={maxAbs} gds={gds} tds={tds}
                                    open={open === r.renewal_id} onToggle={() => setOpen(open === r.renewal_id ? null : r.renewal_id)} />
                      ))}
                    </tbody>
                  </table>
                </div>
                {run.renewals.length > visible.length || showAll ? (
                  <button type="button" className="sc-more" onClick={() => setShowAll(!showAll)}>
                    {showAll ? "Show fewer" : `Show all ${run.renewals.length} renewals`}
                  </button>
                ) : null}
              </article>
            </>
          )}
        </main>

        {chat.open ? <SplitHandle split={chat} container={body} controls="sc-analyst" label="Scenario Analyst" />
                   : <SplitRail split={chat} controls="sc-analyst" label="Scenario Analyst" />}
        {run ? <Analyst run={run} factors={factors} hidden={!chat.open} worldId={theme?.id ?? (emerging ? presetId : null)} />
             : <aside className="sc-analyst" id="sc-analyst" hidden={!chat.open} aria-busy="true" />}
      </div>
    </section>
  );
}
