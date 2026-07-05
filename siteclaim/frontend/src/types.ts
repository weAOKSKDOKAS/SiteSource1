// TypeScript mirror of the backend Pydantic contracts (backend/schemas/models.py).
// SiteSource numeric fields (qty, rate, totals, match_score) serialise as JSON numbers.

export type Severity = "fatal" | "warning" | "info";
export type DispatchStatus = "drafted" | "approved" | "sent_mock";
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
}

export interface TradeWorkPackage {
  trade: string;
  scope_summary: string;
  sor_items: SorItem[];
  source_refs: string[];
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

// Live upload returns the scope split plus the trade-tagged tender (for /dispatch routing).
export interface IngestUpload {
  scope: ScopePackages;
  tender: TenderPackage;
  tender_slug: string;
}

export interface TenderReplyInfo {
  firm_id: string;
  trade: string;
  line_items: number;
  claimed_total: number | null;
}

export interface TenderReplies {
  tender_slug: string;
  reply_count: number;
  last_received: string | null;
  replies: TenderReplyInfo[];
  outstanding: { firm_id: string; trade: string }[];
  comparison_available: boolean;
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

// --- Routing gate (Phase 1) -----------------------------------------------
export interface RoutePackage {
  id?: number;
  package_key: string;
  trade: string;
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
}

export interface FirmProfile {
  firm_id: string;
  name: string;
  registered_grade: string;
  value_band: string;
  trades: string[];
  public_flags: RiskFlag[];
  closeout_summary: string;
  award_history: string[];
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

export interface RankedFirm {
  firm_id: string;
  firm_name: string;
  corrected_total: number;
  risk_flags: RiskFlag[];
  recommended_against: boolean;
  reason: string;
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
}

export interface Health {
  status: string;
  demo_mode: boolean;
}

// Coverage of the real-provenance registry scrape only (the illustrative demo
// firms are excluded from this claim).
export interface Coverage {
  total_firms: number;
  flagged_firms: number;
  flags_by_type: Record<string, number>;
  trades: string[];
  provenance: string;
}
