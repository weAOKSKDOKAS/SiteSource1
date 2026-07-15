// TypeScript mirror of the backend Pydantic contracts (backend/schemas/models.py).
// SiteSource numeric fields (qty, rate, totals, match_score) serialise as JSON numbers.

export type Severity = "fatal" | "warning" | "info";
export type DispatchStatus = "drafted" | "approved" | "sent_mock" | "sent" | "send_failed" | "drafted_gmail";

// Relevant-document assembler (per dispatched section): the attachment plan + any
// referenced-but-unsupplied spec sections.
export interface PlanAttachment {
  source_doc: string; // the disk lookup key (the original filename, or the generated sheet name)
  out_filename: string; // the emitted filename when it differs from source_doc (the SoR slice is
  //   looked up under the original SR name but sent as "SoR_{unit}_Section_{X}.pdf"); "" -> source_doc
  mode: "sliced" | "whole" | "generated";
  pages: number[];
  clauses: string[]; // the clause ids a sliced spec extract contains (7.34A, PB 71)
  reason: string;
  flags: string[]; // "scanned_whole" | "whole_clause_not_located" | "whole_section_not_located" | "priced_return"
}
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
// The human gate's per-section decisions carried back to /dispatch/drafts so the assembled
// bundle matches exactly what was confirmed: drop `removed` docs, send `whole` (sliced) docs whole.
export interface AttachmentOverride {
  package_key: string;
  removed: string[];
  whole: string[];
}
// One enquiry Gmail could not draft, with the actionable reason (no contact email, missing
// credential, API error). The enquiry itself stays safe in the outbox.
export interface DraftFailure {
  firm_id: string;
  reason: string;
}
// The resolved "To:" per firm (address-book override or the register enquiry_email) — so the gate
// can show each recipient. Empty when neither source has an address (that firm is in `failed`).
export interface DraftRecipient {
  firm_id: string;
  to: string;
}
export interface DispatchDraftsResponse {
  drafted: string[]; // firm ids that now have a Gmail draft
  failed: DraftFailure[];
  recipients: DraftRecipient[];
  outbox_written: boolean;
  message: string; // top-level actionable notice (Gmail unconfigured / DEMO); "" when all good
  bundles: DispatchBundle[];
}
// The Gmail integration's health — shown BEFORE the operator clicks, so a broken credential
// is visible on the gate, not discovered as a failed action.
export interface GmailStatus {
  status: "connected" | "not_configured" | "error" | "demo";
  detail: string;
  credentials_configured: boolean;
  token_state: string;
  polling_enabled: boolean;
  poll_seconds: number;
  last_poll_at: string | null;
  last_error: string;
  drafts_created: number;
  replies_processed: number;
  replies_unmatched: number;
}
// grade | award_history | safety_prosecution | winding_up | debarment | adjudication | distress_filing | closeout_performance | pricing
export type SignalType = string;

export interface Evidence {
  source: string;
  signal_type: SignalType;
  snippet: string;
  reference: string;
}

export interface RiskFlag {
  severity: Severity;
  label: string;
  rule_ref: string;
  evidence: Evidence[];
}

export interface SorItem {
  item_ref: string;
  description: string;
  unit: string;
  qty: number;
  section?: string | null; // the SoR section this line belongs to (leading letters of item_ref)
}

export interface SectionMeta {
  code: string;
  title: string;
  item_count: number;
}

export interface TradeWorkPackage {
  trade: string;
  scope_summary: string;
  sor_items: SorItem[];
  source_refs: string[];
  sections?: SectionMeta[];
}

export interface TenderDocument {
  doc_type: string;
  filename: string;
}

export interface TenderPackage {
  project_name: string;
  description: string;
  documents: TenderDocument[];
}

export interface ScopePackages {
  project_name: string;
  packages: TradeWorkPackage[];
}

// How one uploaded document was classified — surfaced so a wrong assignment (e.g. a Method of
// Measurement mistaken for a Schedule of Rates) is visible at ingest, not found as phantom packages.
export interface DocKind {
  filename: string;
  doc_type: string;
  source: string; // filename | title | llm | fallback | "" (unclassified)
}

// An extracted item quarantined because its section is not one the Schedule of Rates itself declares
// — surfaced (never silently dropped), never formed into a package.
export interface UnrecognisedItem {
  item_ref: string;
  description: string;
  section: string;
  reason: string;
}

