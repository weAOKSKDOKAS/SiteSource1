import { useEffect, useMemo, useState } from "react";
import { api } from "./api";
import type { Coverage, Firm, PublicFlag, Severity } from "./types";
import { tradeLabel } from "./format";
import { Card, ErrorBanner, SeverityTag, cx } from "./ui";

// Registry signal -> a face-value severity for the table (the firm-level fatal-on-
// two-prosecutions rule is a sourcing decision, applied in the wizard, not here).
const SIGNAL_SEVERITY: Record<string, Severity> = {
  winding_up: "fatal",
  debarment: "fatal",
  adjudication: "fatal",
  safety_prosecution: "warning",
  distress_filing: "warning",
};
const SIGNAL_LABEL: Record<string, string> = {
  winding_up: "Winding-up petition",
  debarment: "Debarment / suspension",
  adjudication: "Unpaid adjudication",
  safety_prosecution: "Safety prosecution",
  distress_filing: "Distress filing",
};

const signalSeverity = (s: string): Severity => SIGNAL_SEVERITY[s] ?? "info";
const signalLabel = (s: string): string => SIGNAL_LABEL[s] ?? s.replace(/_/g, " ");

export function PageDatabase({ coverage }: { coverage: Coverage | null }) {
  const [firms, setFirms] = useState<Firm[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [query, setQuery] = useState("");
  const [trade, setTrade] = useState("all");
  const [flaggedOnly, setFlaggedOnly] = useState(false);

  useEffect(() => {
    api
      .firms()
      .then(setFirms)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, []);

  const trades = useMemo(() => {
    const set = new Set<string>();
    for (const f of firms) for (const t of f.trades) set.add(t);
    return [...set].sort();
  }, [firms]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return firms.filter((f) => {
      if (flaggedOnly && f.public_flags.length === 0) return false;
      if (trade !== "all" && !f.trades.includes(trade)) return false;
      if (q && !(f.name_en.toLowerCase().includes(q) || (f.name_zh ?? "").toLowerCase().includes(q))) return false;
      return true;
    });
  }, [firms, query, trade, flaggedOnly]);

  return (
    <main className="mx-auto max-w-7xl space-y-5 px-5 py-8">
      <div>
        <h1 className="text-xl font-bold tracking-tight text-ink">The proprietary database</h1>
        <p className="mt-1 max-w-3xl text-sm text-ink-soft">
          Subcontractor performance and risk signals fused from official Hong Kong public records. This is the moat: the
          data the sourcing engine cross-references at the award decision — data a generic chatbot cannot reach.
        </p>
      </div>

      {coverage && <CoverageBanner coverage={coverage} />}
      {error && <ErrorBanner message={error} />}

      {/* Controls */}
      <div className="flex flex-wrap items-end gap-3">
        <div className="min-w-[14rem] flex-1">
          <label htmlFor="db-search" className="mb-1 block text-xs font-semibold uppercase tracking-wide text-ink-faint">
            Search by name
          </label>
          <input
            id="db-search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Firm name (English or 中文)…"
            className="w-full rounded-lg border border-line bg-card px-3 py-2 text-sm text-ink placeholder:text-ink-faint focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
          />
        </div>
        <div>
          <label htmlFor="db-trade" className="mb-1 block text-xs font-semibold uppercase tracking-wide text-ink-faint">
            Trade
          </label>
          <select
            id="db-trade"
            value={trade}
            onChange={(e) => setTrade(e.target.value)}
            className="rounded-lg border border-line bg-card px-3 py-2 text-sm text-ink focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
          >
            <option value="all">All trades</option>
            {trades.map((t) => (
              <option key={t} value={t}>
                {tradeLabel(t)}
              </option>
            ))}
          </select>
        </div>
        <label className="flex items-center gap-2 rounded-lg border border-line bg-card px-3 py-2 text-sm text-ink">
          <input
            type="checkbox"
            checked={flaggedOnly}
            onChange={(e) => setFlaggedOnly(e.target.checked)}
            className="h-4 w-4 accent-[var(--color-brand)]"
          />
          Carries a public flag
        </label>
        <span className="tabular ml-auto text-xs text-ink-faint">
          {loading ? "Loading…" : `Showing ${filtered.length} of ${firms.length} firms`}
        </span>
      </div>

      {/* Table */}
      <Card className="overflow-hidden">
        <div className="max-h-[68vh] overflow-auto">
          <table className="w-full min-w-[860px] text-sm">
            <thead className="sticky top-0 z-10 bg-card">
              <tr className="border-b border-line text-left text-xs uppercase tracking-wide text-ink-faint">
                <th className="px-4 py-2.5 font-semibold">Firm</th>
                <th className="px-3 py-2.5 font-semibold">Grade</th>
                <th className="px-3 py-2.5 font-semibold">Value band</th>
                <th className="px-3 py-2.5 font-semibold">Trades</th>
                <th className="px-4 py-2.5 font-semibold">Public risk flags</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line-soft">
              {filtered.map((f) => (
                <FirmRow key={f.firm_id} firm={f} />
              ))}
              {!loading && filtered.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-4 py-8 text-center text-sm text-ink-faint">
                    No firms match these filters.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </Card>

      <p className="text-xs text-ink-faint">
        Real Hong Kong public-record data — every flag links to its government source; click to verify on screen. The
        illustrative firms used in the Sourcing demo are not shown here.
      </p>
    </main>
  );
}

function CoverageBanner({ coverage }: { coverage: Coverage }) {
  return (
    <Card className="p-5">
      <p className="text-base text-ink">
        Screening against{" "}
        <span className="tabular text-2xl font-bold text-ink">{coverage.total_firms.toLocaleString("en-HK")}</span> firms
        sourced from official Hong Kong registers —{" "}
        <span className="tabular text-2xl font-bold text-ink">{coverage.flagged_firms.toLocaleString("en-HK")}</span> carry
        verified public risk flags, each linked to its government source.
      </p>
      <div className="mt-3 flex flex-wrap gap-2">
        {Object.entries(coverage.flags_by_type).map(([type, n]) => {
          const sev = signalSeverity(type);
          return (
            <span
              key={type}
              className="inline-flex items-center gap-1.5 rounded-md border border-line bg-paper/50 px-2 py-1 text-xs text-ink-soft"
            >
              <span
                className={cx(
                  "h-1.5 w-1.5 rounded-full",
                  sev === "fatal" ? "bg-bad" : sev === "warning" ? "bg-warn" : "bg-brand",
                )}
              />
              {signalLabel(type)} <span className="tabular font-semibold text-ink">{n}</span>
            </span>
          );
        })}
      </div>
    </Card>
  );
}

function FirmRow({ firm }: { firm: Firm }) {
  return (
    <tr className="align-top hover:bg-line-soft/40">
      <td className="px-4 py-2.5">
        <div className="font-medium text-ink">{firm.name_en}</div>
        {firm.name_zh && <div className="text-xs text-ink-faint">{firm.name_zh}</div>}
      </td>
      <td className="tabular px-3 py-2.5 text-ink-soft">{firm.registered_grade || "—"}</td>
      <td className="px-3 py-2.5 text-ink-soft">{firm.value_band || "—"}</td>
      <td className="px-3 py-2.5">
        <div className="flex flex-wrap gap-1">
          {firm.trades.map((t) => (
            <span key={t} className="rounded bg-line-soft px-1.5 py-0.5 text-xs text-ink-soft">
              {tradeLabel(t)}
            </span>
          ))}
        </div>
      </td>
      <td className="px-4 py-2.5">
        {firm.public_flags.length === 0 ? (
          <span className="text-xs text-ink-faint">— clean —</span>
        ) : (
          <ul className="space-y-1.5">
            {firm.public_flags.map((flag, i) => (
              <FlagLine key={i} flag={flag} />
            ))}
          </ul>
        )}
      </td>
    </tr>
  );
}

function FlagLine({ flag }: { flag: PublicFlag }) {
  const isUrl = !!flag.reference && /^https?:\/\//.test(flag.reference);
  return (
    <li className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
      <SeverityTag severity={signalSeverity(flag.signal_type)} />
      <span className="text-sm font-medium text-ink">{signalLabel(flag.signal_type)}</span>
      {flag.label && <span className="text-xs text-ink-faint">{flag.label}</span>}
      {isUrl ? (
        <a
          href={flag.reference!}
          target="_blank"
          rel="noreferrer noopener"
          className="text-xs font-semibold text-brand hover:underline"
        >
          {flag.source ?? "government source"} ↗
        </a>
      ) : (
        flag.source && <span className="text-xs text-ink-faint">{flag.source}</span>
      )}
    </li>
  );
}
