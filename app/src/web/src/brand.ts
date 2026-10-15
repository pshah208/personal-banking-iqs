/**
 * Bank branding for the demo - data-driven and switchable at runtime.
 *
 * Brands are not compiled in. At start-up `loadBrands()` reads
 * `/brand/brands.json`, a manifest written by `tools/brand/fetch_brand.py`
 * (run by deploy.ps1 -Bank "<name>" or the GitHub "Deploy" workflow). Each
 * entry points at its own pack under `/brand/<id>/` (lockup, mark, favicon).
 * When the manifest is missing, the built-in fictional "CFC Bank" pack is
 * used so the app always renders.
 *
 * Every brand-dependent colour in the CSS reads from the custom properties set
 * here, and every brand-dependent image comes from `assets`.
 *
 * The data, agents and story are the same for every bank; only presentation
 * changes. Source copy is authored for the fictional "CFC Bank" and is
 * relabelled client-side by `rebrand`. Agents refer to "the Bank".
 *
 * This module is deliberately React-free so plain-node tests can import it;
 * the `useBrand` hook lives in ./useBrand.ts.
 */

export type BrandId = string;

export interface BrandColors {
  brand: string;
  brandDeep: string;
  brandTint: string;
  brandLine: string;
  brandInk: string;
  accent: string;
  /** Accent used as text on white - must stay legible (a yellow accent is not). */
  accentInk: string;
  accentFg: string;
}

export interface Brand {
  id: BrandId;
  /** Full name, e.g. "BMO Personal Banking". */
  name: string;
  /** How narrative copy names the bank, e.g. "BMO" in "BMO's renewal book". */
  short: string;
  /** Other names the bank goes by in public offers (lower case). */
  aliases: string[];
  colors: BrandColors;
  assets: { lockup: string; mark: string; favicon: string };
}

/** The fictional bank the source copy was written for. */
export const AUTHORED_ID = "cfc";
const AUTHORED_NAMES = ["CFC Bank"];

const CFC: Brand = {
  id: AUTHORED_ID,
  name: "CFC Bank",
  short: "CFC Bank",
  aliases: ["cfc bank", "cfc"],
  colors: {
    brand: "#034694", brandDeep: "#012a5e", brandTint: "#e7eef7", brandLine: "#c3d3e8",
    brandInk: "#011d40", accent: "#333333", accentInk: "#333333", accentFg: "#ffffff",
  },
  assets: { lockup: "/brand/cfc/lockup.png", mark: "/brand/cfc/mark.png", favicon: "/brand/cfc/favicon.png" },
};

let registry: Record<BrandId, Brand> = { [CFC.id]: CFC };
let order: BrandId[] = [CFC.id];
let defaultId: BrandId = CFC.id;

const STORAGE_KEY = "pbi.brand";
const HEX = /^#[0-9a-f]{6}$/i;

const hasDom = () => typeof document !== "undefined" && typeof window !== "undefined";

/* ------------------------------------------------------------ colours --- */

