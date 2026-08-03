// Types for the /client-boq API. Every shape here mirrors a payload the backend actually
// returns — read off client_boq/router.py and client_boq/models.py, not invented to suit the
// design. Where the design asks for something the backend does not send, the derivation lives
// in a named helper (see `authorOf`) rather than a hopeful optional field.

// --- gates & sets ----------------------------------------------------------
export interface GateStates {
  manifest: boolean;
  review: boolean;
  scope: boolean;
}

/** Desk metadata for one tender. The close-date fields are A FINDING, not form fields: read
 *  from the Conditions of Tender with a citation, honestly `not_found` when the read fails,
 *  and only overwritable by a human confirmation. */
export interface SetMeta {
  owner_id: string;
  client: string;
  package: string;
  archived: boolean;
  outcome: "live" | "submitted" | "won" | "lost";
  close_date: string; // ISO or ""
  close_date_status: "reading" | "found" | "not_found" | "confirmed";
  close_date_clause: string;
  close_date_page: number | null;
  close_date_part_id: string;
  close_date_quote: string;
  close_date_confirmed_by: string;
  query_cutoff: string; // ISO or ""
  last_touched_by: string;
  last_touched_at: string | null;
}

/** The counts the home cards and filters derive from. Computed server-side because they must
 *  agree with what the gates refuse — `blocked` is the same arithmetic the 409s are built on. */
export interface SetCounts {
  undecided: number;
  citation_failed: number;
  unaccepted_fallbacks: number;
  open_rfis: number;
}

export interface SetRow {
  set_id: string;
  name: string;
  created_at: string;
  parts: number;
  tier: number | null;
  gates: GateStates;
  price: number | null;
  has_letter: boolean;
  meta: SetMeta;
  counts: SetCounts;
  blocked: boolean;
}

// --- the team (named profiles, not accounts) --------------------------------
export interface TeamMember {
  member_id: string;
  name: string;
  initials: string;
  colour: string;
  role: string;
  archived: boolean;
  created_at?: string;
}

// --- criteria & rates editing ----------------------------------------------
/** A criterion row with its editing metadata — what the Criteria screen renders. */
export interface CriterionRow {
  id: string;
  category_id: string;
  category: string;
  clause_area: string;
  acceptable_position: string;
  why_it_matters: string;
  red_flag: string;
  is_placeholder: boolean;
  enabled: boolean;
  sort_order: number;
  updated_by: string;
  updated_at: string | null;
}

export interface RateRowFull {
  rate_id: string;
  category: string;
  code: string;
  description: string;
  unit: string;
  rate: number;
  currency: string;
  source: string;
  notes: string;
  archived: boolean;
  updated_by: string;
  updated_at: string | null;
}

export interface RatesResponse {
  count: number;
  rows: RateRowFull[];
  categories: string[];
  seed_duplicates: string[];
}

// --- app-wide settings (the AI model) --------------------------------------
export interface LLMSettingsResponse {
  provider: string; // "" = auto
  model_anthropic: string;
  model_deepseek: string;
  providers: string[];
  effective: {
    text_provider: string;
    vision_provider: string; // always "anthropic" — DeepSeek rejects images
    model_anthropic: string;
    model_deepseek: string;
  };
  rows: { key: string; value: string; updated_by: string; updated_at: string | null }[];
}

export interface GateState {
  set_id: string;
  review_approved: boolean;
  queries_raised?: string[];
  open_queries?: number;
}

export interface ManifestGateState {
  set_id: string;
  manifest_approved: boolean;
  parts: number;
  tier: number;
}

export interface ScopeGateState {
  set_id: string;
  scope_approved: boolean;
}

// --- jobs ------------------------------------------------------------------
export interface JobState {
  job_id?: string | null;
  kind: string;
  status: "queued" | "running" | "done" | "error" | "cancelled";
  stage: string;
  error?: string | null;
  result?: unknown;
  warnings?: string[];
  done?: number;
  total?: number;
  /** A stop was asked for and the current stage has not finished. `cancel_requested` true with
   *  status still "running" is the state the strip reads to say "stopping at the next step" —
   *  which is true — rather than "stopped", which would not be. */
  cancel_requested?: boolean;
}