// Live upload returns the scope split plus the trade-tagged tender (for /dispatch routing).
export interface IngestUpload {
  scope: ScopePackages;
  tender: TenderPackage;
  tender_slug: string;
  classification?: DocKind[]; // each document's resolved kind + how it was decided
  unrecognised_items?: UnrecognisedItem[]; // items quarantined by the provenance backstop
}

// Async ingest transport: the kick-off + poll envelope. Live: {job_id, status:"queued"} then
// poll to done|error. DEMO: {status:"done", result} inline (no job). A big tender extracts in
// the background for as long as it needs, so no single long request can time out.
export type IngestJobStatus = "queued" | "running" | "done" | "error";
export interface IngestJobState {
  job_id: string | null;
  status: IngestJobStatus;
  stage: string; // uploading | classifying | extracting | splitting
  progress?: { done: number; total: number } | null;
  error?: string | null;
  result?: IngestUpload | null;
  warnings?: string[]; // per-section batches the extractor couldn't read (non-fatal)
}

// A reply record for a tender. `trade` is the aligned routed-unit package_key the reply covers.
// `status` distinguishes the ACTIVE reply (in the comparison) from history: a `superseded` reply
// was replaced by a later one, `withdrawn` was pulled by the operator, `migrated` was re-keyed.
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
  // routed-unit package_key -> that unit's SoR item count (the coverage denominator, Layer 1).
  unit_totals: Record<string, number>;
}

// --- Benchmark estimator (Phase B1) ---------------------------------------
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

export interface BenchmarkSummary {
  projects: number;
  tender_items: number;
  actual_items: number;
  variance_records: number;
  reasoned_records: number;
  coverage_by_trade: Record<string, number>;
  coverage_by_granularity: Record<string, number>;
}

