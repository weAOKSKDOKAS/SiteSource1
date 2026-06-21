// Small shared formatters. Money is whole-dollar HKD; trades are taxonomy keys.

export function hkd(n: number): string {
  return "HK$" + Math.round(n).toLocaleString("en-HK");
}

export function pct(n: number): string {
  return `${Math.round(n * 100)}%`;
}

// "mechanical_plumbing" -> "Mechanical Plumbing"
export function tradeLabel(trade: string): string {
  return trade.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}
