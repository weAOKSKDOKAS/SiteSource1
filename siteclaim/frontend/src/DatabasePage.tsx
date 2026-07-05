import { useEffect, useMemo, useRef, useState } from "react";

import { api } from "./api";
import { CiteProvider, useCite, type Citation } from "./cite";
import { FirmRecord, Pill } from "./components";
import { tradeLabel } from "./format";
import {
  flagReference,
  flagSignal,
  flagSource,
  registerFor,
  rgba,
  shownEmail,
  signalLabel,
  worstFlagSeverity,
  type Register,
} from "./theme";
import type { Coverage, FirmProfile, FirmsPage } from "./types";
import { Card, Drawer, ErrorBanner, cx } from "./ui";

const PAGE_SIZES = [10, 25, 50, 100];
const MONTHS: Record<string, number> = { jan: 0, feb: 1, mar: 2, apr: 3, may: 4, jun: 5, jul: 6, aug: 7, sep: 8, oct: 9, nov: 10, dec: 11 };

// The exact layered hero background from the design (radial violet + radial teal over the
// navy-depth gradient). Kept inline — it is cleaner than composing three gradient utilities.
const HERO_BG =
  "radial-gradient(820px 420px at 86% -20%, rgba(110,86,207,0.55), transparent 62%)," +
  "radial-gradient(680px 520px at 6% 130%, rgba(15,181,166,0.34), transparent 56%)," +
  "linear-gradient(135deg,#0F1B2D 0%, #14213B 55%, #182347 100%)";

function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const on = () => setReduced(mq.matches);
    on();
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);
  return reduced;
}

function parseRegDate(s: string): Date | null {
  const m = /(\d{1,2})\s+([A-Za-z]{3})\w*\s+(\d{4})/.exec(s || "");
  if (!m) return null;
  const mo = MONTHS[m[2].toLowerCase()];
  return mo == null ? null : new Date(Number(m[3]), mo, Number(m[1]));
}

// A windowed pager: 1 … 7 [8] 9 … 55
function pageWindow(current: number, totalPages: number, span = 1): (number | "…")[] {
  const keep = new Set<number>([1, totalPages]);
  for (let i = current - span; i <= current + span; i++) if (i >= 1 && i <= totalPages) keep.add(i);
  const sorted = [...keep].filter((n) => n >= 1 && n <= totalPages).sort((a, b) => a - b);
  const out: (number | "…")[] = [];
  let prev = 0;
  for (const p of sorted) {
    if (p - prev > 1) out.push("…");
    out.push(p);
    prev = p;
  }
  return out;
}

// The proprietary database (Layer 3) — the animated data-asset showcase over the full CIC
// register. Coverage is stated as an honest composition; the browse and every figure count
// the real-provenance population only (illustrative demo firms never appear). Wrapped in the
// CiteProvider so a register chip or a flag reference opens the shared government-record panel.
export function DatabasePage() {
  return (
    <CiteProvider>
      <DatabaseView />
    </CiteProvider>
  );
}