// --- ingest: the manifest (gate 1) ----------------------------------------
export interface PartSpec {
  /** Stable identity within a set, `NN-abbr`. Computed server-side and sent explicitly —
   *  never re-derived here, or two places would own one identity rule. */
  part_id: string;
  n: number;
  abbr: string;
  slug: string;
  title: string;
  /** 1-based INCLUSIVE physical pages of the SOURCE document. */
  start: number;
  end: number;
  category: string;
  scanned: boolean;
  source_doc: string;
  rev: number;
}

export interface PageSpan {
  start: number;
  end: number;
}

/** Where the split breaks, computed by the same backend function the manifest gate validates
 *  with — so the count beside Approve can never disagree with what the gate would refuse on. */
export interface CoverageDetail {
  pages: number;
  covered: number;
  gaps: PageSpan[];
  overlaps: (PageSpan & { parts: number[] })[];
}

export interface Manifest {
  set_id: string;
  source_doc: string;
  pages: number;
  tier: number;
  tier_reason: string;
  approved: boolean;
  /** The covered page count. `coverage_detail` is the one with the breaks in it. */
  coverage: number;
  coverage_detail: CoverageDetail;
  parts: PartSpec[];
}

// --- ingest: the parts -----------------------------------------------------
export interface StrategyFlag {
  kind: string;
  clause: string;
  page: number | null;
  quote: string;
  part_id?: string;
  source_doc?: string;
}

export interface PartRow {
  part_id: string;
  n: number;
  abbr: string;
  title: string;
  category: string;
  pages: string; // "5-16", in the source document's numbering
  page_count: number;
  scanned: boolean;
  source_doc: string;
  readable: boolean;
  summary: string;
}

export interface PartsResponse {
  set_id: string;
  count: number;
  unreadable: number;
  strategy_flags: StrategyFlag[];
  penalises_qualifications: boolean;
  parts: PartRow[];
}

export interface PartContext {
  part_id: string;
  title: string;
  category: string;
  readable: boolean;
  summary: string;
  key_points: string[];
  obligations: string[];
  commercial_flags: string[];
  feeds: string[];
  strategy_flags: StrategyFlag[];
  notes: string;
  /** Whose words this card is in. Editing stamps it "user"; re-interpreting puts "ai" back,
   *  because that genuinely is a fresh machine reading. */
  badge: "ai" | "user";
}

export interface PartDetail {
  set_id: string;
  part: PartSpec;
  pdf_path: string;
  context: PartContext;
  card: string;
}

// --- the document pane -----------------------------------------------------
/** A rectangle as fractions of page width and height, so it overlays at any zoom. */
export interface Highlight {
  page: number;
  x0: number;
  y0: number;
  x1: number;
  y1: number;
}

export interface SearchHit {
  page: number;
  highlights: Highlight[];
}

export interface SearchResponse {
  set_id: string;
  part_id: string;
  query: string;
  /** false = there is no text layer. Different from "no matches", and said differently. */
  searchable: boolean;
  pages: string;
  count: number;
  hits: SearchHit[];
  note: string;
}

// --- review: the register --------------------------------------------------
export type RegisterStatus =
  | "rule_flagged"
  | "candidate"
  | "uncovered"
  | "unresolved"
  | "citation_failed"
  | "confirmed"
  | "dismissed"
  | "query";

export type RegisterSource = "criteria" | "scope_alignment" | "program" | "cashflow";

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
  status: RegisterStatus;
  source: RegisterSource;
  kind: string;
  rule_ref: string;
  citation_note: string;
  /** MEASURED by s08's physical guard — never the page the model claimed. */
  page: number | null;
  client_response: string;
  contractor_response: string;
  register_status: "open" | "closed";
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
  working_capital_peak: number;
  findings: string[];
  assumptions: string[];
}

export interface UnresolvedCriterion {
  item: number;
  criterion_id: string;
  clause_area: string;
}

export interface Register {
  set_id: string;
  project: string;
  package: string;
  line_items: DepartureItem[];
  unresolved: { count: number; criteria: UnresolvedCriterion[] };
  aligned: AlignedItem[];
  cashflow: CashflowSection | null;
  items: DepartureItem[];
}

/** Set when the register describes a DIFFERENT document from the one uploaded — which is what an
 *  offline DEMO run produces, and which otherwise just looks like a broken screen. */
export interface ParseMismatch {
  reviewed: string[];
  uploaded: string[];
  note: string;
}

