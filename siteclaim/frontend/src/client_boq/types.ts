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
  /** The CURRENT engine's evidence: the client's bill has been imported and is priced from.
   *  `price` above is the retired resource-schedule engine's headline figure and is null on every
   *  tender priced the normal way — the two are different engines and neither implies the other. */
  has_bill: boolean;
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

// --- the output book -------------------------------------------------------
// The rate book's sibling: rates say what a crew costs an hour, outputs say how many hours the
// work takes. Both are the company's, not a job's. A tender inherits every norm here and may
// override any of them, and `SourceChip` shows which — see boq/outputs.py, which is the only
// place BOOK/YOURS/MISSING is decided.
export interface OutputRow {
  key: string;
  label: string;
  unit: string;
  /** The `⌞` line: why the number is what it is. Empty when it needs no explaining. */
  note: string;
  value: number;
  /** What ships. Stays visible beside an edit so you can always see what you moved away from. */
  default: number;
  /** `seed` = nobody has touched it. `you` = somebody set it, and updated_by says who. */
  source: "seed" | "you";
  updated_by: string;
  updated_at: string | null;
}

export interface OutputBlock {
  id: string;
  title: string;
  rows: OutputRow[];
}

export interface OutputsResponse {
  blocks: OutputBlock[];
  count: number;
}

// --- the take-off (Site) ---------------------------------------------------
// The drawing's half of the estimate: where the holes are, which of them a rig can reach, and
// which of them drill alike. None of it is in the bill of quantities.
export interface Station {
  station: string;
  kind: string;
  easting: number | null;
  northing: number | null;
  ground_level_mpd: number | null;
  rockhead_level_mpd: number | null;
  length_m: number;
  max_boring_m: number;
  soil_m: number;
  hard_above_rockhead_m: number;
  rock_m: number;
  standpipe: boolean;
  piezometer: boolean;
  sheet: string;
  notes: string[];
  /**
   * Field names whose cell was on the sheet and could not be read. A blank is not a zero: soil,
   * rock and hard metres are plain numbers defaulting to 0, and a soil-only hole legitimately
   * carries 0 rock — so nothing downstream can tell a missing cell from a printed one unless the
   * reader says so here. Empty on a schedule somebody typed.
   */
  unread: string[];
}

export interface TrialPit {
  station: string;
  easting: number | null;
  northing: number | null;
  ground_level_mpd: number | null;
  depth_m: number;
  max_depth_m: number;
  depth_in_soil_m: number;
  sheet: string;
}

/** `access_class` is "" until somebody decides. `decided_by` is why the table exists. */
export interface StationClass {
  station: string;
  access_class: string;
  group_id: string;
  decided_by: string;
  decided_at: string | null;
}

export interface ScheduleTotals {
  holes: number;
  soil_m: number;
  rock_m: number;
  hard_m: number;
  standpipes: number;
  piezometers: number;
  instruments: number;
  deepest: number;
  trial_pits: number;
}

export interface StationScheduleResponse {
  set_id: string;
  meta: { confirmed_by: string; confirmed_at: string | null; source_sheet: string };
  stations: Station[];
  trial_pits: TrialPit[];
  classes: Record<string, StationClass>;
  /** A hole whose length is not its soil plus its rock has been misread. Named, never repaired. */
  bad_rows: string[];
  /** A hole carrying a cell the reader could not make out. A blank is not a zero. */
  unread_rows: string[];
  /** A hole with no soil and no rock — it adds nothing to either total, so nothing else sees it. */
  empty_rows: string[];
  /** A station name appearing twice. The schedule is keyed on the name; the second one wins. */
  duplicate_names: string[];
  /** All four checks in one list, in that order. Empty means the take-off can be priced from. */
  problems: string[];
  usable: boolean;
  totals: Partial<ScheduleTotals>;
  waiting_on?: string;
}

/** One printed grid cross, read off the sheet: its coordinates as printed, its position as page
 *  fractions (0–1, so the registration survives re-render at any DPI). */
export interface GridMark {
  easting: number;
  northing: number;
  x: number;
  y: number;
  label: string;
}

/** Two grid marks and where the sheet lives. Typed once per site-plan sheet; every station on it
 *  follows by arithmetic — the georef module refuses (with named problems) rather than
 *  approximating, which is what licenses the CSS crop trick. */
export interface SheetRegistrationShape {
  sheet: string;
  part_id: string;
  page: number;
  marks: GridMark[];
}

export interface GeorefSheet {
  sheet: string;
  part_id: string;
  page: number;
  usable: boolean;
  /** "" = two typed numbers are a proposal until somebody has looked at the sheet beside them. */
  confirmed_by: string;
  problems: string[];
  marks: GridMark[];
  stations_on: number;
}

/** One station's tile: which sheet contains it (by coordinates, never nearest-match) and the
 *  crop box MapCrop turns into a CSS transform. */
export interface GeorefCrop {
  sheet: string;
  part_id: string;
  page: number;
  box: {
    x0: number;
    y0: number;
    x1: number;
    y1: number;
    centre_x: number;
    centre_y: number;
    window_m: number;
    clipped: boolean;
  };
}

export interface GeorefResponse {
  set_id: string;
  window_m: number;
  waiting_on: string;
  stations: string[];
  sheets: GeorefSheet[];
  crops: Record<string, GeorefCrop>;
  /** Located stations that land on no registered sheet — named, never given a tile of the
   *  wrong place. */
  unplaced: string[];
}

/** The schedule as it goes back to the server — the shape `POST /site/schedule` accepts. */
export interface StationScheduleShape {
  set_id: string;
  source_sheet: string;
  stations: Station[];
  trial_pits: TrialPit[];
  notes: string[];
  confirmed_by: string;
}

/**
 * What a pasted table was understood to say. A PROPOSAL — the parse endpoint stores nothing, and
 * saving it is a separate call a person makes.
 */
export interface SchedulePasteResponse {
  set_id: string;
  schedule: StationScheduleShape;
  /** One sentence for the top of the panel. Reassuring only when it is true. */
  headline: string;
  header_found: boolean;
  /** "tab" | "comma" | "spaces" — how the columns were separated. */
  delimiter: string;
  /** `field -> the header text it came from`. Empty when the columns were taken by position. */
  mapping: Record<string, string>;
  /** Headers present in the paste that match no field. Named rather than dropped. */
  unmapped_columns: string[];
  /** Fields the paste carries no column for. */
  missing_columns: string[];
  /** Lines that could not be made into a row, with the line number as pasted. */
  skipped_lines: string[];
  cells_unread: number;
  bad_rows: string[];
  unread_rows: string[];
  empty_rows: string[];
  duplicate_names: string[];
  problems: string[];
  usable: boolean;
  totals: Partial<ScheduleTotals>;
}

