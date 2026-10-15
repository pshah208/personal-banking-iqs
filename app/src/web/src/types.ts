export type IQId = "work" | "fabric" | "foundry" | "web";
export type IQStatus = "idle" | "active" | "done";

export interface IQMeta {
  id: IQId;
  name: string;
  source: string;
  blurb: string;
}

export interface IQState extends IQMeta {
  status: IQStatus;
  detail: string;
}

export interface Citation {
  kind?: "url" | "file";
  text?: string;
  title?: string;
  url?: string;
  fileId?: string;
}

export interface ChatMessage {
  role: "user" | "assistant" | "error";
  content: string;
  citations?: Citation[];
  layers?: IQId[];
  /** True while tokens are still arriving. */
  streaming?: boolean;
}

export interface StoryColumnItem {
  name: string;
  detail: string;
}

export interface StoryColumn {
  title: string;
  tag: string;
  items: StoryColumnItem[];
}

export interface Chapter {
  id: string;
  title: string;
  kicker: string;
  layout: "persona" | "architecture" | "iq" | "video";
  body: string;
  points?: string[];
  columns?: StoryColumn[];
  assurances?: string[];
  note?: string;
  /** What the business loses without this layer. Argues for it, rather than describing it. */
  stakes?: string;
  iq?: IQId | "all";
  prompt: string | null;
  expect?: string[];
}

export interface Persona {
  name: string;
  title: string;
  org: string;
  goal: string;
  objectives: string[];
  points?: string[];
}

export interface RolePersona {
  goal: string;
  objectives: string[];
  points: string[];
}

export interface Suggestion {
  /** Which layer the question exercises; "all" needs more than one. */
  iq: IQId | "all";
  text: string;
}

/** One offer line on a flyer, as the agent proposes it. */
export interface FlyerLine {
  headline: string;
  detail?: string;
  /** RP-003 offer code the line claims to sit under, e.g. "OFR-01". */
  code?: string;
  /** Explicit magnitudes, when the agent supplies them rather than only prose. */
  bps?: number;
  cash?: number;
}

/** An offer the customer could unlock, plus the action that unlocks it. */
export interface BundleOffer extends FlyerLine {
  /** Customer-facing action, e.g. "Move your investments to CFC Bank". */
  action: string;
}

export interface FlyerSpec {
  title: string;
  subtitle: string;
  eyebrow?: string;
  customer?: string;
  segment?: string;
  offers: FlyerLine[];
  /**
   * A conditional cross-sell path the customer could qualify for by bundling
   * products they do not already hold. Deliberately separate from `offers`:
   * RP-003 does not allow discounts to stack, so this is drawn as an
   * alternative to the offer above, never as an addition to it.
   */
  bundle?: BundleOffer;
  approval?: string;
  conditions?: string[];
  expiry?: string;
}

/** An entry in the RP-003 approved offer catalogue, served by /api/offers. */
export interface CatalogueOffer {
  code: string;
  name: string;
  max_bps: number;
  max_cash: number;
  segments: string[];
  approver: string;
  condition: string;
}

export interface Story {
  persona: Persona;
  personaByRole?: Record<string, RolePersona>;
  chapters: Chapter[];
  suggestions: Suggestion[];
}

export interface Me {
  name: string;
  upn: string;
  oid: string;
  roles: string[];
  role: string;
  jobTitle: string;
  department: string;
}

export interface AppConfig {
  tenantId: string;
  apiScope: string;
  agentName: string;
  mockMode: boolean;
  bank: string;
  disclaimer: string;
}

export interface FabricCapacity {
  configured: boolean;
  name?: string;
  sku?: string;
  region?: string;
  rawState?: string;
  state: "active" | "paused" | "resuming" | "pausing" | "unknown";
  canOperate: boolean;
  error?: string;
}