export interface RegisterResponse {
  set_id: string;
  slice: string;
  status_counts: Record<string, number>;
  review_approved: boolean;
  register: Register;
  parse_mismatch: ParseMismatch | null;
}

// --- the acceptable-terms library ------------------------------------------
export interface Criterion {
  id: string;
  category_id: string;
  category: string;
  clause_area: string;
  acceptable_position: string;
  why_it_matters: string;
  red_flag: string;
  is_placeholder: boolean;
}

export interface CriteriaResponse {
  count: number;
  criteria: Criterion[];
  placeholders: Criterion[];
  thresholds: { id: string; rule: string; extract_field: string }[];
  /** Every criterion with its editing metadata — the Criteria screen's list. */
  rows: CriterionRow[];
}

// --- review: where each quotation physically sits --------------------------
export type LocationVerdict = "located" | "unverifiable" | "not_located";

export interface CitationRow {
  item: number;
  clause: string;
  cited_text: string;
  verdict: LocationVerdict;
  page: number | null;
  match: "exact" | "fragment" | "none";
  matched_text: string;
  highlights: Highlight[];
  note: string;
}

export interface CitationsResponse {
  set_id: string;
  checked: number;
  by_verdict: Partial<Record<LocationVerdict, number>>;
  citations: CitationRow[];
}

// --- RFI -------------------------------------------------------------------
export interface RFIItem {
  rfi_id: string;
  number: number;
  origin: string;
  register_item: number | null;
  part_id: string;
  clause: string;
  page: number | null;
  question: string;
  context: string;
  status: string;
  batch_id: string;
  answer: string;
  answered_by: string;
  raised_at: string;
  answered_at: string;
}

export interface RFIBatchRow {
  batch_id: string;
  ref: string;
  sent_at: string;
  letter_md?: string;
  items: RFIItem[];
}

export interface RFIsResponse {
  set_id: string;
  open: number;
  items: RFIItem[];
  batches: RFIBatchRow[];
}

// --- documents & revisions -------------------------------------------------
export interface DocumentRow {
  doc_id: string;
  seq: number;
  kind: string;
  filename: string;
  ref: string;
  received_at: string;
  applied: boolean;
}

export interface RevisionRow {
  part_id: string;
  rev: number;
  doc_id: string;
  kind: string;
  note: string;
  applied_at: string;
}

// --- estimate scope (gate 3) ----------------------------------------------
export interface ScopeNote {
  kind: string;
  text: string;
  source: "draft" | "register";
}

export interface ScopeDraft {
  summary: string;
  notes: ScopeNote[];
  clarifying_questions: string[];
}

export interface ScopeResponse {
  set_id: string;
  draft: ScopeDraft;
  amended_summary: string;
  approved: boolean;
}

// --- the scope of record, item by item (the freeze gate) -------------------
export type ScopeSection = "qualifications" | "fallbacks" | "logistics";
export type ScopeBadge = "ai" | "user";
export type ScopeGroup = "departure" | "rfi" | "addendum";

export interface ScopeItem {
  item_id: string;
  section: ScopeSection;
  title: string;
  /** Whose words these are. Editing always flips it to `user` — you edited it, you own it. */
  badge: ScopeBadge;
  /** Stands in for an answer the client never gave. */
  is_fallback: boolean;
  /** A fallback nobody accepted is NOT priced, and never gets the green rule. */
  accepted: boolean;
  text: string;
  source_ref: string;
  updated_at: string;
}

export interface ScopeSource {
  source_ref: string;
  group: ScopeGroup;
  label: string;
  meta: string;
  section: ScopeSection;
  text: string;
  mapped: boolean;
}

export interface ScopeItemsResponse {
  set_id: string;
  items: ScopeItem[];
  baseline: number;
  fallbacks_active: number;
  blocking: { item_id: string; title: string }[];
}

export interface ScopeSourcesResponse extends ScopeItemsResponse {
  sources: ScopeSource[];
}

// --- estimate: the priced build-up -----------------------------------------
// Every shape here mirrors client_boq/models.py. The cost lines carry a full trace on purpose —
// qty, rate, where the rate came from, and the amount — so a person can recompute any number by
// hand. That is the whole reason the estimate is deterministic code rather than a model call.

/** Where a rate came from. `missing` prices at 0 and raises a flag; it is never guessed. */
export type RateSource = "csv" | "inline" | "missing" | "";