/** One quantity the drawing implies, and what the client billed for it. */
export interface Derived {
  full_ref: string;
  label: string;
  value: number;
  unit: string;
  rule: string;
  source: string;
  billed: number | null;
  agrees: boolean | null;
  note: string;
}

export interface DerivedResponse {
  set_id: string;
  rev: number | null;
  checked_against_a_bill: boolean;
  derived: Derived[];
  divergences: Derived[];
  confirmations: string[];
  unchecked: string[];
}

export interface HoleGroup {
  label: string;
  stations: string[];
  access_class: string;
  terrain: string;
  soil_m: number;
  rock_m: number;
  deepest_m: number;
  holes_past_20m: number;
  /** The measured shapes, one per station, straight off the schedule. The totals above are their
   *  sum — a group's programme is run over HOLES, not over one hole as deep as the group. */
  shapes: { station: string; soil_m: number; rock_m: number }[];
  rigs: number;
  soil_output: number;
  rock_output: number;
  /** Efficiency lost per 20 m DOWN ONE HOLE. Defaults to 0: measured at zero across 205 real
   *  drilling-days, and rock fraction — which the band table already carries — is the driver.
   *  Above zero it is deliberate padding, and it resets at every hole. */
  decay: number;
  access_build_cost: number;
  badge: string;
  basis: string;
  /** Which fields the estimator typed. Recorded as an act — `decay` defaults to 0, so the
   *  value alone cannot say whether anybody chose it. */
  overrides: string[];
}

export interface ResolvedNorm {
  key: string;
  value: number;
  source: "book" | "yours" | "missing";
  book_value: number | null;
  label: string;
  unit: string;
}

// --- the access board (Site › MAP) -----------------------------------------
// Where the holes are, and everything that can be KNOWN about reaching them. `proposed_class` is
// on every cluster and is permanently "" — the backend never writes it, and the type carries the
// field so that "nothing proposes an access class" is visible rather than remembered.
export interface Evidence {
  kind: "map" | "imagery" | "drawing" | "satellite" | "street_view" | "road_distance";
  label: string;
  /** A path back into THIS api when the source needs a credential; an external URL only when it
   *  needs none. A keyed URL handed to a browser is a published credential. */
  url: string;
  external: boolean;
  available: boolean;
  unavailable_reason: string;
  /** A measured figure in words, when the evidence IS a number rather than a link — the road
   *  distance's "410 m straight line to the picked access point". Deterministic only. */
  note: string;
}

/** One station in both coordinate worlds, with a keyless map link. `in_hong_kong` false is a
 *  coordinate REFUSED into the list, never a pin drawn confidently in the wrong country. */
export interface StationPosition {
  station: string;
  easting: number;
  northing: number;
  lat: number;
  lon: number;
  in_hong_kong: boolean;
  maps_url: string;
}

export interface PositionsResponse {
  set_id: string;
  positions: StationPosition[];
  problems: string[];
  waiting_on?: string;
}

/** The nearest MAPPED road to one hole. A measurement, with the OSM way it measured to so the
 *  claim can be opened and checked — never a class of site. */
export interface NearestRoad {
  station: string;
  metres: number;
  way_id: number;
  name: string;
  highway: string;
  lat: number;
  lon: number;
}

export interface RoadsResponse {
  set_id: string;
  nearest: NearestRoad[];
  /** Holes no mapped road came within reach of — named, never silently dropped. */
  unreached: string[];
  roads_seen: number;
  source: string;
  problems: string[];
  /** "" when it ran. Otherwise why not: no schedule, demo mode, or the request failed. */
  waiting_on: string;
}

/** A person's click on the map: where the site is entered from. The judgement carries a name;
 *  every distance that follows is arithmetic. */
export interface RoadPoint {
  point_id: string;
  label: string;
  lat: number;
  lon: number;
  picked_by: string;
  picked_at: string | null;
}

export interface RoadResponse {
  set_id: string;
  points: RoadPoint[];
  /** Station → straight-line metres to the NEAREST picked point. A station with no coordinates
   *  has no entry — absence, not zero. */
  station_m: Record<string, number>;
  waiting_on: string;
}

/** One proposed next action from the brain. `tab` and `label` come from the backend's action
 *  REGISTRY, never from the model — the button below it only navigates; the gated endpoint on
 *  that screen still takes the person's click. */
export interface BriefingAction {
  action_id: string;
  tab: string;
  label: string;
  reasoning: string;
  citations: { source: string; quote: string }[];
}

/** The brain's validated briefing. Structurally unable to carry a verdict, a rate, a class or a
 *  gate flag — its raw model has no field for one. */
export interface Briefing {
  understanding: string;
  disagreements: string[];
  actions: BriefingAction[];
  cannot_assess: string;
  /** What validation removed, named — an invented action or an ungrounded citation. */
  stripped: string[];
  /** Which ground families each focused read covered — the briefing's own receipts. */
  reads: string[];
  seq: number;
  created_by: string;
  created_at: string | null;
}

export interface BriefingResponse {
  set_id: string;
  briefing: Briefing | null;
  count: number;
  waiting_on: string;
}

// --- the working screen (§10) — engine B, the per-item build-up bill ---------

/** One line of the derivation tree. `origin` encodes the affordance class (document → show me,
 *  person/library → change, computed → a branch); `problem` is THIS node's own failure, set by
 *  the backend so the failing LINE paints red rather than only a strip naming it. */
export interface TraceNode {
  label: string;
  value: number | null;
  unit: string;
  op: string;
  formula: string;
  origin: "document" | "person" | "library" | "computed";
  cite: { part_id: string; page: number; quote: string; label: string } | null;
  owner: string;
  source: string;
  note: string;
  problem: string;
  children: TraceNode[];
}

export interface RateTraceResponse {
  set_id: string;
  rev: number;
  full_ref: string;
  trace: {
    full_ref: string;
    description: string;
    rate: number | null;
    unit: string;
    qty: number;
    amount: number | null;
    root: TraceNode | null;
    checks: string[];
    problems: string[];
  };
  priced: boolean;
  waiting_on: string;
}