function rgb(hex: string): [number, number, number] {
  const n = parseInt(hex.replace("#", ""), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

function toHex([r, g, b]: [number, number, number]): string {
  return "#" + [r, g, b].map((c) => Math.max(0, Math.min(255, Math.round(c))).toString(16).padStart(2, "0")).join("");
}

/** Blend `hex` towards `toward` by `t` (0..1). */
function mix(hex: string, toward: string, t: number): string {
  const a = rgb(hex);
  const b = rgb(toward);
  return toHex([a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t]);
}

function luminance(hex: string): number {
  const lin = (c: number) => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  };
  const [r, g, b] = rgb(hex);
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
}

const contrastOnWhite = (hex: string) => 1.05 / (luminance(hex) + 0.05);

/** Fill any missing shade from the primary and accent, so a pack may specify only those two. */
export function completeColors(c: Partial<BrandColors> & { brand: string }): BrandColors {
  const brand = c.brand;
  const accent = c.accent && HEX.test(c.accent) ? c.accent : "#333333";
  let accentInk = c.accentInk && HEX.test(c.accentInk) ? c.accentInk : accent;
  for (let i = 0; i < 10 && contrastOnWhite(accentInk) < 4.5; i++) accentInk = mix(accentInk, "#000000", 0.15);
  const pick = (v: string | undefined, fallback: string) => (v && HEX.test(v) ? v : fallback);
  return {
    brand,
    brandDeep: pick(c.brandDeep, mix(brand, "#000000", 0.25)),
    brandTint: pick(c.brandTint, mix(brand, "#ffffff", 0.9)),
    brandLine: pick(c.brandLine, mix(brand, "#ffffff", 0.75)),
    brandInk: pick(c.brandInk, mix(brand, "#000000", 0.55)),
    accent,
    accentInk,
    accentFg: pick(c.accentFg, luminance(accent) > 0.45 ? mix(brand, "#000000", 0.55) : "#ffffff"),
  };
}

/* ----------------------------------------------------------- registry --- */

interface PackJson {
  id?: string;
  name?: string;
  short?: string;
  aliases?: string[];
  colors?: Partial<BrandColors>;
  assets?: Partial<Brand["assets"]>;
}

const asset = (id: string, file: string | undefined, fallback: string) => {
  if (!file) return fallback;
  return /^(https?:)?\//.test(file) ? file : `/brand/${id}/${file}`;
};

/** Validate one manifest entry; anything unusable is dropped rather than half-applied. */
export function normaliseBrand(p: PackJson): Brand | null {
  const id = (p.id ?? "").trim().toLowerCase();
  if (!/^[a-z0-9][a-z0-9-]{0,39}$/.test(id) || !p.name || !p.colors?.brand || !HEX.test(p.colors.brand)) return null;
  const short = (p.short || p.name).trim();
  const aliases = Array.from(new Set([short, p.name, ...(p.aliases ?? [])].map((a) => a.trim().toLowerCase()).filter(Boolean)));
  return {
    id,
    name: p.name.trim(),
    short,
    aliases,
    colors: completeColors(p.colors as BrandColors),
    assets: {
      lockup: asset(id, p.assets?.lockup, CFC.assets.lockup),
      mark: asset(id, p.assets?.mark, CFC.assets.mark),
      favicon: asset(id, p.assets?.favicon, CFC.assets.favicon),
    },
  };
}

/** Load `/brand/brands.json`. Never throws - a missing or bad manifest leaves CFC Bank in place. */
export async function loadBrands(url = "/brand/brands.json"): Promise<void> {
  try {
    const res = await fetch(url, { cache: "no-cache" });
    if (!res.ok) return;
    const doc = (await res.json()) as { default?: string; order?: string[]; brands?: PackJson[] };
    const next: Record<BrandId, Brand> = {};
    for (const p of doc.brands ?? []) {
      const b = normaliseBrand(p);
      if (b) next[b.id] = b;
    }
    if (!Object.keys(next).length) return;
    const listed= (doc.order ?? []).filter((id) => id in next);
    registry = next;
    order = [...listed, ...Object.keys(next).filter((id) => !listed.includes(id))];
    defaultId = doc.default && doc.default in next ? doc.default : order[0];
  } catch {
    /* offline or malformed - keep the built-in brand */
  }
}

export const brandOrder = (): BrandId[] => [...order];
export const defaultBrand = (): BrandId => defaultId;
export const isBrandId = (v: unknown): v is BrandId => typeof v === "string" && v in registry;
export const getBrand = (id: BrandId): Brand => registry[id] ?? registry[defaultId] ?? CFC;

/** `?bank=rbc` wins (shareable demo links), then the last choice, then the deployed default. */
export function initialBrand(): BrandId {
  if (!hasDom()) return defaultId;
  const fromUrl = new URLSearchParams(window.location.search).get("bank");
  if (isBrandId(fromUrl)) return fromUrl;
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (isBrandId(stored)) return stored;
  } catch {
    /* storage unavailable */
  }
  return defaultId;
}

/** Push a brand into the document: CSS variables, favicon, title and persistence. */
export function applyBrand(id: BrandId): void {
  if (!hasDom()) return;
  const b = getBrand(id);
  const root = document.documentElement;
  root.dataset.brand = b.id;
  const set = (k: string, v: string) => root.style.setProperty(k, v);
  set("--brand", b.colors.brand);
  set("--brand-rgb", rgb(b.colors.brand).join(" "));
  set("--brand-deep", b.colors.brandDeep);
  set("--brand-tint", b.colors.brandTint);
  set("--brand-line", b.colors.brandLine);
  set("--brand-ink", b.colors.brandInk);
  set("--accent", b.colors.accent);
  set("--accent-ink", b.colors.accentInk);
  set("--accent-fg", b.colors.accentFg);

  const icon = document.querySelector<HTMLLinkElement>("link[rel='icon']");
  if (icon) icon.href = b.assets.favicon;
  document.title = `${b.short} · Personal Banking Intelligence`;
  try {
    window.localStorage.setItem(STORAGE_KEY, b.id);
  } catch {
    /* storage unavailable */
  }
  window.dispatchEvent(new CustomEvent("brandchange", { detail: b.id }));
}

/** Current brand id (charts, flyer render, offer copy). */
export function currentBrand(): BrandId {
  const id = hasDom() ? document.documentElement.dataset.brand : undefined;
  return isBrandId(id) ? id : defaultId;
}

export function cssVar(name: string, fallback: string): string {
  if (!hasDom()) return fallback;
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}

const escapeRe = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const AUTHORED_RE = new RegExp(`\\b(?:${AUTHORED_NAMES.map(escapeRe).join("|")})\\b`, "g");

/** Relabel text authored for CFC Bank so it names the selected bank instead. */
export function rebrandText(text: string, id: BrandId): string {
  if (id === AUTHORED_ID || !text) return text;
  return text.replace(AUTHORED_RE, getBrand(id).short);
}

/** Deep-relabel every string in a JSON-shaped value (story, config). */
export function rebrand<T>(value: T, id: BrandId): T {
  if (id === AUTHORED_ID) return value;
  const walk = (v: unknown): unknown => {
    if (typeof v === "string") return rebrandText(v, id);
    if (Array.isArray(v)) return v.map(walk);
    if (v && typeof v === "object") {
      return Object.fromEntries(Object.entries(v as Record<string, unknown>).map(([k, x]) => [k, walk(x)]));
    }
    return v;
  };
  return walk(value) as T;
}
