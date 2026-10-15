/**
 * A customer-facing renewal offer flyer, rendered to a canvas and downloadable
 * as a PNG.
 *
 * WHY CANVAS, AND WHY ONE OF THEM
 * -------------------------------
 * The flyer is drawn once, onto a single canvas, which is both the thing shown
 * on screen and the thing that downloads. Rendering the preview as HTML and the
 * export as something else invites the two to drift, and "the PNG didn't match
 * what I saw" is a bad surprise to discover in front of a customer. The obvious
 * alternative — serialising an SVG `foreignObject` into a canvas — taints in
 * Safari and silently drops web fonts, so it is avoided.
 *
 * WHY IT CAN REFUSE TO PRODUCE ARTWORK
 * ------------------------------------
 * RP-003 governs what may be *presented to a client*, not merely what may be
 * approved internally:
 *
 *     "Any offer not listed requires Pricing Committee approval before it is
 *      presented to a client."
 *     "Offers may not be presented outside their eligible segments."
 *
 * A flyer is presentation. So every line is checked against the catalogue served
 * by `/api/offers` before the artwork is called approved, and a breach is drawn
 * onto the flyer itself rather than reported quietly beside it. A watermarked
 * flyer that says why it is not usable is far more useful than a clean one that
 * is quietly non-compliant.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { useOfferCatalogue } from "../lib/offers";
import { cssVar, currentBrand, rebrandText } from "../brand";
import { useBrand } from "../useBrand";
import type { CatalogueOffer, FlyerSpec, FlyerLine } from "../types";

const W = 1080;
const H = 1350;
const SCALE = 2;

let RED = "#ec111a";
const INK = "#1a1a1c";

export type Verdict = "ok" | "exceeds" | "segment" | "unknown";

export interface CheckedLine extends FlyerLine {
  verdict: Verdict;
  /** Plain-language reason, shown to the user and drawn on the flyer. */
  reason: string;
  offer?: CatalogueOffer;
}

/** Basis points named in a line, e.g. "0.15% rate discount" or "15 bps off". */
function bpsOf(line: FlyerLine): number | null {
  if (typeof line.bps === "number") return line.bps;
  const pct = line.headline.match(/(\d+(?:\.\d+)?)\s*%/);
  if (pct) return Math.round(parseFloat(pct[1]) * 100);
  const bps = line.headline.match(/(\d+(?:\.\d+)?)\s*bps/i);
  if (bps) return Math.round(parseFloat(bps[1]));
  return null;
}

/** Cash named in a line, e.g. "Up to $2,000 cashback". */
function cashOf(line: FlyerLine): number | null {
  if (typeof line.cash === "number") return line.cash;
  const m = line.headline.match(/(?:CAD|\$)\s*([\d,]+)/i);
  return m ? parseInt(m[1].replace(/,/g, ""), 10) : null;
}

/**
 * Check one flyer line against the catalogue.
 *
 * Collects *every* failure rather than returning on the first. A line can breach
 * on more than one axis at once — the classic case is a cash amount that is both
 * over the cap and offered to an ineligible segment — and reporting only the
 * first would send someone away to fix one problem and hit the next.
 *
 * The verdict is the most fundamental failure (not in the catalogue at all beats
 * wrong segment beats over the cap), but the reason names all of them.
 */