/** One priced item from `price_bill` — the engine the sweep and the loadings actually reach. */
export interface WorkingItem {
  full_ref: string;
  description: string;
  qty: number | null;
  unit: string;
  lump: boolean;
  build_up: number;
  spread: number;
  /** A cost routed "load onto this item" on the sweep. Its own field — a loading hidden inside
   *  the resource cost is precisely what this screen exists to expose. */
  loading: number;
  cost: number;
  unit_rate: number | null;
  amount: number;
  rate_source: string;
  pre_priced: boolean;
}

export interface WorkingBill {
  set_id: string;
  rev: number;
  items: WorkingItem[];
  flags: { kind: string; item_id: string; message: string }[];
  spread_total: number;
  spread_residue_ref: string;
  loading_total: number;
  total_build_up: number;
  margin_pct: number;
  tendered_total: number;
}

export interface BillChecksResponse {
  set_id: string;
  rev: number;
  tendered_total: number;
  counts: Record<string, number>;
  flags: { kind: string; item_id: string; message: string }[];
  outstanding_review: { full_ref: string; reason: string }[];
}

export interface CoverageEntry {
  key: string;
  label: string;
  clause_ref: string;
  authored_by: string;
  scope: string;
  page: string;
  document_hint: string;
  unresolved: string;
  provenance: string;
  unverifiable: string;
  ticked: boolean;
  ticked_by: string;
  ticked_at: string | null;
  basis_key?: string;
  accounting?: string;
}

export interface CoverageResponse {
  set_id: string;
  rev: number;
  full_ref: string;
  description: string;
  summary: string;
  entries: CoverageEntry[];
  uncovered: string[];
  settled: boolean;
  note: string;
  partial: boolean;
  waiting_on: string;
}

export interface SweepCost {
  key: string;
  label: string;
  source: string;
  amount: number;
  route: "" | "query" | "load" | "spread" | "accept";
  target_ref: string;
  reason: string;
  decided_by: string;
}

export interface SweepResponse {
  set_id: string;
  rev: number;
  costs: SweepCost[];
  /** One sentence per unrouted cost — the SAME sentences the settle gate refuses with. */
  outstanding: string[];
  settled: boolean;
  spread_total: number;
  loadings: Record<string, number>;
  queries: string[];
  accepted_risk: number;
  routes: string[];
  route_meaning: Record<string, string>;
}

export interface ClusterEvidence {
  label: string;
  stations: string[];
  holes: number;
  lat: number;
  lon: number;
  /** How far the furthest station sits from the centroid. A cluster 400 m across is not one place. */
  spread_m: number;
  soil_m: number;
  rock_m: number;
  deepest_m: number;
  /** What a HUMAN has already decided, per class. "" counts the undecided. Read, never written. */
  decided: Record<string, number>;
  /** ALWAYS "". Declared so the absence is a property of the contract. */
  proposed_class: string;
  evidence: Evidence[];
  notes: string[];
}

export interface MapProviders {
  basemap: {
    provider: string;
    imagery_tiles: string;
    basemap_tiles: string;
    label_tiles: string;
    attribution: string;
    requires_key: boolean;
  };
  google: {
    key_present: boolean;
    static_maps: boolean;
    street_view: boolean;
    distance_matrix: boolean;
  };
}

export interface AccessBoardResponse {
  set_id: string;
  clusters: ClusterEvidence[];
  radius_m: number;
  unlocated: string[];
  problems: string[];
  providers: MapProviders;
  waiting_on?: string;
}

export interface GroupsResponse {
  set_id: string;
  rev: number;
  groups: HoleGroup[];
  /** group label → field name → where that output came from. Drives the SourceChips. */
  sources: Record<string, Record<string, ResolvedNorm>>;
  counts: Record<string, number>;
  /** Holes in the take-off with no class of site — over the WHOLE schedule, not just the grouped
   *  part of it. Read it beside `take_off_read`: 0 with no take-off means nothing is known. */
  unassigned: number;
  billed_class_counts: Record<string, number>;
  /** Where the estimator's classification disagrees with the bill. Empty means agreed AND
   *  checkable — with no billed counts to compare against it now says so instead of going quiet. */
  reconcile: string[];
  not_ready: Record<string, string[]>;
  class_refs: Record<string, string>;
  /** How many holes there are to class, or null when no schedule has been read. */
  total_holes: number | null;
  take_off_read: boolean;
  /** Why the counts above are over an empty take-off. Empty when a schedule has been read. */
  not_checked_because: string;
}

// --- the costing engine ----------------------------------------------------
// Bill of quantities in, priced bill and a live Excel model out. Everything the engine does is
// described by a CostingModel the estimator can change; a change made on one tender stays there.
export interface Band {
  label: string;
  lower: number;
  rate: number;
  holes: number;
  calibration_depth_m: number;
}

export interface SpreadLine {
  key: string;
  label: string;
  block: string;
  multiplier: number;
  rate: number;
  unit: string;
  /** `rig_day` scales with the rig count; `contract_day` does not. Merging them prices
   *  supervision per rig, which is wrong in the direction that loses money.
   *  `prelim` is in NEITHER total — the office and the site vehicle are billed as their own
   *  items, so rolling them into a day-cost would charge them inside every metre drilled and
   *  again on the line the client asked for them on. */
  charge: "rig_day" | "contract_day" | "none" | "prelim";
  note: string;
}

export interface CostingModelShape {
  name: string;
  note: string;
  inputs: Record<string, number>;
  bands: { bands: Band[] };
  method: {
    basis: string;
    divergent_threshold: number;
    marginal_threshold: number;
    depth_departure_threshold: number;
  };
  spread: SpreadLine[];
  laboratory: { key: string; label: string; rate: number; note: string }[];
  /** Stand-ins keyed on how a line is MEASURED, so they fill in any bill rather than only the
   *  one they were written against. `unit: ""` is the catch-all. */
  placeholders: { unit: string; rate: number; label: string }[];
  /** Off shows the bill as it honestly stands — every unpriced line red, nothing invented. */
  use_placeholders: boolean;
  basis_rows: { key: string; label: string; driver: string; divisor: string; note: string }[];
  markup: { key: string; label: string; kind: string; components: string[] }[];
  rounding: { threshold: number; decimals: number }[];
}

/** What one scalar input IS. Declared once on the backend (`model.INPUT_SPECS`) and read by BOTH
 *  the workbook writer and the Library screen — a second copy here would drift the first time
 *  somebody added a knob. */
export interface InputSpec {
  key: string;
  label: string;
  block: string;
  unit: string;
  note: string;
  /** Held as a fraction, said out loud as a percentage. Nothing converts the stored value. */
  percent: boolean;
  /** The template's highlight — the handful that move the answer most. */
  key_assumption: boolean;
}