export interface CostLine {
  item_id: string;
  description: string;
  resource_ref: string;
  qty: number;
  unit: string;
  productivity: number | null;
  hours: number | null;
  rate: number;
  rate_source: RateSource;
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
  basis: string; // lump | per_week | pct_of_direct
  /** How it was computed, in words — hand-checkable. */
  detail: string;
  amount: number;
}

export type EstimateFlagKind =
  | "missing_rate"
  | "zero_or_negative_qty"
  | "empty_activity"
  | "rate_outlier"
  | "unclassified_item";

/** Raised by the rule layer. Surfaced for the human, never blocking, never a verdict. */
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
  /** price − total_cost. A readout, not a "profitable / not" verdict. */
  margin_amount: number;
}

export interface Estimate {
  set_id: string;
  duration_weeks: number | null;
  activities: CostActivity[];
  indirects: IndirectLine[];
  unclassified: unknown[];
  flags: EstimateFlag[];
  totals: EstimateTotals;
}

export interface EstimateResponse {
  set_id: string;
  totals: EstimateTotals;
  flag_counts: Record<string, number>;
  estimate: Estimate;
}

// --- the offer letter ------------------------------------------------------
/** `register` = a confirmed departure, carried VERBATIM. `draft` = an AI condition from the
 *  scope. The distinction is the point: one is a decision already taken, the other a proposal. */
export type AppendixSource = "register" | "draft" | string;

export interface LetterAppendixItem {
  text: string;
  source: AppendixSource;
}

export interface PricingScheduleRow {
  item_id: string;
  description: string;
  total: number;
}