export function checkLine(
  line: FlyerLine, catalogue: CatalogueOffer[], segment?: string,
): CheckedLine {
  const offer = catalogue.find((o) => o.code === line.code);
  if (!offer) {
    return {
      ...line,
      verdict: "unknown",
      reason: line.code
        ? `${line.code} is not in the RP-003 catalogue.`
        : "Not tied to an approved offer in RP-003.",
    };
  }

  const issues: { verdict: Verdict; reason: string }[] = [];

  if (segment && !offer.segments.includes(segment)) {
    issues.push({
      verdict: "segment",
      reason: `${offer.code} is not eligible for ${segment}.`,
    });
  }

  const bps = bpsOf(line);
  if (bps !== null && bps > offer.max_bps) {
    issues.push({
      verdict: "exceeds",
      reason: `${bps} bps exceeds the ${offer.max_bps} bps cap on ${offer.code}.`,
    });
  }

  const cash = cashOf(line);
  if (cash !== null && cash > offer.max_cash) {
    issues.push({
      verdict: "exceeds",
      reason: `CAD ${cash.toLocaleString("en-CA")} exceeds the CAD ${
        offer.max_cash.toLocaleString("en-CA")} cap on ${offer.code}.`,
    });
  }

  if (!issues.length) {
    return { ...line, offer, verdict: "ok", reason: `${offer.code} ${offer.name}` };
  }

  const order: Verdict[] = ["unknown", "segment", "exceeds"];
  issues.sort((a, b) => order.indexOf(a.verdict) - order.indexOf(b.verdict));

  return {
    ...line,
    offer,
    verdict: issues[0].verdict,
    reason: issues.map((x) => x.reason).join(" "),
  };
}

/* --------------------------------------------------------------- drawing --- */

function roundRect(
  c: CanvasRenderingContext2D, x: number, y: number,
  w: number, h: number, r: number,
) {
  c.beginPath();
  c.moveTo(x + r, y);
  c.arcTo(x + w, y, x + w, y + h, r);
  c.arcTo(x + w, y + h, x, y + h, r);
  c.arcTo(x, y + h, x, y, r);
  c.arcTo(x, y, x + w, y, r);
  c.closePath();
}

/** Greedy wrap. Returns the y position after the last line drawn. */
function wrap(
  c: CanvasRenderingContext2D, text: string,
  x: number, y: number, maxW: number, lineH: number,
): number {
  const words = text.split(/\s+/);
  let line = "";
  let yy = y;
  for (const word of words) {
    const test = line ? `${line} ${word}` : word;
    if (c.measureText(test).width > maxW && line) {
      c.fillText(line, x, yy);
      yy += lineH;
      line = word;
    } else {
      line = test;
    }
  }
  if (line) { c.fillText(line, x, yy); yy += lineH; }
  return yy;
}

/* -------------------------------------------------------------- countdown --- */

/**
 * The 120-day early-renewal window from OFR-03.
 *
 * Used as the countdown's full scale so the ring is not an arbitrary dial: a
 * full ring is the first day the rate can be locked, and an empty one is
 * maturity.
 */
const LOCK_WINDOW_DAYS = 120;

/**
 * Whole days from today to a maturity date, or null if it cannot be read.
 *
 * Parsed at local noon rather than midnight. Dates arrive as plain calendar
 * strings with no timezone, and `Date.parse` treats a bare ISO date as UTC — so
 * a midnight anchor lands on the previous day for anyone west of Greenwich and
 * the flyer would be a day out for every Canadian branch.
 */
export function daysUntil(text: string | undefined, now = new Date()): number | null {
  if (!text) return null;

  const iso = text.match(/(20\d{2})-(\d{2})-(\d{2})/);
  const due = iso
    ? new Date(+iso[1], +iso[2] - 1, +iso[3], 12)
    : (() => {
        const parsed = Date.parse(text);
        if (Number.isNaN(parsed)) return null;
        const d = new Date(parsed);
        return new Date(d.getFullYear(), d.getMonth(), d.getDate(), 12);
      })();
  if (!due) return null;

  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 12);
  return Math.round((due.getTime() - today.getTime()) / 86_400_000);
}

/** Urgency colour. Inside a month is the point at which this stops being admin. */
function urgencyOf(days: number): { ring: string; label: string } {
  if (days <= 30) return { ring: RED, label: "Renewing very soon" };
  if (days <= 90) return { ring: "#b45309", label: "Renewal window open" };
  return { ring: "#0f766e", label: "Plenty of time to plan" };
}

