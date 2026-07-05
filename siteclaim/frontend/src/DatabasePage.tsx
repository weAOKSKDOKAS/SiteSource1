import { useEffect, useState } from "react";

import { api } from "./api";
import { FirmRecord, Pill } from "./components";
import { tradeLabel } from "./format";
import type { Coverage, FirmProfile, FirmsPage, RiskFlag } from "./types";
import { Card, Drawer, ErrorBanner, LayerBadge, SectionHeader, StatCallout } from "./ui";

const PAGE_SIZES = [10, 25, 50, 100];

function worstSeverity(flags: RiskFlag[]): "fatal" | "warning" | null {
  if (flags.some((f) => f.severity === "fatal")) return "fatal";
  if (flags.some((f) => f.severity === "warning")) return "warning";
  return null;
}

// The proprietary database (Layer 3) — coverage aggregates over the screened public-register
// pool, plus a searchable firm browse. All figures and rows are the real-provenance scrape
// only; illustrative demo firms are excluded and partner-archive firms never appear.
export function DatabasePage() {
  const [cov, setCov] = useState<Coverage | null>(null);
  const [q, setQ] = useState("");
  const [trade, setTrade] = useState("");
  const [limit, setLimit] = useState(25);
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<FirmsPage | null>(null);
  const [detail, setDetail] = useState<FirmProfile | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.coverage().then(setCov).catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  useEffect(() => {
    const id = setTimeout(() => {
      api
        .firms({ q: q || undefined, trade: trade || undefined, limit, offset })
        .then(setPage)
        .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
    }, 160); // light debounce so typing does not spam the endpoint
    return () => clearTimeout(id);
  }, [q, trade, limit, offset]);

  const setFilter = (fn: () => void) => {
    fn();
    setOffset(0); // any filter change returns to the first page
  };

  const total = page?.total ?? 0;
  const shownFrom = total === 0 ? 0 : offset + 1;
  const shownTo = Math.min(offset + limit, total);

  return (
    <div className="min-w-0 space-y-5">
      <SectionHeader
        title="Proprietary database"
        lead="Fused public records and private closeout reports — the grounding corpus applied at the moment of a decision."
        right={<LayerBadge layer="L3" />}
      />
      {error && <ErrorBanner message={error} />}

      {cov && (
        <>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <StatCallout label="Firms (public register)" value={cov.total_firms} tone="violet" />
            <StatCallout label="Carrying a public flag" value={cov.flagged_firms} tone="violet" />
            <StatCallout label="Distinct trades" value={cov.trades.length} tone="violet" />
            <StatCallout label="Flag types" value={Object.keys(cov.flags_by_type).length} tone="violet" />
          </div>

          <Card className="p-4">
            <div className="mb-2 flex flex-wrap items-baseline gap-2">
              <h3 className="text-sm font-semibold text-ink">Flags by type</h3>
              <span className="text-xs text-ink-faint">
                official registers cross-checked — every stored flag carries its issuing source and reference
              </span>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {Object.entries(cov.flags_by_type).map(([k, n]) => (
                <span key={k} title={`${n} verified public record(s) of this type across the screened pool`} className="cursor-help">
                  <Pill tone="neutral">{`${k.replace(/_/g, " ")} · ${n}`}</Pill>
                </span>
              ))}
            </div>
          </Card>

          {/* Firm browse */}
          <Card className="p-0">
            <div className="flex flex-wrap items-center gap-2 border-b border-line-soft px-4 py-3">
              <h3 className="text-sm font-semibold text-ink">Firms</h3>
              <input
                value={q}
                onChange={(e) => setFilter(() => setQ(e.target.value))}
                placeholder="Search by name…"
                className="min-w-40 flex-1 rounded-lg border border-line px-2.5 py-1.5 text-sm focus:border-brand focus:outline-none"
              />
              <select
                value={trade}
                onChange={(e) => setFilter(() => setTrade(e.target.value))}
                className="rounded-lg border border-line px-2 py-1.5 text-sm text-ink-soft focus:border-brand focus:outline-none"
              >
                <option value="">All trades</option>
                {cov.trades.map((t) => (
                  <option key={t} value={t}>{tradeLabel(t)}</option>
                ))}
              </select>
              <select
                value={limit}
                onChange={(e) => setFilter(() => setLimit(Number(e.target.value)))}
                className="rounded-lg border border-line px-2 py-1.5 text-sm text-ink-soft focus:border-brand focus:outline-none"
              >
                {PAGE_SIZES.map((n) => (
                  <option key={n} value={n}>{n} / page</option>
                ))}
              </select>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-line-soft text-left text-xs text-ink-faint">
                    <th className="px-4 py-2">Reference</th>
                    <th className="px-4 py-2">Firm</th>
                    <th className="px-4 py-2">Grade</th>
                    <th className="px-4 py-2">Band</th>
                    <th className="px-4 py-2">Trades</th>
                    <th className="px-4 py-2">Record</th>
                  </tr>
                </thead>
                <tbody>
                  {page && page.items.length === 0 && (
                    <tr><td className="px-4 py-4 text-ink-faint" colSpan={6}>No firms match — clear the filters.</td></tr>
                  )}
                  {page?.items.map((f) => {
                    const worst = worstSeverity(f.public_flags);
                    return (
                      <tr
                        key={f.firm_id}
                        onClick={() => setDetail(f)}
                        title="Open the firm record"
                        className="cursor-pointer border-b border-line-soft transition-colors last:border-0 hover:bg-paper-soft/70"
                      >
                        <td className="tabular px-4 py-2 text-xs text-ink-faint">{f.firm_id}</td>
                        <td className="px-4 py-2 font-medium text-ink">{f.name}</td>
                        <td className="px-4 py-2 text-ink-soft">{f.registered_grade || "—"}</td>
                        <td className="px-4 py-2 text-ink-soft">{f.value_band.replace(/_/g, " ") || "—"}</td>
                        <td className="px-4 py-2">
                          <span className="flex flex-wrap gap-1">
                            {f.trades.slice(0, 2).map((t) => <Pill key={t} tone="violet">{tradeLabel(t)}</Pill>)}
                            {f.trades.length > 2 && <Pill tone="neutral">{`+${f.trades.length - 2}`}</Pill>}
                          </span>
                        </td>
                        <td className="px-4 py-2">
                          {worst === "fatal" ? (
                            <Pill tone="bad">{`${f.public_flags.length} flag${f.public_flags.length === 1 ? "" : "s"}`}</Pill>
                          ) : worst === "warning" ? (
                            <Pill tone="warn">{`${f.public_flags.length} flag${f.public_flags.length === 1 ? "" : "s"}`}</Pill>
                          ) : (
                            <Pill tone="neutral">clean</Pill>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line-soft px-4 py-2.5 text-xs text-ink-faint">
              <span className="tabular">{shownFrom}–{shownTo} of {total}</span>
              <div className="flex items-center gap-1.5">
                <button
                  type="button"
                  disabled={offset <= 0}
                  onClick={() => setOffset(Math.max(0, offset - limit))}
                  className="rounded-md border border-line px-2.5 py-1 font-semibold text-ink-soft enabled:hover:bg-line-soft disabled:opacity-40"
                >
                  ← Prev
                </button>
                <button
                  type="button"
                  disabled={offset + limit >= total}
                  onClick={() => setOffset(offset + limit)}
                  className="rounded-md border border-line px-2.5 py-1 font-semibold text-ink-soft enabled:hover:bg-line-soft disabled:opacity-40"
                >
                  Next →
                </button>
              </div>
            </div>
          </Card>

          <p className="text-xs text-ink-faint">
            The browse shows the real <span className="tabular">{cov.provenance}</span> register firms only — the same 140/46
            population the figures above count. Illustrative demo firms are present-but-excluded here and absent in the live
            profile; partner-archive firms never appear. Every flag carries its issuing source and reference.
          </p>
        </>
      )}

      <Drawer
        open={detail != null}
        onClose={() => setDetail(null)}
        eyebrow="Firm record"
        tone={detail && detail.public_flags.some((f) => f.severity === "fatal") ? "bad" : "violet"}
        title={detail?.name ?? ""}
        subtitle={detail && <span className="tabular">{detail.firm_id}</span>}
        footer="Real-provenance register firm — every flag carries its issuing government source and reference."
      >
        {detail && <FirmRecord firm={detail} />}
      </Drawer>
    </div>
  );
}