function DatabaseView() {
  const cite = useCite();
  const [cov, setCov] = useState<Coverage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [debouncedQ, setDebouncedQ] = useState("");
  const [limit, setLimit] = useState(25);
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<FirmsPage | null>(null);
  const [loading, setLoading] = useState(false);
  const [detail, setDetail] = useState<FirmProfile | null>(null);
  const reduced = usePrefersReducedMotion();

  useEffect(() => {
    api.coverage().then(setCov).catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  // debounce the search box → back to the first page
  useEffect(() => {
    const t = setTimeout(() => { setDebouncedQ(q.trim()); setOffset(0); }, 300);
    return () => clearTimeout(t);
  }, [q]);

  // server-side fetch on page / size / search change (latest-wins)
  const reqId = useRef(0);
  useEffect(() => {
    const id = ++reqId.current;
    setLoading(true);
    api.firms({ limit, offset, q: debouncedQ || undefined })
      .then((p) => { if (id === reqId.current) setPage(p); })
      .catch(() => { if (id === reqId.current) setPage({ items: [], total: 0, limit, offset }); })
      .finally(() => { if (id === reqId.current) setLoading(false); });
  }, [limit, offset, debouncedQ]);

  const total = cov?.total_firms ?? 0;
  const flagged = cov?.flagged_count ?? cov?.flagged_firms ?? 0;
  const registers = cov?.registers ?? 0;

  // count-up over the headline figures (settles instantly under reduced motion)
  const [counts, setCounts] = useState({ firms: 0, flagged: 0, registers: 0 });
  const raf = useRef(0);
  useEffect(() => {
    if (!cov) return;
    if (reduced) { setCounts({ firms: total, flagged, registers }); return; }
    const dur = 1150, t0 = performance.now();
    const tick = (now: number) => {
      const p = Math.min(1, (now - t0) / dur), e = 1 - Math.pow(1 - p, 3);
      setCounts({ firms: Math.round(total * e), flagged: Math.round(flagged * e), registers: Math.round(registers * e) });
      if (p < 1) raf.current = requestAnimationFrame(tick);
    };
    raf.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf.current);
  }, [cov, total, flagged, registers, reduced]);

  // the breathing risk matrix — a representative 240-cell grid, proportionally flagged
  const cells = useMemo(() => {
    const N = 240, flaggedN = total > 0 ? Math.max(1, Math.round((flagged / total) * N)) : 0;
    return Array.from({ length: N }, (_, i) => ({
      color: i < flaggedN ? (i < flaggedN * 0.7 ? "#E5484D" : "#D99513") : "rgba(159,180,214,0.26)",
      dur: (2.4 + (i % 5) * 0.45).toFixed(2) + "s",
      delay: ((i % 13) * 0.13).toFixed(2) + "s",
    }));
  }, [total, flagged]);

  const registerChips = useMemo(() => {
    const map = new Map<string, Register>();
    for (const s of cov?.flag_sources ?? []) { const r = registerFor(s); map.set(r.short, r); }
    return [...map.values()];
  }, [cov]);

  const totalPages = Math.max(1, Math.ceil((page?.total ?? 0) / limit));
  const current = Math.floor(offset / limit) + 1;
  const goPage = (p: number) => setOffset((Math.max(1, Math.min(p, totalPages)) - 1) * limit);
  const from = (page?.total ?? 0) === 0 ? 0 : offset + 1;
  const to = Math.min(offset + limit, page?.total ?? 0);

  return (
    <div className="min-w-0 space-y-5">
      {error && <ErrorBanner message={error} />}

      {/* HERO — the centrepiece (inline styles for the layered gradient + matrix). */}
      <section
        className="relative overflow-hidden rounded-[22px] px-7 py-8 text-white sm:px-9"
        style={{ background: HERO_BG, boxShadow: "0 24px 60px -28px rgba(15,27,45,0.55)" }}
      >
        <div className="relative z-[2] flex flex-wrap items-end justify-between gap-10">
          <div className="max-w-xl">
            <div className="tabular mb-4 inline-flex items-center gap-2 rounded-full border border-white/20 px-3 py-1.5 text-[11px] uppercase tracking-[0.16em] text-[#9fb4d6]">
              <span className="h-1.5 w-1.5 rounded-full" style={{ background: "#0FB5A6" }} /> The proprietary data asset
            </div>
            <h1 className="font-display text-[34px] font-bold leading-[1.05] tracking-[-0.025em] sm:text-[38px]">
              The Hong Kong subcontractor register, screened.
            </h1>
            <p className="mt-3.5 max-w-lg text-sm leading-relaxed text-[#b9c7de]">
              The full CIC Registered Subcontractors register — every firm with its registered trades and enquiry
              contact — cross-referenced against the public enforcement record. The moat is the data and the
              cross-reference, not the model.
            </p>
          </div>

          {/* RISK OVERLAY breathing matrix */}
          <div className="flex-none">
            <div className="mb-3 flex items-center justify-between gap-3.5">
              <span className="tabular text-[10.5px] uppercase tracking-[0.12em] text-[#9fb4d6]">Risk overlay</span>
              <div className="tabular flex gap-3 text-[10px] text-[#9fb4d6]">
                <span className="inline-flex items-center gap-1.5"><span className="h-2 w-2 rounded-[2px]" style={{ background: "#E5484D" }} />flagged</span>
                <span className="inline-flex items-center gap-1.5"><span className="h-2 w-2 rounded-[2px]" style={{ background: "rgba(159,180,214,0.30)" }} />clear</span>
              </div>
            </div>
            <div className="grid w-[300px] gap-[3.5px] sm:w-[360px]" style={{ gridTemplateColumns: "repeat(24,1fr)" }}>
              {cells.map((c, i) => (
                <span
                  key={i}
                  className="w-full rounded-[2px]"
                  style={{ aspectRatio: "1", background: c.color, animation: `ssPulse ${c.dur} ease-in-out ${c.delay} infinite` }}
                />
              ))}
            </div>
          </div>
        </div>

        {/* Headline figures (count-up), register chips, and the honest composition line. */}
        <div className="relative z-[2] mt-6 border-t border-white/10 pt-5">
          <div className="flex flex-wrap items-center gap-x-9 gap-y-4">
            <Figure value={counts.firms} label="Subcontractors screened" />
            <Figure value={counts.flagged} label="With an enforcement flag" tone="danger" />
            <Figure value={counts.registers} label="Issuing registers cross-checked" />
            <div className="flex flex-wrap items-center gap-2 sm:ml-auto">
              {registerChips.map((r) => (
                <button
                  key={r.short}
                  type="button"
                  onClick={() => cite.open({
                    source: r.name,
                    reference: r.home,
                    detail: `${r.name} — cross-checked against all ${total.toLocaleString("en-HK")} screened firms; adverse records matched by company name and registration number.`,
                    date: null,
                  })}
                  title={`${r.name} — open the government record`}
                  className="tabular inline-flex cursor-pointer items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-[11px] text-[#dbe5f4] transition hover:brightness-125"
                  style={{ background: "rgba(255,255,255,0.04)", borderColor: rgba(r.color, 0.4) }}
                >
                  <span className="h-[7px] w-[7px] rounded-full" style={{ background: r.color }} />{r.short}
                </button>
              ))}
            </div>
          </div>
          {cov && (
            <p className="mt-3.5 text-[12.5px] leading-relaxed text-[#9fb4d6]">
              <span className="font-semibold text-[#cdd9ec]">{cov.register_count.toLocaleString("en-HK")}</span> on the CIC subcontractor register
              <span className="opacity-50"> · </span>
              <span className="font-semibold text-[#cdd9ec]">{cov.overlay_count.toLocaleString("en-HK")}</span> from enforcement &amp; offer records
              <span className="opacity-50"> · </span>
              <span className="font-semibold text-[#FFB3B3]">{cov.flagged_count}</span> flagged
            </p>
          )}
        </div>
      </section>

      {/* CONTROLS */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative flex h-11 min-w-64 flex-1 items-center gap-2.5 rounded-xl border border-line bg-card px-3.5 shadow-card">
          <span className="text-brand" aria-hidden>⌕</span>
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search the register by company name…"
            className="h-full flex-1 border-none bg-transparent text-sm text-ink outline-none"
          />
          {loading && <span className="ssLive h-2 w-2 shrink-0 rounded-full bg-brand" title="Searching the register…" aria-hidden />}
        </div>
        <div className="flex items-center gap-2">
          <span className="tabular text-[11px] text-ink-faint">Rows</span>
          <div className="inline-flex overflow-hidden rounded-lg border border-line">
            {PAGE_SIZES.map((n) => (
              <button
                key={n}
                type="button"
                onClick={() => { setLimit(n); setOffset(0); }}
                className={cx(
                  "tabular border-l border-line px-3 py-2 text-xs font-semibold first:border-l-0 transition-colors",
                  limit === n ? "bg-ink text-white" : "bg-card text-ink-soft hover:bg-line-soft",
                )}
              >
                {n}
              </button>
            ))}
          </div>
        </div>
        <div className="tabular whitespace-nowrap text-[12.5px] text-ink-soft">
          <span className="font-bold text-ink">{total.toLocaleString("en-HK")}</span> registered subcontractors
          <span className="text-ink-faint"> · </span>
          <span className="font-bold text-bad">{flagged}</span> with enforcement flags
        </div>
      </div>

      {/* TABLE */}
      <Card className="overflow-hidden p-0">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[880px] border-collapse text-sm">
            <thead>
              <tr className="border-b border-line-soft bg-paper-soft/70 text-left">
                {["Company", "Registered trades", "Registration", "Enforcement"].map((h) => (
                  <th key={h} className="tabular px-4 py-3 text-[10.5px] font-semibold uppercase tracking-eyebrow text-ink-faint">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {page?.items.map((f) => <FirmRow key={f.firm_id} firm={f} onOpen={() => setDetail(f)} onCite={cite.open} />)}
              {!loading && (page?.items.length ?? 0) === 0 && (
                <tr><td colSpan={4} className="px-4 py-10 text-center text-sm text-ink-faint">No registered subcontractor matches “{debouncedQ}”.</td></tr>
              )}
            </tbody>
          </table>
        </div>

        {/* PAGER */}
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line-soft px-4 py-3">
          <span className="tabular text-xs text-ink-faint">
            {from.toLocaleString("en-HK")}–{to.toLocaleString("en-HK")} of {(page?.total ?? 0).toLocaleString("en-HK")}
          </span>
          <div className="flex items-center gap-1.5">
            <PagerBtn label="« First" disabled={current <= 1} onClick={() => goPage(1)} />
            <PagerBtn label="‹ Prev" disabled={current <= 1} onClick={() => goPage(current - 1)} />
            {pageWindow(current, totalPages).map((p, i) => p === "…"
              ? <span key={`e${i}`} className="px-1.5 text-ink-faint">…</span>
              : (
                <button
                  key={p}
                  type="button"
                  onClick={() => goPage(p)}
                  className={cx(
                    "tabular h-8 min-w-8 rounded-md border px-2 text-[13px] font-semibold transition-colors",
                    p === current ? "border-brand bg-brand text-white" : "border-line bg-card text-ink-soft hover:bg-line-soft",
                  )}
                >
                  {p}
                </button>
              ))}
            <PagerBtn label="Next ›" disabled={current >= totalPages} onClick={() => goPage(current + 1)} />
            <PagerBtn label="Last »" disabled={current >= totalPages} onClick={() => goPage(totalPages)} />
          </div>
        </div>
      </Card>

      <p className="text-xs text-ink-faint">
        The browse and every figure count the real-provenance population only — the CIC register plus the
        enforcement overlay. Illustrative demo firms are present-but-excluded here and absent in the live profile;
        every flag carries its issuing source and reference.
      </p>

      <Drawer
        open={detail != null}
        onClose={() => setDetail(null)}
        eyebrow="Firm record"
        tone={detail && worstFlagSeverity(detail.public_flags) === "fatal" ? "bad" : "violet"}
        title={detail?.name ?? ""}
        subtitle={detail && (
          <span className="flex flex-wrap items-center gap-2">
            <span className="tabular">{detail.firm_id}</span>
            {detail.name_zh && <span className="text-ink-faint">{detail.name_zh}</span>}
          </span>
        )}
        footer="Real-provenance register firm — every enforcement flag carries its issuing government source and reference."
      >
        {detail && <FirmRecord firm={detail} />}
      </Drawer>
    </div>
  );
}

function Figure({ value, label, tone }: { value: number; label: string; tone?: "danger" }) {
  return (
    <div>
      <div className="relative inline-block">
        <span className="tabular font-display text-[46px] font-bold leading-[0.9]" style={{ color: tone === "danger" ? "#FF8E8E" : "#fff" }}>
          {value.toLocaleString("en-HK")}
        </span>
        {tone === "danger" && <span className="absolute inset-x-0 -bottom-0.5 h-[3px] rounded-[2px]" style={{ background: "linear-gradient(90deg,#E5484D,#D99513)" }} />}
      </div>
      <div className="mt-2 text-[11.5px] uppercase tracking-[0.05em] text-[#9fb4d6]">{label}</div>
    </div>
  );
}

function PagerBtn({ label, disabled, onClick }: { label: string; disabled: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="h-8 rounded-md border border-line bg-card px-2.5 text-[12.5px] font-semibold text-ink-soft enabled:hover:bg-line-soft disabled:text-ink-faint/60"
    >
      {label}
    </button>
  );
}

function FirmRow({ firm, onOpen, onCite }: { firm: FirmProfile; onOpen: () => void; onCite: (c: Citation) => void }) {
  const flags = firm.public_flags;
  const worst = worstFlagSeverity(flags);
  const flagged = flags.length > 0;
  const accent = worst === "fatal" ? "#E5484D" : worst === "warning" ? "#D99513" : worst ? "#8a98ab" : "#2EA56A";
  const trades = firm.trades.slice(0, 3);
  const moreTrades = firm.trades.length - trades.length;
  const email = shownEmail(firm.enquiry_email);
  const expiry = parseRegDate(firm.expiry_date);
  const valid = expiry ? expiry.getTime() >= Date.now() : null;

  return (
    <tr
      onClick={onOpen}
      title="Open the firm record"
      className={cx("cursor-pointer border-b border-line-soft transition-colors last:border-0 hover:bg-paper-soft/70", flagged && "bg-bad-bg/30")}
    >
      <td className="px-4 py-3 align-top" style={{ borderLeft: `3px solid ${accent}` }}>
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-display text-sm font-semibold text-ink">{firm.name}</span>
          {firm.name_zh && <span className="text-xs text-ink-faint">{firm.name_zh}</span>}
        </div>
        {firm.description && <div className="mt-0.5 max-w-md text-xs leading-snug text-ink-soft">{firm.description}</div>}
        {email ? (
          <span className="tabular mt-1 inline-flex items-center gap-1.5 text-[11px] text-brand">✉ {email}</span>
        ) : (
          <span className="tabular mt-1 inline-flex items-center gap-1.5 text-[11px] italic text-ink-faint">✉ email not listed</span>
        )}
      </td>
      <td className="px-4 py-3 align-top">
        <span className="flex max-w-[280px] flex-wrap gap-1.5">
          {trades.map((t) => <Pill key={t} tone="violet">{tradeLabel(t)}</Pill>)}
          {moreTrades > 0 && <span className="text-[11px] text-ink-faint">+{moreTrades}</span>}
        </span>
      </td>
      <td className="px-4 py-3 align-top whitespace-nowrap">
        {firm.registered_grade && <div className="text-xs text-ink-soft">{firm.registered_grade}</div>}
        {valid == null ? (
          <span className="text-xs text-ink-faint">—</span>
        ) : (
          <span className={cx("inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-semibold", valid ? "bg-ok-bg text-ok" : "bg-bad-bg text-bad")}>
            <span className={cx("h-1.5 w-1.5 rounded-full", valid ? "bg-ok" : "bg-bad")} />{valid ? "Valid" : "Expired"}
          </span>
        )}
        {firm.expiry_date && <div className="tabular mt-1 text-[10.5px] text-ink-faint">to {firm.expiry_date}</div>}
        {firm.br_no && <div className="tabular mt-0.5 text-[10.5px] text-ink-faint">BR {firm.br_no}</div>}
      </td>
      <td className="px-4 py-3 align-top">
        {flagged ? (
          <>
            <button
              type="button"
              onClick={(e) => { e.stopPropagation(); onCite({ source: flagSource(flags[0]), reference: flagReference(flags[0]), detail: flags[0].label, date: null }); }}
              title="Open the government record"
              className="rounded-full focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-bright"
            >
              <Pill tone={worst === "warning" ? "warn" : "bad"}>{`⚑ ${flags.length} flag${flags.length === 1 ? "" : "s"}`}</Pill>
            </button>
            <div className="mt-1 text-[11px] text-warn">{signalLabel(flagSignal(flags[0]))}</div>
          </>
        ) : (
          <Pill tone="neutral">clear</Pill>
        )}
      </td>
    </tr>
  );
}