/**
 * The countdown dial.
 *
 * A number of days is more motivating than a date — "12 days" prompts a call in
 * a way that "2026-08-25" does not — but the date is kept beside it so the
 * artwork is still unambiguous once printed and left on a desk.
 */
function drawCountdown(
  c: CanvasRenderingContext2D, x: number, y: number, w: number,
  days: number, expiry: string | undefined,
) {
  const h = 188;
  const tone = urgencyOf(days);
  const overdue = days <= 0;

  c.fillStyle = "#faf8f6";
  roundRect(c, x, y, w, h, 14);
  c.fill();
  c.fillStyle = tone.ring;
  roundRect(c, x, y, 6, h, 3);
  c.fill();

  /* ---- ring ---- */
  const cx = x + 118;
  const cy = y + h / 2;
  const r = 62;
  const frac = Math.max(0, Math.min(1, days / LOCK_WINDOW_DAYS));

  c.lineWidth = 14;
  c.strokeStyle = "#e6e4e1";
  c.beginPath();
  c.arc(cx, cy, r, 0, Math.PI * 2);
  c.stroke();

  if (frac > 0) {
    c.strokeStyle = tone.ring;
    c.lineCap = "round";
    c.beginPath();
    c.arc(cx, cy, r, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * frac);
    c.stroke();
    c.lineCap = "butt";
  }

  c.textAlign = "center";
  c.fillStyle = overdue ? RED : INK;
  c.font = `800 ${overdue ? 30 : 52}px 'Segoe UI', Arial, sans-serif`;
  c.fillText(overdue ? "DUE" : String(days), cx, cy + (overdue ? 10 : 12));
  if (!overdue) {
    c.fillStyle = "#71717a";
    c.font = "700 17px 'Segoe UI', Arial, sans-serif";
    c.fillText(days === 1 ? "DAY" : "DAYS", cx, cy + 38);
  }
  c.textAlign = "left";

  /* ---- copy ---- */
  const tx = x + 214;
  c.fillStyle = tone.ring;
  c.font = "700 19px 'Segoe UI', Arial, sans-serif";
  c.letterSpacing = "2px";
  c.fillText(overdue ? "RENEWAL DUE NOW" : "TIME LEFT TO RENEW", tx, y + 50);
  c.letterSpacing = "0px";

  c.fillStyle = INK;
  c.font = "800 36px 'Segoe UI', Arial, sans-serif";
  c.fillText(
    overdue
      ? "Your mortgage is up for renewal"
      : `${days} ${days === 1 ? "day" : "days"} until your mortgage matures`,
    tx, y + 96,
  );

  c.fillStyle = "#71717a";
  c.font = "400 23px 'Segoe UI', Arial, sans-serif";
  c.fillText(
    overdue
      ? "Your renewal date has passed. Contact us today."
      : `${tone.label}. Speak to us to lock this rate in.`,
    tx, y + 132,
  );

  if (expiry) {
    c.fillStyle = "#71717a";
    c.font = "700 19px 'Segoe UI', Arial, sans-serif";
    c.letterSpacing = "2px";
    c.fillText("OFFER EXPIRES", tx, y + 166);
    c.letterSpacing = "0px";
    c.fillStyle = INK;
    c.font = "700 21px 'Segoe UI', Arial, sans-serif";
    c.fillText(expiry, tx + 168, y + 166);
  }

  return y + h;
}

/**
 * The cross-sell panel.
 *
 * Led by the action rather than the reward, because the action is the part the
 * customer has to decide about — and it differs by offer, so a fixed "bundle
 * your products" headline would misdescribe an investment-transfer offer.
 *
 * Framed as a swap rather than a top-up, and worded that way on the artwork,
 * because RP-003 does not allow discounts to stack. A customer who reads this as
 * "and also" would arrive at a branch expecting a number nobody approved.
 */
