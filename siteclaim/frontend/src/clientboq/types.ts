// TypeScript mirror of the client_boq contracts (backend/client_boq/models.py) and the
// response envelopes assembled in backend/client_boq/router.py.
//
// Kept in its own module, mirroring the backend: client_boq is a self-contained capability
// beside the procurement pipeline, so its types never enter src/types.ts.

// ---------------------------------------------------------------------------
// Departure status vocabulary — the single lifecycle field on a register line.
// WHO writes each value is the whole point of this module, so the union is
// annotated with its author (see backend/client_boq/models.py).
// ---------------------------------------------------------------------------
export type DepartureStatus =
  | "rule_flagged"      // deterministic rule code — a numeric threshold breached
  | "candidate"         // an AI-proposed qualitative match awaiting a verdict
  | "uncovered"         // a clause that matched no criterion
  | "unresolved"        // a criterion no clause resolved
  | "citation_failed"   // a cited clause not found / not supported in the documents
  | "confirmed"         // a human accepted the departure  (approve endpoint ONLY)
  | "dismissed";        // a human rejected the departure  (approve endpoint ONLY)

export type HumanVerdict = "confirmed" | "dismissed";

// Which check produced a register line.
export type DepartureSource = "criteria" | "scope_alignment" | "program" | "cashflow";

export interface DepartureItem {
  item: number;
  clause: string;
  criterion_id: string;
  category: string;
  clause_area: string;
  extracted_value: string;
  cited_text: string;
  amendment_proposal: string;
  rationale: string;
  proposed_position: string;
  status: DepartureStatus;
  source: DepartureSource;
  kind: string;
  rule_ref: string;
  citation_note: string;
  client_response: string;
  contractor_response: string;
  register_status: string; // "open" | "closed"
}

export interface AlignedItem {
  criterion_id: string;
  clause_area: string;
  clause: string;
  extracted_value: string;
  why: string;
}

export interface CashflowPoint {
  period: string;
  inflow: number;
  outflow: number;
  net: number;
  cumulative: number;
}

export interface CashflowSection {
  points: CashflowPoint[];
  negative_periods: string[];
  working_capital_peak: number; // most-negative cumulative — the funding requirement
  findings: string[];
  assumptions: string[];
}

// The register as the router presents it: actionable lines first, the unresolved
// criteria grouped, the aligned + cashflow sections beside them. `items` keeps the
// full canonical list — its stable item numbers are what /review/approve references.
export interface RegisterView {
  set_id: string;
  project: string;
  package: string;
  line_items: DepartureItem[];
  unresolved: {
    count: number;
    criteria: { item: number; criterion_id: string; clause_area: string }[];
  };
  aligned: AlignedItem[];
  cashflow: CashflowSection | null;
  items: DepartureItem[];
}

export interface ReviewResult {
  set_id: string;
  slice: string;
  status_counts: Partial<Record<DepartureStatus, number>>;
  review_approved: boolean;
  register: RegisterView;
}

export interface GateState {
  set_id: string;
  review_approved: boolean;
}

// ---------------------------------------------------------------------------
// ESTIMATE — scope (step 1) and its gate
// ---------------------------------------------------------------------------
export type ScopeNoteKind = "inclusion" | "exclusion" | "ambiguity" | "conflict" | "assumption";

export interface ScopeReviewNote {
  kind: ScopeNoteKind | string;
  text: string;
  source: "draft" | "register" | string; // "register" = deterministically injected, never AI
}

export interface ScopeReviewResult {
  summary: string;
  notes: ScopeReviewNote[];
  clarifying_questions: string[];
}

export interface ScopeResult {
  set_id: string;
  review_approved: boolean;
  scope_approved: boolean;
  summary_of_record: string;
  scope: ScopeReviewResult;
  amended_summary: string;
}

export interface ScopeGateState {
  set_id: string;
  scope_approved: boolean;
  summary_of_record: string;
}

// ---------------------------------------------------------------------------
// ESTIMATE — the pricing schedule (input) and the priced estimate (output)
// ---------------------------------------------------------------------------
export interface ResourceLine {
  description: string;
  resource_ref: string;             // rate_id in rates.csv (blank when inline)
  inline_rate: number | null;
  qty: number;
  unit: string;
  productivity: number | null;      // output units per hour
}

