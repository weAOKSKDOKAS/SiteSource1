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