function drawBundle(
  c: CanvasRenderingContext2D, x: number, y: number, w: number,
  line: CheckedLine & { action: string },
) {
  const h = 172;

  c.fillStyle = "#0f1c1a";
  roundRect(c, x, y, w, h, 14);
  c.fill();

  c.fillStyle = "#5eead4";
  c.font = "700 19px 'Segoe UI', Arial, sans-serif";
  c.letterSpacing = "2px";
  c.fillText(line.action.toUpperCase(), x + 34, y + 44);
  c.letterSpacing = "0px";

  c.fillStyle = "#ffffff";
  c.font = "800 34px 'Segoe UI', Arial, sans-serif";
  c.fillText(`Unlock ${line.headline.replace(/^Up to /, "up to ")}`, x + 34, y + 88);

  c.fillStyle = "rgba(255,255,255,.66)";
  c.font = "400 22px 'Segoe UI', Arial, sans-serif";
  wrap(c, line.detail ?? "", x + 34, y + 122, w - 68, 28);

  c.fillStyle = "rgba(255,255,255,.42)";
  c.font = "400 18px 'Segoe UI', Arial, sans-serif";
  c.fillText(
    "An alternative to the offer above, not in addition to it.",
    x + 34, y + 154,
  );

  return y + h;
}

/** The rotated stamp across the artwork, so a screenshot cannot lose the caveat. */
function stamp(
  c: CanvasRenderingContext2D, heading: string, sub: string, tint: string,
) {
  c.save();
  c.translate(W / 2, H / 2);
  c.rotate(-Math.PI / 9);
  c.fillStyle = tint;
  c.font = `800 ${heading.length > 13 ? 96 : 116}px 'Segoe UI', Arial, sans-serif`;
  c.textAlign = "center";
  c.fillText(heading, 0, 0);
  c.font = "700 40px 'Segoe UI', Arial, sans-serif";
  c.fillText(sub, 0, 66);
  c.restore();
}

