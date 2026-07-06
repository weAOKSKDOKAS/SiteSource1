// Small shared formatters. Money is whole-dollar HKD; trades are taxonomy keys.

export function hkd(n: number): string {
  return "HK$" + Math.round(n).toLocaleString("en-HK");
}

// Money that tolerates null/undefined (an em dash) and keeps cents — for the estimator /
// benchmark rate tables where a rate-only or unpriced line has no amount.
export function money(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return "HK$" + n.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

export function pct(n: number): string {
  return `${Math.round(n * 100)}%`;
}

// "mechanical_plumbing" -> "Mechanical Plumbing"; a section sub-package key
// "ground_investigation:H" -> "Ground Investigation · Section H".
export function tradeLabel(trade: string): string {
  const [base, section] = trade.split(":");
  const label = base.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  return section ? `${label} · Section ${section}` : label;
}