/** An input the model still carries that nothing reads. Inert by construction, said out loud so a
 *  knob that stopped being connected is not discovered from a number that never moves. */
export interface RetiredInput {
  key: string;
  value: number;
  why: string;
}

/** These three travel with every model payload — library and tender alike. */
export interface ModelDeclarations {
  input_blocks: string[];
  input_specs: InputSpec[];
  charge_labels: Record<string, string>;
  retired: RetiredInput[];
}

export interface LibraryModelResponse extends ModelDeclarations {
  model: CostingModelShape;
  problems: string[];
  usable: boolean;
}

/** A thing worth knowing before pricing. `stop` is the template's "do not price". */
export interface CostingCheck {
  key: string;
  verdict: "ok" | "marginal" | "stop";
  message: string;
  value: number | null;
}

export interface ProgrammeShape {
  rock_fraction: number;
  band: Band | null;
  work_days: number;
  work_days_p10: number;
  work_days_p90: number;
  blended_rate: number;
  method_b_days: number;
  divergence: number;
  allocation: number;
  calendar_days: number;
  rigs_exact: number;
  rigs_required: number;
  standing_hours: number;
  core_boxes: number;
  mazier_samples: number;
  grout_litres: number;
  problems: string[];
}

export interface PricedRow {
  full_ref: string;
  description: string;
  qty: number | null;
  unit: string;
  lump: boolean;
  cost_basis: number | null;
  rate_raw: number | null;
  rate_rounded: number | null;
  /** The estimator's. The rounded figure beside it is only a proposal. */
  rate_to_submit: number | null;
  amount: number | null;
  overridden: boolean;
  /** built | lab | client | prelim | typed | unpriced */
  source: string;
  /** How the line behaves over time, from the bill's own unit: fixed | time | measured. */
  behaviour: string;
  /** The arithmetic behind a proposed rate, in words — "Site vehicle at HK$3,500/week × 122". */
  working: string;
  /** Which build-up basis prices this line ("" when a lab/prelim/typed rate does instead).
   *  The per-class rig-move switch reads it to know whether the split is on. */
  basis_key: string;
  prelim_key: string;
  note: string;
}

export interface AssumptionRow {
  key: string;
  label: string;
  value: string;
  basis: string;
  source: string;
  confidence: "High" | "Medium" | "Low";
  /** Read from the bill or worked out from it — shown, not adjustable. */
  derived: boolean;
  /** The model path this row is ABOUT, in the workbook's own naming ("inputs.gft_ratio",
   *  "spread.gft.rate"). Empty on a derived fact and on a caveat with no single number. This is
   *  what makes the register editable rather than a page of confirmations. */
  edit_path: string;
  /** Held as a fraction, said out loud as a percentage. Display only. */
  edit_percent: boolean;
  status: string;
  reviewed_by: string;
  comment: string;
}

/** A condition somebody wrote down, and the knob it was proposed onto.
 *
 *  `status` is a PERSON's — no stage and no model call writes it — and `applied_value` is non-null
 *  only after a confirmation. A row with no `proposed_path` is not a failure: many real conditions
 *  have no single knob, and it stays listed and unpriced rather than disappearing. */
export interface ConditionRow {
  set_id: string;
  condition_id: string;
  text: string;
  note: string;
  created_by: string;
  created_at: string | null;
  proposed_path: string;
  proposed_value: number | null;
  proposal_basis: string;
  proposal_source: string;
  status: "" | "confirmed" | "rejected";
  decided_by: string;
  decided_at: string | null;
  applied_value: number | null;
  /** Which site-log discussion this condition was born of. 0 = none — typed straight onto the
   *  register, or written before the log existed. The backward half of "why do we believe
   *  this?"; the forward half is the log entry's `became_condition`. */
  born_of_seq: number;
}

/** One site photograph. `caption` and `station` are the PHOTOGRAPHER's — neither is read off the
 *  image, because a model guessing which hole a picture is of attaches real evidence to the wrong
 *  location, which is worse than a picture with no location at all. */
export interface PhotoRow {
  set_id: string;
  photo_id: string;
  filename: string;
  rel_path: string;
  content_type: string;
  caption: string;
  station: string;
  uploaded_by: string;
  uploaded_at: string | null;
}

/** What is VISIBLE in a photograph, and why it might cost money. No access class, no cost, no
 *  status — a machine looking at a hillside cannot classify it, and if it did it would be
 *  believed. `as_condition` is the sentence it becomes if somebody keeps it. */
export interface Observation {
  topic: "access" | "ground" | "obstruction" | "space" | "hazard" | "other";
  what_i_see: string;
  why_it_might_matter: string;
  photo_refs: string[];
  corroboration: string;
  confidence: "high" | "medium" | "low";
  as_condition?: string;
}

export interface PhotoReadResponse {
  set_id: string;
  observations: Observation[];
  photos_read: string[];
  could_not_see: string;
  problems: string[];
  waiting_on?: string;
}

/** A grounded answer. Deliberately has no field for a rate, a duration, a class or a verdict —
 *  there is nowhere to put the kind of answer a chat box would otherwise invent. */
/** One persisted discussion. Everything the reply carried, including what validation stripped —
 *  a discussion that lost a citation on the way through must read that way six months later. */
export interface SiteLogEntry {
  seq: number;
  question: string;
  answer: string;
  cannot_answer: string;
  citations: { source: string; quote: string }[] | null;
  figures: Record<string, string> | null;
  proposes: string;
  stripped: string[] | null;
  asked_by: string;
  asked_at: string | null;
  /** The condition this discussion went on to become, "" when it did not. Derived at read time
   *  from the condition's own provenance. */
  became_condition: string;
  /** That condition's current status — a discussion whose condition was later rejected must not
   *  keep wearing a green badge. "" when undecided or when no condition was born. */
  became_status: "" | "confirmed" | "rejected";
}

export interface AskResponse {
  set_id: string;
  question: string;
  answer: string;
  citations: { source: string; quote: string }[];
  /** Keys of the engine's figures the prose quoted. */
  figures_used: string[];
  /** key → what it is, for the ones actually quoted. */
  figures: Record<string, string>;
  /** The one action it may suggest: record a condition. It writes nothing. */
  proposes: string;
  cannot_answer: string;
  /** What was removed on the way through. A fabricated citation reads exactly like a real one. */
  stripped: string[];
  grounded_in: string[];
  /** This exchange's place in the tender's persisted site log. Memory, not authority. */
  log_seq: number;
  asked_by: string;
}