function draw(
  canvas: HTMLCanvasElement, spec: FlyerSpec,
  lines: CheckedLine[], logo: HTMLImageElement | null, compliant: boolean,
  bundle: (CheckedLine & { action: string }) | null,
  now: Date, draft: string | undefined,
) {
  const c = canvas.getContext("2d");
  if (!c) return;

  canvas.width = W * SCALE;
  canvas.height = H * SCALE;
  c.setTransform(SCALE, 0, 0, SCALE, 0, 0);

  c.fillStyle = "#ffffff";
  c.fillRect(0, 0, W, H);

  /* ---- header ---- */
  c.fillStyle = RED;
  c.fillRect(0, 0, W, 300);

  if (logo) {
    const lw = 132;
    const lh = (logo.naturalHeight / logo.naturalWidth) * lw || 132;
    c.drawImage(logo, 72, 62, lw, lh);
  }

  c.fillStyle = "rgba(255,255,255,.82)";
  c.font = "600 24px 'Segoe UI', Arial, sans-serif";
  c.letterSpacing = "3px";
  c.fillText((spec.eyebrow ?? "Mortgage Renewal").toUpperCase(), 72, 218);
  c.letterSpacing = "0px";

  c.fillStyle = "#ffffff";
  c.font = "800 52px 'Segoe UI', Arial, sans-serif";
  c.fillText(spec.title, 72, 272);

  /* ---- headline ---- */
  let y = 384;
  c.fillStyle = INK;
  c.font = "800 60px 'Segoe UI', Arial, sans-serif";
  y = wrap(c, spec.subtitle, 72, y, W - 144, 70);

  if (spec.customer) {
    c.fillStyle = "#71717a";
    c.font = "400 27px 'Segoe UI', Arial, sans-serif";
    const who = spec.segment ? `${spec.customer} · ${spec.segment}` : spec.customer;
    c.fillText(`Prepared for ${who}`, 72, y + 16);
    y += 52;
  }

  /* ---- offers ---- */
  y += 40;
  for (const line of lines) {
    const bad = line.verdict !== "ok";
    const rowH = 108;

    c.fillStyle = bad ? "#fff5f5" : "#faf8f6";
    roundRect(c, 72, y, W - 144, rowH, 14);
    c.fill();

    c.fillStyle = bad ? "#b00d14" : RED;
    roundRect(c, 72, y, 6, rowH, 3);
    c.fill();

    // Status glyph: a tick for an approved line, a warning for a breach.
    c.fillStyle = bad ? "#b00d14" : "#0f766e";
    c.font = "800 34px 'Segoe UI', Arial, sans-serif";
    c.fillText(bad ? "!" : "✓", 108, y + 56);

    c.fillStyle = INK;
    c.font = "700 34px 'Segoe UI', Arial, sans-serif";
    c.fillText(line.headline, 158, y + 50);

    c.fillStyle = bad ? "#b00d14" : "#71717a";
    c.font = "400 23px 'Segoe UI', Arial, sans-serif";
    c.fillText(bad ? line.reason : (line.detail || line.reason), 158, y + 84);

    y += rowH + 16;
  }

  /* ---- countdown, then the bundle path ----
     The approval routing that used to sit here (APPROVAL REQUIRED / who signs
     it off) has been removed deliberately. It is internal workflow: the
     customer cannot act on it, and naming an internal committee on customer
     artwork invites questions no branch wants to field. The approver is still
     carried on the spec and shown to staff in the breach panel. */
  const days = daysUntil(spec.expiry, now);

  y += 24;
  if (days !== null) {
    y = drawCountdown(c, 72, y, W - 144, days, spec.expiry) + 20;
  } else if (spec.expiry) {
    c.fillStyle = "#faf8f6";
    roundRect(c, 72, y, W - 144, 96, 14);
    c.fill();
    c.fillStyle = "#71717a";
    c.font = "700 19px 'Segoe UI', Arial, sans-serif";
    c.letterSpacing = "2px";
    c.fillText("OFFER EXPIRES", 100, y + 36);
    c.letterSpacing = "0px";
    c.fillStyle = INK;
    c.font = "700 28px 'Segoe UI', Arial, sans-serif";
    c.fillText(spec.expiry, 100, y + 72);
    y += 116;
  }

  if (bundle) {
    y = drawBundle(c, 72, y, W - 144, bundle) + 20;
  }

  /* ---- conditions ---- */
  y += 12;
  c.fillStyle = "#71717a";
  c.font = "400 19px 'Segoe UI', Arial, sans-serif";
  for (const cond of (spec.conditions ?? []).slice(0, 2)) {
    y = wrap(c, `• ${cond}`, 72, y, W - 144, 26);
  }

  /* ---- disclaimer ---- */
  c.fillStyle = "#a1a1aa";
  c.font = "400 17px 'Segoe UI', Arial, sans-serif";
  c.fillText(
    rebrandText("Synthetic demonstration material. Not a real CFC Bank offer, rate or product.", currentBrand()),
    72, H - 44,
  );

  /* ---- non-compliance watermark ----
     Drawn last and across the artwork, so a breaching flyer cannot be screenshot
     and passed off as approved. A draft stamp is drawn on the same terms: an
     internally generated draft leaving the building as a PNG has to carry the
     fact that nobody has approved the price on it. */
  if (!compliant) {
    stamp(c, "NOT APPROVED", "BREACHES RP-003", "rgba(176,13,20,.13)");
  } else if (draft) {
    stamp(c, "DRAFT", draft, "rgba(26,26,28,.10)");
  }
}

/* ------------------------------------------------------------- component --- */

/**
 * The flyer.
 *
 * `catalogue`, `now` and `draft` are all optional and all default to the
 * behaviour this component already had. They exist for the snapshot dashboard,
 * which must not make a request (`catalogue`), must measure the countdown from
 * its snapshot date rather than the wall clock (`now`), and produces a flyer
 * explicitly for internal review rather than for a customer (`draft`).
 */