export type ItemCategory = "direct" | "indirect";
export type IndirectBasis = "lump" | "per_week" | "pct_of_direct";

export interface ScheduleItem {
  item_id: string;
  description: string;
  category: string;                 // "direct" | "indirect" | anything else -> flagged, never guessed
  unit: string;
  lines: ResourceLine[];
  basis: string;                    // indirect: lump | per_week | pct_of_direct
  amount: number | null;            // lump
  rate: number | null;              // per_week rate
  pct: number | null;               // pct_of_direct
}

export interface EstimateSchedule {
  duration_weeks: number | null;
  items: ScheduleItem[];
}

export interface CostLine {
  item_id: string;
  description: string;
  resource_ref: string;
  qty: number;
  unit: string;
  productivity: number | null;
  hours: number | null;             // qty ÷ productivity, when productivity is given
  rate: number;
  rate_source: "csv" | "inline" | "missing" | string;
  amount: number;
}

export interface CostActivity {
  item_id: string;
  description: string;
  category: string;
  unit: string;
  lines: CostLine[];
  activity_total: number;
}

export interface IndirectLine {
  item_id: string;
  label: string;
  basis: string;
  detail: string;                   // how it was computed — hand-checkable
  amount: number;
}

export type EstimateFlagKind =
  | "missing_rate"
  | "zero_or_negative_qty"
  | "empty_activity"
  | "rate_outlier"
  | "unclassified_item";

export interface EstimateFlag {
  kind: EstimateFlagKind | string;
  item_id: string;
  message: string;
}

export interface EstimateTotals {
  total_direct: number;
  total_indirect: number;
  total_cost: number;
  margin_pct: number;
  price: number;
  margin_amount: number;            // price − total_cost; a readout, never a verdict
}

export interface Estimate {
  set_id: string;
  duration_weeks: number | null;
  activities: CostActivity[];
  indirects: IndirectLine[];
  unclassified: ScheduleItem[];
  flags: EstimateFlag[];
  totals: EstimateTotals;
}

export interface EstimateResult {
  set_id: string;
  totals: EstimateTotals;
  flag_counts: Partial<Record<EstimateFlagKind, number>>;
  estimate: Estimate;
}

// ---------------------------------------------------------------------------
// ESTIMATE — the offer letter (a draft; nothing sends it)
// ---------------------------------------------------------------------------
export interface LetterMeta {
  company_name: string;
  company_address: string;
  contact_name: string;
  contact_number: string;
  project: string;
  client_name: string;
  date: string;
  ref: string;
  validity_days: number;
}

export interface LetterAppendixItem {
  text: string;
  source: "register" | "draft" | string;
}

export interface PricingScheduleRow {
  item_id: string;
  description: string;
  total: number;
}

export interface LetterOfOffer {
  set_id: string;
  meta: LetterMeta;
  intro: string;
  price: number;
  price_str: string;
  inclusions: string[];
  exclusions: string[];
  pricing_schedule: PricingScheduleRow[];
  appendix: LetterAppendixItem[];
  markdown: string;
}

export interface LetterResult {
  set_id: string;
  price: number;
  price_str: string;
  markdown: string;
  letter: LetterOfOffer;
}

// ---------------------------------------------------------------------------
// The rate book (client_boq/data/rates.csv) — the hand-editable v1 rate source.
// ---------------------------------------------------------------------------
export interface RateRow {
  rate_id: string;
  category: string;
  code: string;
  description: string;
  unit: string;
  rate: number;
  currency: string;
  source: string;
  notes: string;
}

// ---------------------------------------------------------------------------
// The shared job envelope. DEMO returns {status:"done", result} inline (no job,
// no network); live returns a job_id to poll.
// ---------------------------------------------------------------------------
export type JobKind = "review" | "scope" | "estimate";
export type JobStatus = "queued" | "running" | "done" | "error";

export interface JobState<T> {
  job_id: string | null;
  kind: JobKind | string;
  status: JobStatus;
  stage: string;
  error: string | null;
  result: T | null;
  warnings: string[];
}
