// Presentational maps for the v2 design. Everything here is derived from fields the
// backend already returns (a flag's `source`, a `signal_type`, a `trade` key) — no
// new backend data. Colours/labels mirror the Claude Design handoff.

export function rgba(hex: string, a: number): string {
  const h = hex.replace("#", "");
  const r = parseInt(h.slice(0, 2), 16);
  const g = parseInt(h.slice(2, 4), 16);
  const b = parseInt(h.slice(4, 6), 16);
  return `rgba(${r},${g},${b},${a})`;
}

// ---- Registers (issuing government bodies) -------------------------------
export interface Register {
  short: string;
  name: string;
  color: string;
  home: string;
}

const REGISTER_LIST: { match: RegExp; reg: Register }[] = [
  { match: /buildings/, reg: { short: "BD", name: "Buildings Department", color: "#1F6FEB", home: "https://www.bd.gov.hk/" } },
  { match: /development bureau|devb/, reg: { short: "DEVB", name: "Development Bureau", color: "#6E56CF", home: "https://www.devb.gov.hk/" } },
  { match: /labour/, reg: { short: "LD", name: "Labour Department", color: "#0FB5A6", home: "https://www.labour.gov.hk/" } },
  { match: /companies registry/, reg: { short: "CR", name: "Companies Registry", color: "#44597A", home: "https://www.cr.gov.hk/" } },
  { match: /environmental|epd/, reg: { short: "EPD", name: "Environmental Protection Department", color: "#3F8AD6", home: "https://www.epd.gov.hk/" } },
  { match: /housing/, reg: { short: "HA", name: "Housing Authority", color: "#8A6FE0", home: "https://www.housingauthority.gov.hk/" } },
  { match: /emsd|electrical and mechanical/, reg: { short: "EMSD", name: "EMSD Registration", color: "#0E8C80", home: "https://www.emsd.gov.hk/" } },
  { match: /adjudicat/, reg: { short: "ADJ", name: "Adjudicator's determination", color: "#44597A", home: "https://www.devb.gov.hk/" } },
];

export function registerFor(source: string | null | undefined): Register {
  const s = (source || "").toLowerCase();
  for (const { match, reg } of REGISTER_LIST) if (match.test(s)) return reg;
  const short = (source || "Public record").split(/\s+/).map((w) => w[0]).join("").slice(0, 4).toUpperCase() || "REC";
  return { short, name: source || "Public record", color: "#44597A", home: "https://www.gov.hk/en/residents/" };
}

// ---- Severity (a flag's weight) -----------------------------------------
export type Sev = "fatal" | "warning" | "info";

export interface SevMeta { fg: string; bg: string; dot: string; tag: string; label: string; }

export function sevMeta(s: Sev): SevMeta {
  if (s === "fatal") return { fg: "#E5484D", bg: rgba("#E5484D", 0.1), dot: "#E5484D", tag: "Fatal", label: "Fatal flag" };
  if (s === "warning") return { fg: "#9a6a08", bg: rgba("#D99513", 0.12), dot: "#D99513", tag: "Warning", label: "Warning" };
  return { fg: "#46566b", bg: rgba("#5A6E8C", 0.12), dot: "#5A6E8C", tag: "Info", label: "Info" };
}

// Database flags carry a signal_type, not a severity — give each a face-value
// weight for the table (the firm-level rules live in the Sourcing pipeline).
const FATAL_SIGNALS = new Set(["winding_up", "debarment", "adjudication"]);
export function signalSeverity(signalType: string): Sev {
  if (FATAL_SIGNALS.has(signalType)) return "fatal";
  if (signalType === "info") return "info";
  return "warning";
}

const SIGNAL_LABELS: Record<string, string> = {
  winding_up: "Winding-up",
  debarment: "Debarment",
  safety_prosecution: "Safety prosecution",
  adjudication: "Unpaid adjudication",
  distress_filing: "Distress filing",
  environmental: "Environmental",
};
export function signalLabel(signalType: string): string {
  return SIGNAL_LABELS[signalType] ?? signalType.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

const SIGNAL_COLORS: Record<string, string> = {
  safety_prosecution: "#E5484D",
  debarment: "#C13439",
  winding_up: "#D99513",
  adjudication: "#E0A93A",
  distress_filing: "#B8861E",
  environmental: "#3F8AD6",
};
export function signalColor(signalType: string): string {
  return SIGNAL_COLORS[signalType] ?? "#C13439";
}

// ---- Trades -------------------------------------------------------------
const TRADE_COLORS: Record<string, string> = {
  electrical: "#1F6FEB",
  mechanical_plumbing: "#0FB5A6",
  fire_services: "#6E56CF",
  joinery_fitting_out: "#C2410C",
  reinforced_concrete: "#44597A",
  structural: "#5A6E8C",
  foundation_substructure: "#8A6FE0",
  builders_work: "#46566b",
  external_works: "#3F8AD6",
  drainage_works: "#0E8C80",
};
export function tradeColor(trade: string): string {
  return TRADE_COLORS[trade] ?? "#5A6E8C";
}

export function tradeLabel(trade: string): string {
  return trade.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

// ---- Money --------------------------------------------------------------
export function hkd(n: number): string {
  return "HK$" + Math.round(n).toLocaleString("en-HK");
}