export function Flyer({ spec, catalogue: supplied, now, draft }: {
  spec: FlyerSpec;
  catalogue?: CatalogueOffer[];
  now?: Date;
  draft?: string;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const catalogue = useOfferCatalogue(supplied);
  const [logo, setLogo] = useState<HTMLImageElement | null>(null);
  const brand = useBrand();
  RED = cssVar("--brand", "#ec111a");

  useEffect(() => {
    const img = new Image();
    img.onload = () => setLogo(img);
    img.onerror = () => setLogo(null);
    img.src = brand.assets.mark;
  }, [brand]);

  const lines = useMemo(
    () => (spec.offers ?? []).map((l) => checkLine(l, catalogue, spec.segment)),
    [spec, catalogue],
  );
  const breaches = lines.filter((l) => l.verdict !== "ok");
  // Until the catalogue loads there is nothing to check against, so the flyer is
  // not claimed to be compliant.
  const compliant = catalogue.length > 0 && breaches.length === 0;

  /**
   * The bundle path is checked exactly like a presented offer, and dropped
   * rather than drawn if it fails.
   *
   * It is built from a catalogue entry so it should always pass — which is the
   * point of checking it anyway. A cross-sell that silently bypassed the policy
   * gate would be the easiest place in the app for an unapproved number to
   * reach a customer.
   */
  const bundle = useMemo(() => {
    if (!spec.bundle || catalogue.length === 0) return null;
    const checked = checkLine(spec.bundle, catalogue, spec.segment);
    return checked.verdict === "ok"
      ? { ...checked, action: spec.bundle.action }
      : null;
  }, [spec, catalogue]);

  useEffect(() => {
    if (canvasRef.current) {
      draw(canvasRef.current, spec, lines, logo, compliant, bundle, now ?? new Date(), draft);
    }
  }, [spec, lines, logo, compliant, bundle, now, draft]);

  function download() {
    canvasRef.current?.toBlob((blob) => {
      if (!blob) return;
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      const who = (spec.customer ?? "renewal-offer").replace(/[^a-z0-9]+/gi, "-");
      a.href = url;
      a.download = `${who.toLowerCase()}-flyer${
        compliant ? (draft ? "-DRAFT" : "") : "-NOT-APPROVED"}.png`;
      a.click();
      URL.revokeObjectURL(url);
    }, "image/png");
  }

  return (
    <div className="flyer">
      <div className="flyer-bar">
        <span className={`flyer-status ${compliant ? "ok" : "bad"}`}>
          {catalogue.length === 0 ? "Checking against RP-003…"
            : compliant ? (draft
              ? "✓ Within the RP-003 offer catalogue · draft for review, not approved pricing"
              : "✓ Within the RP-003 offer catalogue")
            : `${breaches.length} breach${breaches.length > 1 ? "es" : ""} of RP-003`}
        </span>
        <button className="flyer-download" onClick={download}>
          Download PNG
        </button>
      </div>

      <canvas ref={canvasRef} className="flyer-canvas"
              role="img" aria-label={`${spec.title} — ${spec.subtitle}`} />

      {breaches.length > 0 && (
        <div className="flyer-breaches">
          <div className="flyer-breaches-head">Why this cannot be presented</div>
          <ul>
            {breaches.map((b, i) => (
              <li key={i}>
                <strong>{b.headline}</strong> — {b.reason}
                {b.offer && (
                  <span className="flyer-fix"> Permitted: {b.offer.name}, up to{" "}
                    {b.offer.max_bps > 0 ? `${b.offer.max_bps} bps` : ""}
                    {b.offer.max_bps > 0 && b.offer.max_cash > 0 ? " plus " : ""}
                    {b.offer.max_cash > 0
                      ? `CAD ${b.offer.max_cash.toLocaleString("en-CA")}` : ""}
                    , approved by {b.offer.approver}.
                  </span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