// --- the bid / no-bid decision (the tender's FIRST decision) ----------------
// navy = the aggregated hard signals, each a deterministic read of an artifact that already
// exists. brass = a DETERMINISTIC rule over them, shown with its reasons and freely overridable.
// The verdict is the human's: nothing on the server records one.
//
// Nothing here is a computed score. Win probability, capacity and strategic fit are the operator's
// own words in `factors`, and a signal that cannot be read honestly is the string "unknown".
export interface BidSignal {
  /** Where this number came from. Every signal carries one. */
  source: string;
  /** Present only when the signal could not be read — and then it says which state made it so. */
  why_unknown?: string;
}

export interface BidSignals {
  deadline: BidSignal & {
    close_date: string | "unknown";
    /** "unknown" whenever the close date's status is not `found` or `confirmed` — the same rule
     *  `on_time` already applies. A date nobody read is not a deadline. */
    days_remaining: number | "unknown";
  };
  open_clarifications: BidSignal & { count: number };
  review_approved: BidSignal & { value: boolean };
  /** `"unknown"` until a review register has been assembled — with no register, nothing is known
   *  about the pack's departures, and 0 of 0 would read as a register that came out clean. */
  departures: BidSignal & { total: number | "unknown"; unresolved: number | "unknown" };
  scope_gaps: BidSignal & { gaps: number | "unknown"; inputs_missing: number | "unknown" };
  coverage: BidSignal & {
    /** "unknown" until a bill is imported — coverage is per bill item, so with no bill there is
     *  nothing to have coverage OF. */
    bills_without_list: string[] | "unknown";
    waiting: number | "unknown";
    partial?: number;
    unmatched_clauses?: number;
  };
}

export interface BidRecommendation {
  /** Only ever `bid` or `clarify`. The rule NEVER proposes no-bid — declining a tender is a
   *  judgement about workload, relationship and risk appetite, none of which the machine has. */
  verdict: "bid" | "clarify";
  /** Each names the signal that produced it, so the proposal shows its evidence. */
  reasons: string[];
  basis: string;
}

export interface BidDecision {
  set_id: string;
  verdict: "bid" | "no_bid" | "clarify";
  rationale: string;
  /** The operator's OWN strategic judgement. Stored verbatim; nothing computes any of it. */
  factors: Record<string, string>;
  decided_by: string;
  decided_at: string;
}

export interface BidBrief {
  set_id: string;
  signals: BidSignals;
  recommendation: BidRecommendation;
  /** `null` until somebody decides — which is a state, not an error. */
  decision: BidDecision | null;
}

export interface ConditionsResponse {
  set_id: string;
  conditions: ConditionRow[];
  unmapped: number;
  undecided: number;
}

export interface CostingResponse extends ModelDeclarations {
  /**
   * Does the money come out the other side exactly once? The one check no rate on this screen can
   * make: a cost basis nothing claims sits OUTSIDE the bill, so every line can be priced,
   * `unpriced` and `placeholders` can both be empty, and a third of the direct cost can still be
   * missing. Branch on `clean`; `headline` is a sentence whatever the news is.
   */
  conservation: {
    clean: boolean;
    difference: number;
    headline: string;
    problems: string[];
  };
  set_id: string;
  rev: number;
  model: CostingModelShape;
  /** Dotted path → `book` | `yours`. Empty means this tender has changed nothing. */
  marks: Record<string, string>;
  using_own_model: boolean;
  quantities: Record<string, { role: string; full_ref: string; description: string; value: number; unit: string; why: string; confirmed: boolean }>;
  unmatched_roles: string[];
  mapping_problems: string[];
  programme: ProgrammeShape;
  checks: CostingCheck[];
  spread: {
    cost_per_rig_day: number;
    /** ONE site team, per day. The site team manages a site — its count never moves with rigs. */
    cost_per_contract_day: number;
    /** ONE GFT, per day. A different resource: the GFT manages rigs, at one per `gft_ratio`. */
    cost_per_gft_day: number;
    site_count: number;
    site_team_per_site: number;
    /** sites × coefficient. Fractional on purpose — half a team is a team shared with another job. */
    site_teams: number;
    gft_ratio: number;
    gfts_required: number;
    rig_cost_programme: number;
    rig_cost_programme_p90: number;
    site_team_cost_programme: number;
    gft_cost_programme: number;
  };
  buildup: {
    rows: { key: string; label: string; quantity: number; total_cost: number; cost_per_unit: number | null; derivation: string; problem: string }[];
    total_direct_cost: number;
    markup_steps: { key: string; label: string; kind: string; rate: number; factor: number }[];
    selling_factor: number;
    problems: string[];
  };
  priced: {
    rows: PricedRow[];
    total: number;
    unpriced: string[];
    /** Lines standing on a stand-in. While this is non-empty the total is PROVISIONAL. */
    placeholders: string[];
    provisional: boolean;
    /** How much of `total` nobody chose. The difference is what has actually been priced. */
    placeholder_total: number;
    problems: string[];
  };
  register: { rows: AssumptionRow[]; gate: string; summary: string; outstanding: number };
  /** Which bill items carry the Class A / Class B rig moves (e.g. {"A": "2.2a", "B": "2.2b"}) —
   *  the switch's targets for pricing the moves per class of site. */
  class_refs: Record<string, string>;
  /** The billed hole count per class — the bill's own numbers, the divisor of each class rate. */
  class_counts: Record<string, number>;
  /** The platform builds typed on effective-Class-B Site groups. Lands inside the Class B move
   *  rate the moment the split is on (SMM S02 ¶2.08(h)); flagged on checks until then. */
  platform_cost_b: number;
}

/** The arithmetic under the Groups screen. Days and the blend, never a rate. */
export interface GroupPreview {
  ready: boolean;
  waiting_on?: string[];
  sources: Record<string, ResolvedNorm>;
  soil_m?: number;
  rock_m?: number;
  soil_days?: number;
  rock_days_charged?: number;
  drilling_days?: number;
  on_site_days?: number;
  rigs?: number;
  blended_m_per_day?: number;
  unfinished?: boolean;
  /** What the as-built corpus expects of a group with THIS rock fraction, beside what the typed
   *  outputs give. The production driver — depth decay is measured at zero and defaults to it. */
  band?: BandCalibration;
}

/** The rock-fraction band a group falls in, and how its own outputs compare with it. */
export interface BandCalibration {
  rock_fraction: number;
  band_label: string;
  band_rate: number;
  band_holes: number;
  indicative_only: boolean;
  expected_work_days: number;
  simulated_work_days: number;
  /** simulated ÷ expected − 1. `null` when no band applies. */
  divergence: number | null;
  note: string;
  problems: string[];
}

