// TypeScript mirror of the backend Pydantic contracts (backend/schemas/models.py).
// SiteSource numeric fields (qty, rate, totals, match_score) serialise as JSON numbers.

export type Severity = "fatal" | "warning" | "info";
export type DispatchStatus = "drafted" | "approved" | "sent_mock" | "drafted_gmail";
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
  // factual CIC-register blurb (trades + registration); shown for register-only
  // firms that carry no held closeout report.
  description: string;
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
  normalized_total: number;
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
  scope_fixture: string;
  replies: BidReply[];
  rationale_fixture: string;
  // Per-work-section rationale fixtures (trade -> fixture); drives per-section recommend.
  rationale_by_trade: Record<string, string>;
  // Approval-driven cases ship a SoR template bank instead of a fixed replies list: the
  // wizard builds the leveling replies from the approved firms via /collect-replies.
  sor_fixture?: string | null;
}

export interface Health {
  status: string;
  demo_mode: boolean;
}

// A raw public-record flag as stored, linked to its government source.
export interface PublicFlag {
  signal_type: string;
  label: string;
  date: string | null;
  source: string | null;
  reference: string | null;
}

// A registered CIC trade row (Code :: Specialty), structured for display.
export interface RegisteredTrade {
  code: string;
  group: string;
  specialty: string;
}

// A real-provenance registry firm (the Database page's data asset), fused from the
// CIC register: a factual description, the real enquiry e-mail, registration dates.
export interface Firm {
  firm_id: string;
  name_en: string;
  name_zh: string | null;
  registered_grade: string;
  value_band: string;
  trades: string[];
  registered_trades: RegisteredTrade[];
  description: string;
  enquiry_email: string;
  br_no: string;
  reg_date: string;
  expiry_date: string;
  public_flags: PublicFlag[];
}

// One server-side page of the register.
export interface FirmsPage {
  items: Firm[];
  total: number;
  limit: number;
  offset: number;
}

// Full firm profile returned by GET /firms/{firm_id} — used by the shortlist card modal.
export interface AwardHistoryItem {
  project: string;
  client: string | null;
  year: number | null;
  source: string | null;
}

export interface NotableProject {
  title: string;
  source?: string | null;
}

// The curated, verifiable profile for a firm that genuinely does these trades.
// Empty (all blank/[]) for register-only firms — the modal then shows register data only.
export interface FirmCuratedProfile {
  overview: string;
  services: string[];
  notable_projects: NotableProject[];
  accreditations: string[];
  group_parent: string;
  staff_note: string;
  offices: string[];
}

export interface FirmProfileFull {
  firm_id: string;
  name_en: string;
  name_zh: string | null;
  registered_grade: string;
  value_band: string;
  registers: string[];
  trades: string[];
  registered_trades: RegisteredTrade[];
  description: string;
  enquiry_email: string;
  br_no: string;
  reg_date: string;
  expiry_date: string;
  public_flags: PublicFlag[];
  award_history: AwardHistoryItem[];
  provenance: string;
  profile: FirmCuratedProfile;
}

// Coverage of the real-provenance registry scrape only (the illustrative demo
// firms are excluded from this claim).
export interface Coverage {
  total_firms: number;
  flagged_firms: number;
  // headline composition: CIC-register firms + enforcement/offer overlay
  register_count: number;
  overlay_count: number;
  flagged_count: number;
  flags_by_type: Record<string, number>;
  trades: string[];
  flag_sources: string[];
  registers: number;
  provenance: string;
}

// A clicked citation, opened in the evidence drawer. Built from a flag/evidence the
// backend already returns (source + reference + a snippet/label, optional date).
export interface Citation {
  source: string | null;
  reference: string | null;
  detail: string;
  date?: string | null;
}