// --- EOS narrative → variance reason (Phase 2) -----------------------------
export interface ProjectEOS {
  id: number;
  project_id: number;
  narrative: string;
  summary: string;
  source_doc: string;
  has_images: boolean;
  provenance: string; // demo | live
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

// --- Routing gate (Phase 1) -----------------------------------------------
export interface RoutePackage {
  id?: number;
  package_key: string;
  trade: string;
  section?: string | null; // a section sub-package: its code (trade:SECTION) and header title
  section_title?: string;
  scope_summary: string;
  recommended_route: string; // self_perform | sublet
  rationale: string;
  signals: Record<string, number | boolean | string>;
  chosen_route: string | null;
  decided_by: string;
  decided_at: string;
  source: string;
}

export interface RouteProposal {
  run_ref: string;
  packages: RoutePackage[];
}

export interface RouteDecision {
  package_key: string;
  chosen_route: string;
}

export interface RouteDecisionResult {
  run_ref: string;
  packages: RoutePackage[];
  sublet_packages: string[];
  self_perform_packages: string[];
  estimate_ids: Record<string, number>; // package_key -> seeded left-track estimate id (P4b)
}

// --- Estimator (Phase 3) ---------------------------------------------------
export interface EstimateProject {
  id: number;
  name: string;
  trade: string;
  client: string;
  contract_ref: string;
  status: string; // draft | submitted | awarded | closed
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

export interface EstimateItem {
  id: number;
  estimate_id: number;
  item_ref: string;
  description: string;
  unit: string;
  qty: number | null;
  rate: number | null;
  amount: number | null;
  section: string;
  source: string;
}

export interface EstimateDraftResult {
  estimate: EstimateProject;
  scope_of_works: string;
  added_item_refs: string[];
  trade_mapped: boolean;
}

export interface RateWarning {
  reason_code: string;
  count: number;
}

export interface RatePrecedent {
  item_id: number | null;
  item_ref: string;
  tier: number; // 1 exact | 2 similar | 0 none
  matched_ref: string;
  similarity: number | null;
  sample_count: number;
  rate_low: number | null;
  rate_median: number | null;
  rate_high: number | null;
  rate_warnings: RateWarning[];
}

export interface RateSuggestions {
  estimate_id: number;
  corpus_empty: boolean;
  corpus_size: number;
  suggestions: RatePrecedent[];
}

export interface EstimateFinding {
  kind: string; // omission | unit_mismatch | unpriced | rubric | scope_gap
  severity: string; // warning | info
  item_ref: string;
  message: string;
  source: string;
}

export interface EstimateCheckResult {
  estimate_id: number;
  findings: EstimateFinding[];
  tender_checked: boolean;
  rubric_size: number;
}

export interface LetterOfOffer {
  subject: string;
  body: string;
  inclusions: string[];
  exclusions: string[];
  assumptions: string[];
}

// --- Unified project dashboard (Phase 4) -----------------------------------
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

// One raw registered-trade line from the CIC register (code / group / specialty).
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
  // CIC-register fields (Prompt E) — empty on overlay/illustrative firms.
  description: string;
  enquiry_email: string;
  br_no: string;
  address: string;
  reg_date: string;
  expiry_date: string;
}

export interface FirmsPage {
  items: FirmProfile[];
  total: number;
  limit: number;
  offset: number;
}

export interface Candidate {
  firm: FirmProfile;
  trade: string;
  match_score: number;
  evidence: Evidence[];
  risk_flags: RiskFlag[];
  recommended_against: boolean;
}

export interface ShortlistSet {
  per_trade: Record<string, Candidate[]>;
}

// A human-edited enquiry draft for one (trade, firm) — the approve-before-send gate.
// A blank field keeps the composed value; the outbox stores exactly the edited text.
export interface DraftOverride {
  trade: string;
  firm_id: string;
  subject: string;
  body: string;
}

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

// A return uploaded for one enquiry whose lines actually price ANOTHER unit strongly (the exact
// operator mistake). Advisory only — the operator confirms a reattach; nothing moves automatically.
export interface MisdirectedHint {
  target_unit: string;
  matched_unit: string;
  matched_items: number;
  unit_total: number;
}

// The /level-upload envelope: the levelled bid(s) plus a misdirect hint when the return looks like
// it belongs to a different enquiry.
export interface LevelUploadResult {
  levelled: LevelledBid[];
  misdirected: MisdirectedHint | null;
}

// Live-run awaiting state (Prompt 1): a dispatched sublet package whose priced returns
// have not all arrived. `ref` is the [SiteSource Ref] the enquiry carries; `received` is
// true once a reply for that firm has been levelled into the package's section.
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

export interface ArithmeticFinding {
  location: string;
  issue: string;
  corrected_value: number;
  severity: Severity;
}

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

// --- Per-section (per-trade) leveling + recommend (Prompt 1) ----------------
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

export interface RankedFirm {
  firm_id: string;
  firm_name: string;
  corrected_total: number;
  risk_flags: RiskFlag[];
  recommended_against: boolean;
  reason: string;
  // A return that priced NOTHING for this unit — excluded from the ranking, never awardable at HK$0.
  no_priced_coverage: boolean;
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

export interface Recommendation {
  trade: string;
  recommended_firm_id: string | null;
  ranked: RankedFirm[];
  rationale: string;
  bid_distribution: BidDistributionPoint[];
  historical_band: HistoricalBand | null;
  // True when no valid priced return has arrived — the award gate is closed for this package.
  awaiting_valid_return: boolean;
}

export interface DemoCaseSummary {
  id: string;
  name: string;
  hero_trade: string;
  blurb: string;
}

export interface DemoCase extends DemoCaseSummary {
  tender: TenderPackage;
  replies: BidReply[];
  rationale_fixture: string;
  // Per-trade rationale fixtures for the per-section recommend path; single-trade
  // scenarios carry {hero_trade: rationale_fixture}.
  rationale_fixtures: Record<string, string>;
}

export interface Health {
  status: string;
  demo_mode: boolean;
}

// Coverage of the real-provenance population only (the CIC register + the enforcement
// overlay), stated as an honest composition. The illustrative demo firms are excluded.
export interface Coverage {
  total_firms: number;
  register_count: number; // real firms on the CIC register (carry a BR No.)
  overlay_count: number; // real firms from the enforcement/offer overlay (not on the register)
  flagged_count: number;
  flagged_firms: number; // back-compat alias for flagged_count
  flags_by_type: Record<string, number>;
  trades: string[];
  flag_sources: string[]; // distinct issuing bodies on the stored flags
  registers: number; // how many distinct issuing registers
  provenance: string;
}