export interface LetterMeta {
  company_name: string;
  company_address: string;
  contact_name: string;
  contact_number: string;
  project: string;
  client_name: string;
  date: string;
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

export interface LetterResponse {
  set_id: string;
  price: number;
  price_str: string;
  markdown: string;
  letter: LetterOfOffer;
}

// ---------------------------------------------------------------------------
// The bridge (/bridge/*) — the join between this review and the procurement fork
// ---------------------------------------------------------------------------
// DUPLICATION, DELIBERATE. `SorItem`, `TradeWorkPackage` and `ScopePackages` also exist in
// src/types.ts, where procurement defines them. They are copied rather than imported because the
// two products keep separate type files by design: a cross-import is the beginning of a tangle,
// and the day procurement changes its shape we want a compile error here, not a silent drift in a
// screen nobody was editing. If these ever disagree with the backend, the backend wins — every
// shape below is read off backend/bridge/router.py and backend/schemas/models.py.

/** One priceable line of the bill. */
export interface SorItem {
  item_ref: string;
  description?: string | null;
  unit?: string | null;
  qty?: number | null;
  section?: string | null;
  clause_refs: string[];
}

export interface SectionMeta {
  code: string;
  title: string;
  item_count: number;
  section_trade: string;
}

/** The scope for one trade, split out of the bill. */
export interface TradeWorkPackage {
  trade: string;
  scope_summary: string;
  sor_items: SorItem[];
  source_refs: string[];
  sections: SectionMeta[];
}

export interface ScopePackages {
  project_name: string;
  packages: TradeWorkPackage[];
}

/** An extracted item the provenance guard refused: its section is not one the bill itself
 *  declares, so it never was a real bill line. Surfaced, never silently dropped. */
export interface UnrecognisedItem {
  item_ref: string;
  description: string;
  section: string;
  reason: string;
}

/** One part of the set, as a candidate for being the priced bill. `proposed` means its category
 *  is `pricing`; it is a PROPOSAL, and only `confirmed` reflects a human's choice. */
export interface BqCandidatePart {
  part_id: string;
  n: number;
  title: string;
  category: string;
  pages: number;
  scanned: boolean;
  has_pdf: boolean;
  source_doc: string;
  rev: number;
  proposed: boolean;
  confirmed: boolean;
}

export interface BqCandidates {
  set_id: string;
  parts: BqCandidatePart[];
  proposed: string[];
  confirmed: string[];
  /** Confirmed part ids that no longer exist in the set (a re-split dropped them). Shown, never
   *  silently discarded. */
  stale_confirmed: string[];
  message: string;
}

/** The bill split. Note the UI never calls this "scope": that word already means client_boq's
 *  estimate scope on this desk, and one strip cannot carry two unrelated things under one name. */
export interface BridgeSplitResponse {
  set_id: string;
  scope: ScopePackages;
  unrecognised_items: UnrecognisedItem[];
  /** Honest-degradation messages from the run — an unreadable part, a quarantined item. */
  notes: string[];
}

export interface BridgeSplitRead {
  set_id: string;
  scope: ScopePackages;
}

/** One routable package with its recommendation. `recommended_route` is ADVISORY — the AI
 *  proposes; `chosen_route` is null until a human decides, and the bridge records that decision in
 *  its own table rather than here. */
export interface BridgeRoutePackage {
  id?: number | null;
  package_key: string;
  trade: string;
  section?: string | null;
  section_title: string;
  scope_summary: string;
  recommended_route: string;
  rationale: string;
  signals: Record<string, number | boolean | string>;
  chosen_route?: string | null;
  decided_by: string;
  decided_at: string;
  source: string;
}

/** POST /route/analyze — runs the proposal. */
export interface BridgeRouteProposal {
  set_id: string;
  run_ref: string;
  packages: BridgeRoutePackage[];
  /** Shown, never blocking: an unanswered client query does not move the submission deadline. */
  open_queries: number;
  notes: string[];
}

/** GET /route/proposal — a pure read that never re-runs the analysis. An empty `packages` means
 *  "not yet run", which is a state and not an error. */
export interface BridgeRouteProposalRead {
  set_id: string;
  run_ref: string;
  packages: BridgeRoutePackage[];
  open_queries: number;
  review_approved: boolean;
  has_split: boolean;
}

export interface BridgeRouteDecision {
  package_key: string;
  chosen_route: string;
  decided_by: string;
  decided_at: string;
}

/** Both POST /route/confirm and GET /route/decisions return this shape, so a tab renders
 *  identically whether it just confirmed or is reading back after a reload. */
export interface BridgeRouteDecisions {
  set_id: string;
  run_ref: string;
  decisions: BridgeRouteDecision[];
  self_perform_packages: string[];
  sublet_packages: string[];
}

// ---------------------------------------------------------------------------
// Sourcing (/shortlist, /dispatch, …) — the sublet fork
// ---------------------------------------------------------------------------
// Copied from src/types.ts for the same reason the bridge shapes above are: separate type files
// by design. The backend is the authority for all of them.

export type Severity = "fatal" | "warning" | "info";

export interface Evidence {
  source: string;
  signal_type: string;
  snippet: string;
  reference: string;
}

export interface RiskFlag {
  severity: Severity;
  label: string;
  rule_ref: string;
  evidence: Evidence[];
}

export interface RegisteredTrade {
  code: string;
  group: string;
  specialty: string;
}

export interface FirmProfile {
  firm_id: string;
  name: string;
  name_zh: string;
  registered_grade: string;
  value_band: string;
  trades: string[];
  registered_trades: RegisteredTrade[];
  public_flags: RiskFlag[];
  closeout_summary: string;
  award_history: string[];
  description: string;
  enquiry_email: string;
  br_no: string;
  address: string;
  reg_date: string;
  expiry_date: string;
}

export interface Candidate {
  firm: FirmProfile;
  trade: string;
  match_score: number;
  evidence: Evidence[];
  risk_flags: RiskFlag[];
  /** A fatal flag demotes a firm below every clean one regardless of price or match. Deterministic
   *  Layer 1 — never a model's opinion. */
  recommended_against: boolean;
}

export interface ShortlistSet {
  per_trade: Record<string, Candidate[]>;
}

export interface Coverage {
  total_firms: number;
  register_count: number;
  overlay_count: number;
  flagged_count: number;
  flagged_firms: number;
  flags_by_type: Record<string, number>;
  trades: string[];
  flag_sources: string[];
  registers: number;
  provenance: string;
}

export type DispatchStatus =
  | "drafted"
  | "approved"
  | "sent_mock"
  | "sent"
  | "send_failed"
  | "drafted_gmail";

export interface DispatchBundle {
  firm_id: string;
  firm_name: string;
  trade: string;
  bundle_doc_refs: string[];
  email_subject: string;
  email_body: string;
  status: DispatchStatus;
}

export interface DispatchSet {
  bundles: DispatchBundle[];
}

export interface AttachmentOverride {
  package_key: string;
  removed: string[];
  whole: string[];
}

export interface DraftFailure {
  firm_id: string;
  reason: string;
}

export interface DraftRecipient {
  firm_id: string;
  to: string;
}

export interface DispatchDraftsResponse {
  drafted: string[];
  failed: DraftFailure[];
  recipients: DraftRecipient[];
  outbox_written: boolean;
  /** Top-level actionable notice (Gmail unconfigured / DEMO / TEST MODE); "" when all is well. */
  message: string;
  bundles: DispatchBundle[];
}

/** One planned attachment for a package. `mode` is the whole point: `sliced` means pages were cut
 *  from a legal original, `whole` means the file goes intact (the safe default), `generated` means
 *  we produced it (the priced-return sheet). `flags` records why a slice degraded to whole. */
export interface PlanAttachment {
  source_doc: string;
  out_filename: string;
  mode: "sliced" | "whole" | "generated";
  pages: number[];
  clauses: string[];
  reason: string;
  flags: string[];
}

/** A spec a package's lines reference that is not in the upload. Surfaced, never silently absent. */
export interface MissingSpec {
  spec: string;
  referenced_by: string;
}

export interface SectionPlan {
  package_key: string;
  section: string;
  attachments: PlanAttachment[];
  missing_specs: MissingSpec[];
}

// ---------------------------------------------------------------------------
// Level & award — what came back, and who gets it
// ---------------------------------------------------------------------------

export interface ArithmeticFinding {
  location: string;
  issue: string;
  corrected_value: number;
  severity: Severity;
}

export interface BidLineItem {
  item_ref: string;
  description: string;
  unit: string;
  qty: number;
  rate: number | null;
  amount: number | null;
}

export interface BidReply {
  firm_id: string;
  trade: string;
  line_items: BidLineItem[];
  exclusions: string[];
  claimed_total: number | null;
}

/** One firm's bid after Layer 1 has recomputed it. `corrected_total` is OURS — the arithmetic we
 *  redid — and `normalized_total` is what they claimed. The difference is the finding. */
export interface LevelledBid {
  firm_id: string;
  firm_name: string;
  trade: string;
  normalized_total: number;
  corrected_total: number;
  arithmetic_findings: ArithmeticFinding[];
  exclusions: string[];
  scope_gaps: string[];
}

export type ReplyStatus = "active" | "superseded" | "withdrawn" | "migrated";

export interface TenderReplyInfo {
  firm_id: string;
  trade: string;
  line_items: number;
  claimed_total: number | null;
  status: ReplyStatus;
  received_at: string | null;
}

export interface TenderReplies {
  tender_slug: string;
  reply_count: number;
  last_received: string | null;
  replies: TenderReplyInfo[];
  outstanding: { firm_id: string; trade: string }[];
  comparison_available: boolean;
  /** routed-unit package_key -> that unit's bill-line count (the coverage denominator, Layer 1). */
  unit_totals: Record<string, number>;
}

export interface AwaitingFirm {
  firm_id: string;
  firm_name: string;
  ref: string;
  received: boolean;
  status: DispatchStatus;
}

export interface AwaitingPackage {
  trade: string;
  firms: AwaitingFirm[];
}

/** A return that priced a DIFFERENT unit than the one it was uploaded against. Reported so the
 *  operator can re-attach it, never silently filed under the wrong package. */
export interface MisdirectedHint {
  target_unit: string;
  matched_unit: string;
  matched_items: number;
  unit_total: number;
}

export interface BidDistributionPoint {
  firm_name: string;
  corrected_total: number;
}

export interface HistoricalBand {
  low: number;
  median: number;
  high: number;
}

export interface RankedFirm {
  firm_id: string;
  firm_name: string;
  corrected_total: number;
  risk_flags: RiskFlag[];
  recommended_against: boolean;
  reason: string;
  /** A return that priced NOTHING for this unit — excluded from the ranking, never awardable at 0. */
  no_priced_coverage: boolean;
}

export interface Recommendation {
  trade: string;
  recommended_firm_id: string | null;
  ranked: RankedFirm[];
  rationale: string;
  bid_distribution: BidDistributionPoint[];
  historical_band: HistoricalBand | null;
  /** No valid priced return has arrived — the award gate is closed for this package. */
  awaiting_valid_return: boolean;
}

export interface LevelSection {
  trade: string;
  levelled: LevelledBid[];
}

export interface LevelAllResponse {
  sections: LevelSection[];
}

export interface RecommendSection {
  trade: string;
  recommendation: Recommendation;
}

export interface RecommendAllResponse {
  sections: RecommendSection[];
}

export interface LevelUploadResult {
  levelled: LevelledBid[];
  misdirected?: MisdirectedHint | null;
}

// ---------------------------------------------------------------------------
// The management screens — firm register, benchmark corpus, projects
// ---------------------------------------------------------------------------
// Copied from src/types.ts on the same terms as everything above: separate type files by design,
// and the backend is the authority.

export interface FirmsPage {
  items: FirmProfile[];
  total: number;
  limit: number;
  offset: number;
}

export interface EstimateProject {
  id: number;
  name: string;
  trade: string;
  client: string;
  contract_ref: string;
  status: string;
  provenance: string;
  source: string;
  run_ref: string;
  package_key: string;
  scope_of_works: string;
  notes: string;
  created_at: string;
  closed_at: string;
  item_count: number;
  priced_item_count: number;
  total: number | null;
}

export interface DashboardPackage {
  package_key: string;
  trade: string;
  scope_summary: string;
  recommended_route: string;
  chosen_route: string | null;
  track: string; // left | right | undecided
  estimate_id: number | null;
  decided_by: string;
}

export interface ProjectSummary {
  run_ref: string;
  name: string;
  provenance: string;
  package_count: number;
  self_perform_count: number;
  sublet_count: number;
  estimate_count: number;
  benchmark_project_id: number | null;
}

export interface ProjectDashboard {
  run_ref: string;
  name: string;
  provenance: string;
  packages: DashboardPackage[];
  estimates: EstimateProject[];
  benchmark_project_id: number | null;
}

export interface BenchmarkProject {
  id: number;
  name: string;
  trade: string;
  client: string;
  contract_ref: string;
  status: string;
  provenance: string;
  source: string;
  notes: string;
  created_at: string;
  closed_at: string;
  tender_item_count: number;
  actual_item_count: number;
  variance_count: number;
}

export interface BenchmarkSummary {
  projects: number;
  tender_items: number;
  actual_items: number;
  variance_records: number;
  reasoned_records: number;
  coverage_by_trade: Record<string, number>;
  coverage_by_granularity: Record<string, number>;
}

export interface BenchmarkItem {
  id: number;
  project_id: number;
  item_ref: string;
  description: string;
  unit: string;
  qty: number | null;
  rate: number | null;
  amount: number | null;
  section: string;
  granularity?: string;
}

export interface MatchPair {
  tier: number;
  similarity: number | null;
  tender: BenchmarkItem | null;
  actual: BenchmarkItem | null;
}

export interface MatchProposal {
  project_id: number;
  tier1: MatchPair[];
  tier2: MatchPair[];
  tier3: MatchPair[];
}

export interface MatchConfirm {
  tender_item_id?: number | null;
  actual_item_id?: number | null;
  match_tier: number;
}

/** One matched tender-vs-actual line. `reason_code` is written ONLY by a human confirming it —
 *  `suggested_reason` is a proposal drawn from the EOS narrative and is never the same field. */
export interface VarianceRecord {
  id: number;
  project_id: number;
  tender_item_id: number | null;
  actual_item_id: number | null;
  item_ref: string;
  granularity: string;
  match_tier: number | null;
  tender_rate: number | null;
  actual_rate: number | null;
  tender_qty: number | null;
  actual_qty: number | null;
  tender_amount: number | null;
  actual_amount: number | null;
  rate_delta: number | null;
  rate_delta_pct: number | null;
  amount_delta: number | null;
  amount_delta_qty: number | null;
  amount_delta_rate: number | null;
  reason_code: string;
  reason_note: string;
  tagged_by: string;
  confirmed_at: string;
  source: string;
  suggested_reason: string | null;
}

export interface ReasonCode {
  code: string;
  label: string;
  description: string;
  category: string;
}

export interface ProjectEOS {
  id: number;
  project_id: number;
  narrative: string;
  summary: string;
  source_doc: string;
  has_images: boolean;
  provenance: string;
  created_at: string;
}

export interface ReasonCandidate {
  item_ref: string;
  granularity: string;
  reason_code: string;
  snippet: string;
  source: string; // reason-from-eos | fallback
  record_id: number | null;
}

export interface VarianceReasonSuggestions {
  project_id: number;
  eos_attached: boolean;
  candidates: ReasonCandidate[];
}