// --- app-wide settings (the AI model) --------------------------------------
/** Demo or live, and what it would take to change it.
 *
 *  DEMO IS OFFLINE: no token is spent, no email is sent, and the tenders live in a different
 *  database file from the live ones — so the two can never appear in one list. LIVE is real spend,
 *  real outbound email and real tenders.
 */
export interface ModeResponse {
  demo: boolean;
  /** "operator" when somebody switched it here, "environment" when it is the deployment default.
   *  A person opening the app mid-session cannot tell those apart from the mode alone. */
  source: "operator" | "environment";
  /** The override is a process variable, so a restart returns to `env_default`. Always true; it is
   *  a field rather than an assumption so the screen can state it instead of implying it. */
  reverts_on_restart: boolean;
  env_default: boolean;
  /** The providers live mode would actually call — the text one and the ingest one. */
  providers_needed: string[];
  /** Those with no API key set on the server. Empty means live would work. */
  providers_missing: string[];
  live_ready: boolean;
  /** provider -> the environment variables that would satisfy it. */
  set_to_go_live: Record<string, string[]>;
  /** Why live is refused, in a sentence naming the variable. Empty when it is not. */
  blocked_because: string;
}

export interface LLMSettingsResponse {
  /** The letterhead block, saved on the same screen. */
  company: CompanySettings;
  provider: string; // "" = auto
  /** Who reads the documents. "" falls through to EXTRACTION_PROVIDER, then to `provider`. */
  provider_ingest: string;
  /** Who reads the DRAWING, and with which model. Its own question: the read runs once or twice a
   *  tender, reads a legal-quality sheet, and the map, the access cards, the rig optimiser and the
   *  check against Bill No.2 all rest on it — so the strongest model is worth its cost here and
   *  nowhere else. `model_drawing` names a MODEL rather than a provider, which is the shape that
   *  did not exist: every other model setting is per provider. Both "" fall through to ingest. */
  provider_drawing: string;
  model_drawing: string;
  model_anthropic: string;
  model_deepseek: string;
  model_openai: string;
  providers: string[];
  effective: {
    text_provider: string;
    ingest_provider: string;
    /** Who reads a SCANNED page — the ingest provider, unless it cannot take images. */
    vision_provider: string;
    /** The providers that can be handed a page image at all. */
    vision_capable: string[];
    model_anthropic: string;
    model_deepseek: string;
    model_openai: string;
    model_ingest: string;
    /** Resolved the same way the reader resolves it, so the screen shows what will actually
     *  happen rather than what was typed. */
    drawing_provider: string;
    model_drawing: string;
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
  /** Where this stage sits in its workflow. `stage_total` 0 means the workflow's length is not
   *  certain — show the position alone rather than a total that could be contradicted two stages
   *  later. */
  stage_index?: number;
  stage_total?: number;
  /** Progress WITHIN the current stage. 0/0 means this stage is not batched, or its length is not
   *  known — which is an indeterminate bar, never a bar moving on a timer. */
  done?: number;
  total?: number;
  /** Elapsed only. There is deliberately no remaining-time estimate anywhere in this system: a
   *  countdown that lies is worse than a bar that admits it does not know.
   *
   *  THREE numbers, because two of them used to be added together and shown as one. The server
   *  pool has two workers shared by every workflow, so a job can wait behind another having spent
   *  nothing — and `elapsed_seconds` counts from the request, so that wait was displayed as run
   *  time. A "34 minute" review that queued for 20 was doing 14 minutes of work, and there was no
   *  way to tell a slow review from a queued one. `elapsed_seconds` keeps its meaning (total);
   *  the other two decompose it, and `queued_seconds` freezes when the work starts. */
  elapsed_seconds?: number;
  queued_seconds?: number;
  running_seconds?: number;
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
  /** How this set arrived, and therefore how it is unpacked. `binder` is CUT into page ranges by
   *  `/ingest/split`; `folder` arrived already organised and needs no unpacking; `archive` is a
   *  tender pack still inside its ZIP and is EXTRACTED by `/bridge/archive/extract`. */
  layout?: "binder" | "folder" | "archive";
  /** True when the gate passed itself because there were no page ranges to confirm. */
  auto_approved?: boolean;
  file_count?: number;
  file_pages?: number;
  /** The covered page count. `coverage_detail` is the one with the breaks in it. */
  coverage: number;
  coverage_detail: CoverageDetail;
  parts: PartSpec[];
  /** Folder ingest only — what was routed, and what is stored but read by nothing. */
  summary?: string;
  bills?: BillCandidate[];
  held?: { relative_path: string; suffix: string; bytes: number; note: string }[];
  problems?: string[];
}

/** A workbook in the upload that reads as a bill of quantities.
 *
 *  `proposed` marks the one the app believes is operative and `why` is the sentence that explains
 *  it ("latest addendum: TA #2"). A proposal, never an automatic choice: which file is newest is
 *  very nearly clerical, and being wrong about it prices the wrong bill. */
export interface BillCandidate {
  relative_path: string;
  name: string;
  bytes: number;
  items: number;
  priceable: number;
  notes: string[];
  already_imported: boolean;
  proposed: boolean;
  why: string;
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
  /** The member QUESTION IDS — `GET /rfi/{set_id}` sends ids, not full items. The full items
   *  (and the letter) come from `api.rfiBatch`, which is the sent-batch panel's read. */
  items: string[];
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

// The back of the funnel — final approval, then submission (nodes 46–48).
export interface BridgeFinalApproval {
  set_id: string;
  verdict: "approve" | "revise";
  rationale: string;
  approved_by: string;
  approved_at: string;
  /**
   * What the conservation check said at the moment this verdict was given — frozen on the
   * signature, not looked up. A sentence whatever the news was, because a record that says nothing
   * when the news was good cannot be told from one written before anybody checked. Empty ONLY on a
   * verdict recorded before the column existed, which the screen says out loud.
   */
  conservation: string;
}

export interface BridgeSubmissionRecord {
  set_id: string;
  submitted_at: string;
  deadline: string;
  /** 1 on time, 0 late, null when the deadline is unknown — never an invented pass. */
  on_time: number | null;
  /** The FROZEN letter of offer as it went out — immutable, not the live letter. */
  letter_snapshot: LetterOfOffer;
  price_snapshot: number | null;
  price_str: string;
  approval_ref: string;
  proof: string;
  submitted_by: string;
}

/** GET /bridge/{set_id}/submission — approval + submission + deadline + whether a letter exists. */
export interface BridgeSubmissionState {
  set_id: string;
  approval: BridgeFinalApproval | null;
  submission: BridgeSubmissionRecord | null;
  deadline: string;
  deadline_known: boolean;
  letter_ready: boolean;
  /**
   * The LIVE conservation verdict, beside the frozen one on the approval. Both, deliberately: the
   * frozen one says what was true when somebody signed and this one says what is true now, and a
   * model edited after approval is exactly where they differ. It warns; it never blocks.
   *
   * ALWAYS a sentence — on good news, on bad news, and when nothing could be checked. Branch on
   * `conservation_clean`, never on this being non-empty.
   */
  conservation: string;
  /**
   * `true` every basis balances · `false` the cost does not come out once · `null` the check could
   * not be run. Three states, and collapsing them into two is how "we do not know" comes to read
   * as "it is fine".
   */
  conservation_clean: boolean | null;
}

// The persisted sublet award (node 43): which firm won a package, at what levelled total. A
// Layer-4 record of the human's press — the ranking recommends, the radio decides.
export interface BridgeAward {
  set_id: string;
  package_key: string;
  firm_id: string;
  firm_name: string;
  total: number | null;
  decided_by: string;
  decided_at: string;
}

/** One package's contribution to the combined tender total, from whichever side prices it. */
export interface CombinedSideLine {
  package_key: string;
  side: "self_perform" | "sublet";
  amount: number | null;
  items: number;
  firm_name: string;
  displaced_estimate: number | null;
  note: string;
}

/** GET /bridge/{set_id}/combined-pricing — one tender total from both engines, every gap and
 *  double-count NAMED, fork 5's normalisation questions riding on the payload. */
export interface BridgeCombinedPricing {
  set_id: string;
  routed: boolean;
  self_perform_total: number | null;
  sublet_total: number | null;
  combined_total: number | null;
  lines: CombinedSideLine[];
  unrouted_amount: number | null;
  unrouted_items: number;
  displaced_estimate_total: number;
  letter_price: number | null;
  gaps: string[];
  double_counts: string[];
  notes: string[];
  open_questions: string[];
}

// Closeout — the only feedback edge (nodes 49–53). The tender OUTCOME (did we win) is NOT the
// sublet award; they are kept apart in the API and here.
export interface BridgeOutcome {
  set_id: string;
  status: "submitted" | "won" | "lost" | "withdrawn";
  outcome_notes: string;
  decided_by: string;
  decided_at: string;
}

export interface BridgeLesson {
  id: number;
  set_id: string;
  category: string;
  lesson: string;
  created_at: string;
}

export interface BridgePostSubmissionEvent {
  id: number;
  set_id: string;
  kind: string;
  detail: string;
  created_at: string;
}

/** GET /bridge/{set_id}/closeout — the Closeout tab's one read. */
export interface BridgeCloseoutState {
  set_id: string;
  outcome: BridgeOutcome | null;
  lessons: BridgeLesson[];
  events: BridgePostSubmissionEvent[];
  handover_ready: boolean;
}

/** GET /bridge/{set_id}/handover — a read-only projection, meaningful once won. */
export interface BridgeHandover {
  set_id: string;
  name: string;
  ready: boolean;
  status: string;
  pending: string;
  missing: string[];
  markdown: string;
  sections: Record<string, unknown>;
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
  /** NULL for a workbook — an xlsx has no pages, and `end - start + 1` over the archive's
   *  placeholder bound rendered "1 pages" as though it were a measurement. */
  pages: number | null;
  scanned: boolean;
  has_pdf: boolean;
  /** Why this part yields no text, in words. `scanned` alone reads as "needs OCR" when the real
   *  answer is often "needs the Excel reader". Empty when the part is readable. */
  unreadable_reason?: string;
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

/** What the dispatch gate reports about this tender's document index, before anything is drafted. */
export interface DocIndexState {
  set_id: string;
  tender_slug: string;
  exists: boolean;
  /** ISO-8601 UTC, from the index file's own mtime. Null when there is no index. */
  built_at: string | null;
  documents: number;
  /** How many parts SHOULD be indexed right now — the confirmed bill plus every non-drawing
   *  context part. More than `documents` means something arrived after the index was built. */
  indexable_parts: number;
  kinds: Record<string, number>;
  sor_sections: string[];
  stale: boolean;
  /** The sentence to show, naming the slug. Empty when there is nothing to warn about. */
  warning: string;
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
  /** True when this row's `package_key` is not in the CURRENT scope split — the split has been
   *  re-run since the routing was analysed, so the row describes a package that no longer exists.
   *  Only `GET /route/proposal` can produce it; `POST /route/analyze` recomputes both sides. */
  stale?: boolean;
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
  /** Keys in the stored proposal that the current split no longer produces. Confirming is refused
   *  while this is non-empty — a route recorded against a package that does not exist is a route
   *  the sourcing screen then filters on. */
  stale_packages: string[];
  notes: string[];
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
  /** Warnings on a call that SUCCEEDED — today, the soft review gate's unread-terms notice. Same
   *  field and shape as `/route/analyze`'s, so one renderer serves both. Optional because the
   *  persisted-read endpoint returns the same interface without them. */
  notes?: string[];
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
  /** A sentence about the RUN rather than about any one bundle — today, that the
   *  `GMAIL_TEST_RECIPIENT` valve redirected every recipient away from the firms. Empty on a
   *  normal run. Shown, always: a redirect an operator cannot see is one they will eventually
   *  trust when it is not there. */
  notice?: string;
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
  /** OUR OWN dispatched RFQ, ingested as if it were a return — true only when this record's Gmail
   *  message id is in the outbound ledger, so it is a fact rather than a guess from the content.
   *  A LABEL AND NOTHING MORE: withdrawing stays the only action that changes a comparison, and it
   *  stays the operator's. Always false for a record stored before the id was recorded (the five
   *  from before the guard existed cannot be recovered) and for a manual upload, which has no
   *  message. */
  own_outbound?: boolean;
}

export interface TenderReplies {
  tender_slug: string;
  reply_count: number;
  last_received: string | null;
  replies: TenderReplyInfo[];
  /** EVERY dispatched enquiry for this tender, replied or not — the persisted record of who was
   *  asked, and the only source Level & compare should build its package list from.
   *
   *  `dispatch.bundles` is React state: close the tab and six landed replies rendered as "No
   *  dispatched packages yet", because no dispatch had happened in THAT session. A reply that
   *  exists must be visible regardless of what this browser did. */
  dispatched: { firm_id: string; trade: string; ref: string; firm_name: string; received: boolean }[];
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
  /** `"recorded"` is NOT a `DispatchStatus` — it is the honest answer when the row came from the
   *  persisted correlation registry rather than from this session's own dispatch. The registry
   *  stores identity (ref, tender, firm, trade) and no state, so it can say an enquiry was
   *  RECORDED and cannot say it was sent. Rows rebuilt from it used to render `"sent"`, which
   *  claimed something no stored field supports — a composed-but-never-sent enquiry read as sent
   *  the moment the tab was reloaded. */
  status: DispatchStatus | "recorded";
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


/** GET /integrations/gmail — the transport's own health, plus this run's poller counters.
 *
 *  `polling_enabled` is the field Level & compare exists to surface: it defaults FALSE, so a
 *  default install is not watching for replies at all and the screen is otherwise indistinguishable
 *  from an inbox with nothing in it. */
export interface GmailIntegrationStatus {
  status: string; // "connected" | "not_configured" | "error" | "demo"
  detail: string;
  credentials_configured: boolean;
  token_state: string;
  polling_enabled: boolean;
  poll_seconds: number;
  last_poll_at: string | null;
  last_error: string;
  last_draft_error?: string;
  drafts_created?: number;
  replies_processed: number;
  replies_unmatched: number;
}

// --- the pricing schedule: the INPUT a live estimate is run from ------------
// Mirrors ResourceLine / ScheduleItem / EstimateSchedule in models.py. In DEMO a fixture supplies
// this; in LIVE a person builds it, which is what the Price tab's editor is for.

/** One resource within a direct activity. Either name a rate from the book (`resource_ref`) OR
 *  give an `inline_rate`. `productivity` (output units per hour) converts a quantity into hours
 *  before the rate applies: qty ÷ productivity = hours, hours × rate = amount. */
export interface ResourceLineInput {
  description: string;
  resource_ref: string;
  inline_rate: number | null;
  qty: number;
  unit: string;
  productivity: number | null;
}

/** `direct` prices from resource lines; `indirect` computes from a basis. Anything else is left
 *  alone for s05 to flag as `unclassified_item` — never guessed into a category. */
export type ScheduleCategory = "direct" | "indirect" | "";
export type IndirectBasis = "lump" | "per_week" | "pct_of_direct" | "";

export interface ScheduleItemInput {
  item_id: string; // assigned by s02 when blank
  description: string;
  category: ScheduleCategory;
  unit: string;
  lines: ResourceLineInput[];
  basis: IndirectBasis;
  amount: number | null; // lump
  rate: number | null; // per_week
  pct: number | null; // pct_of_direct
}

export interface EstimateScheduleInput {
  duration_weeks: number | null;
  items: ScheduleItemInput[];
}

export interface ScheduleResponse {
  set_id: string;
  /** false = this tender has never had one. A state the screen shows, not an error. */
  saved: boolean;
  schedule: EstimateScheduleInput;
  margin_pct: number;
  updated_by: string;
  updated_at: string | null;
}

/** The letterhead, stored app-wide. Blank fields stay blank — the letter shows a visible
 *  placeholder rather than inventing a company name. */
export interface CompanySettings {
  company_name: string;
  company_address: string;
  contact_name: string;
  contact_number: string;
}


/**
 * What a streamed tender-pack upload proposed. Nothing has been extracted at this point: the
 * server read the ZIP's central directory, checked the UNCOMPRESSED total against the ceiling
 * before opening any member, and saved a manifest UNAPPROVED. The human approves it through the
 * same gate a single PDF passes, then extraction runs as a job.
 */
export interface ArchiveUploadResponse {
  set_id: string;
  name: string;
  archive_bytes: number;
  uncompressed_bytes: number;
  entries: number;
  content_files: number;
  signature_files: number;
  skipped_files: number;
  /** Grouped by folder, because a 203-row gate is a wall. The person is checking the SHAPE. */
  folders: { folder: string; files: number; category: string; bytes: number; names: string[] }[];
  tier_reason: string;
  parts: number;
  manifest_approved: boolean;
}


/**
 * What the drawing reader made of the sheets it was given. A PROPOSAL — nothing is stored, and the
 * take-off arrives unconfirmed with every unreadable cell marked rather than filled with a zero.
 */
export interface ScheduleReadResponse {
  set_id: string;
  schedule: StationScheduleShape;
  headline: string;
  /** How the schedule sheets were identified, and what was passed over. */
  triage: {
    /** "register" (free, off the cover sheet's text) · "filename" (weaker) · "none". */
    tier: string;
    reason: string;
    headline: string;
    /** The file the register was read from, when one was found. */
    register: string;
    sheets: { number: string; title: string; kind: string; filename: string }[];
    /** Coordinate sheets that are NOT station schedules — the working-area plans. */
    excluded: string[];
    total_drawings: number;
  };
  sheets_read: {
    sheet: string;
    read: boolean;
    problem: string;
    cells_unread: number;
    headline: string;
    /** How many slices the sheet was cut into. >1 means one call could not hold its answer. */
    bands: number;
    /** Slices that failed. Non-empty means the sheet is only PARTLY read. */
    bands_failed: string[];
    /** One record per live call — provider, model, ms, in/out tokens. Empty in DEMO, which is the
     *  honest answer: a demo run cost nothing. */
    calls: { provider: string; model: string; ms: number; in: number | null; out: number | null }[];
    seconds: number;
    tokens_in: number;
    tokens_out: number;
    /** The model that actually read this sheet, "" in DEMO. */
    model: string;
    /** The reader returned rows and put NO NUMBERS in them — the shape of a model that gave up
     *  politely. Empty when it did not. Distinct from `problem` (nothing came back) and from
     *  `cells_unread` (a count, not a verdict): this arrives with `read: true` and a plausible
     *  row count, which is the most reassuring thing on the response. */
    gave_up: string;
    /** True when some slices came back and some did not — rows are missing and no total on this
     *  sheet is the sheet's total. */
    partial: boolean;
  }[];
  /** Sheets that are only partly read, by number. The loudest thing on this response. */
  partial_sheets: string[];
  /** Sheets where the reader outlined the table and read none of it. */
  surrendered_sheets: string[];
  /** How many slices were asked for — 0 is adaptive. Echoed back so a provider comparison can say
   *  which run was whole-sheet and which was quartered. */
  bands_requested: number;
  cells_unread: number;
  bad_rows: string[];
  unread_rows: string[];
  empty_rows: string[];
  duplicate_names: string[];
  problems: string[];
  usable: boolean;
  totals: Partial<ScheduleTotals>;
}
