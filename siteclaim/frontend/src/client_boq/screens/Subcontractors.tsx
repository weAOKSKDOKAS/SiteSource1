// Subcontractors — the firm register browser. Ported from DatabasePage, restyled onto the
// tender-desk palette; behaviour, wording and every decision it encodes are unchanged.
//
// This screen is the product's evidence cabinet, so three rules are load-bearing rather than
// cosmetic and are preserved literally:
//
//  * SITESOURCE ASSERTS NOTHING WITHOUT A RECORD. Every enforcement flag opens the issuing
//    government body's record — its proper name, its reference/docket, and a link to verify at
//    source. A flag with no citation behind it would make this a chatbot's opinion about a company.
//  * AN ABSENT ASSESSMENT IS NOT A ZERO. A registration date that cannot be parsed renders as
//    "—", never as "Expired"; a firm with no flags renders "clear", never a score.
//  * THE FIGURES COUNT THE REAL-PROVENANCE POPULATION ONLY. The composition line states what the
//    headline number is made of — register firms plus the enforcement overlay — instead of letting
//    one round number stand in for two different things.
//
// The citation mechanism (CiteProvider / useCite) is ported INLINE rather than imported: the
// original `src/cite.tsx` pulls `Docket`, `Drawer` and `MonoLabel` out of the procurement UI and
// its issuing-body map out of `src/theme.ts`, and client_boq does not import procurement files.
// Only the presentation moved — the context shape, the drawer's content and its footer sentence
// are the source's.

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { api } from "../api";
import { FirmRecord, shownEmail } from "../firm";
import type { Coverage, FirmProfile, FirmsPage, RiskFlag } from "../types";
import { Chip, Docket, Drawer, ErrorNote, Pill, SectionLabel, Spinner, cx } from "../ui";

const PAGE_SIZES = [10, 25, 50, 100];
const MONTHS: Record<string, number> = { jan: 0, feb: 1, mar: 2, apr: 3, may: 4, jun: 5, jul: 6, aug: 7, sep: 8, oct: 9, nov: 10, dec: 11 };

function tradeLabel(trade: string): string {
  const [base, section] = trade.split(":");
  const label = base.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  return section ? `${label} · Section ${section}` : label;
}

// ---------------------------------------------------------------------------
// The issuing registers, and how a stored flag is read back
// ---------------------------------------------------------------------------
// Ported from `src/theme.ts` (the map, not the badge colours — see the note in `RegisterChips`).
// Nothing here is new backend data: a public flag is stored as a RiskFlag whose issuing source,
// signal type and reference live on its first piece of evidence, and these read them back.

interface Register {
  short: string;
  name: string;
  home: string;
}

const REGISTER_LIST: { match: RegExp; reg: Register }[] = [
  { match: /buildings/, reg: { short: "BD", name: "Buildings Department", home: "https://www.bd.gov.hk/" } },
  { match: /development bureau|devb/, reg: { short: "DEVB", name: "Development Bureau", home: "https://www.devb.gov.hk/" } },
  { match: /labour/, reg: { short: "LD", name: "Labour Department", home: "https://www.labour.gov.hk/" } },
  { match: /companies registry/, reg: { short: "CR", name: "Companies Registry", home: "https://www.cr.gov.hk/" } },
  { match: /environmental|epd/, reg: { short: "EPD", name: "Environmental Protection Department", home: "https://www.epd.gov.hk/" } },
  { match: /housing/, reg: { short: "HA", name: "Housing Authority", home: "https://www.housingauthority.gov.hk/" } },
  { match: /emsd|electrical and mechanical/, reg: { short: "EMSD", name: "EMSD Registration", home: "https://www.emsd.gov.hk/" } },
  { match: /fire services/, reg: { short: "FSD", name: "Fire Services Department", home: "https://www.hkfsd.gov.hk/" } },
  { match: /adjudicat/, reg: { short: "ADJ", name: "Adjudicator's determination", home: "https://www.devb.gov.hk/" } },
];

function registerFor(source: string | null | undefined): Register {
  const s = (source || "").toLowerCase();
  for (const { match, reg } of REGISTER_LIST) if (match.test(s)) return reg;
  const short = (source || "Public record").split(/\s+/).map((w) => w[0]).join("").slice(0, 4).toUpperCase() || "REC";
  return { short, name: source || "Public record", home: "https://www.gov.hk/en/residents/" };
}

type Sev = "fatal" | "warning" | "info";

const FATAL_SIGNALS = new Set(["winding_up", "debarment", "adjudication"]);
function signalSeverity(signalType: string): Sev {
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
  closeout_performance: "Delayed closeout",
};
function signalLabel(signalType: string): string {
  return SIGNAL_LABELS[signalType] ?? signalType.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function flagSignal(f: RiskFlag): string {
  return f.evidence[0]?.signal_type ?? "info";
}
function flagSource(f: RiskFlag): string | null {
  return f.evidence[0]?.source || null;
}
function flagReference(f: RiskFlag): string | null {
  return f.evidence[0]?.reference || null;
}

/** The worst signal weight across a firm's public flags (null = clean). */
function worstFlagSeverity(flags: RiskFlag[]): Sev | null {
  if (flags.some((f) => signalSeverity(flagSignal(f)) === "fatal")) return "fatal";
  if (flags.some((f) => signalSeverity(flagSignal(f)) === "warning")) return "warning";
  return flags.length ? "info" : null;
}

// ---------------------------------------------------------------------------
// The citable public record
// ---------------------------------------------------------------------------
/** Any source chip or flag reference on this screen opens the shared government-record drawer
 *  through this context. The drawer asserts nothing that is not already a cited public record —
 *  it IS that record. */
interface Citation {
  source: string | null;
  reference: string | null;
  detail: string;
  date?: string | null;
}

interface CiteCtx {
  open: (c: Citation) => void;
  close: () => void;
}
const Ctx = createContext<CiteCtx>({ open: () => {}, close: () => {} });
const useCite = () => useContext(Ctx);

function CiteProvider({ children }: { children: ReactNode }) {
  const [cite, setCite] = useState<Citation | null>(null);
  const open = useCallback((c: Citation) => setCite(c), []);
  const close = useCallback(() => setCite(null), []);
  return (
    <Ctx.Provider value={{ open, close }}>
      {children}
      <EvidenceDrawer cite={cite} onClose={close} />
    </Ctx.Provider>
  );
}

function EvidenceDrawer({ cite, onClose }: { cite: Citation | null; onClose: () => void }) {
  const reg = registerFor(cite?.source);
  const isUrl = !!cite?.reference && /^https?:\/\//.test(cite.reference);
  const verifyUrl = isUrl ? (cite as Citation).reference! : reg.home;
  const docket = cite?.reference || "On the public register";
  return (
    <Drawer
      open={cite != null}
      onClose={onClose}
      eyebrow="Government record"
      // Navy: a government record is a fact on a public register. Nothing in this drawer was
      // written or proposed by a model, so it must not carry the brass accent.
      accent="bg-cb-navy"
      title={reg.name}
      subtitle={<span className="font-cb-mono">{reg.short}</span>}
      footer="SiteSource asserts nothing without a citable public record. This drawer is that record."
    >
      {cite && (
        <div className="space-y-3">
          <Docket label="Reference / docket" code={<span className="break-all">{docket}</span>} />
          <div>
            <SectionLabel className="mb-1">Record summary</SectionLabel>
            <p className="text-[11px] leading-relaxed text-cb-body">{cite.detail}</p>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div className="rounded-cb-card border border-cb-border bg-cb-panel px-3 py-2.5">
              <SectionLabel>Issuing body</SectionLabel>
              <div className="mt-0.5 font-cb-mono text-[12px] font-semibold text-cb-ink-text">{reg.short}</div>
            </div>
            <div className="rounded-cb-card border border-cb-border bg-cb-panel px-3 py-2.5">
              <SectionLabel>Last checked</SectionLabel>
              <div className="mt-0.5 font-cb-mono text-[12px] font-semibold text-cb-ink-text">{cite.date || "live"}</div>
            </div>
          </div>
          <a
            href={verifyUrl}
            target="_blank"
            rel="noreferrer noopener"
            className="cb-press flex items-center justify-center gap-2 rounded-cb-btn bg-cb-ink px-3 py-2.5 font-cb-sans text-[11px] font-semibold text-white"
          >
            Verify at source ↗
          </a>
        </div>
      )}
    </Drawer>
  );
}

// ---------------------------------------------------------------------------
// Small helpers, ported verbatim
// ---------------------------------------------------------------------------
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

// ---------------------------------------------------------------------------
// The screen
// ---------------------------------------------------------------------------
/** The proprietary database (Layer 3) — the browse over the full CIC register. Coverage is stated
 *  as an honest composition; the browse and every figure count the real-provenance population only
 *  (illustrative demo firms never appear). Wrapped in the CiteProvider so a register chip or a flag
 *  reference opens the shared government-record panel. */
export function Subcontractors({ onError }: { onError: (message: string) => void }) {
  return (
    <CiteProvider>
      <SubcontractorsView onError={onError} />
    </CiteProvider>
  );
}

function SubcontractorsView({ onError }: { onError: (message: string) => void }) {
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
    api.manage
      .coverage()
      .then(setCov)
      .catch((e: unknown) => {
        const message = e instanceof Error ? e.message : String(e);
        setError(message);
        onError(message);
      });
    // The source mounts this once; onError is the shell's stable callback and is deliberately
    // not a dependency — re-fetching coverage because a parent re-rendered would be new behaviour.
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
    api.manage.firms({ limit, offset, q: debouncedQ || undefined })
      // A failed search shows the empty-result sentence rather than an error banner — the source's
      // choice, kept: the row that matters is "nothing matches", not the transport.
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

  // The breathing risk matrix — a representative 240-cell grid, proportionally flagged. The
  // source's three hexes become three meanings: an adverse record (bad), a warning-weight signal
  // (amber), and a firm with nothing against it (track — a neutral count, not a judgement).
  const cells = useMemo(() => {
    const N = 240, flaggedN = total > 0 ? Math.max(1, Math.round((flagged / total) * N)) : 0;
    return Array.from({ length: N }, (_, i) => ({
      cls: i < flaggedN ? (i < flaggedN * 0.7 ? "bg-cb-bad" : "bg-cb-amber") : "bg-cb-track",
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
    <div className="min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto min-w-0 max-w-[1080px] space-y-4 p-[18px]">
        {error && <ErrorNote message={error} onDismiss={() => setError(null)} />}

        {/* THE DATA ASSET — headline figures, the risk overlay, and the honest composition. */}
        <section className="rounded-cb-card border border-cb-border bg-cb-surface px-6 py-5 shadow-cb-card">
          <div className="flex flex-wrap items-end justify-between gap-8">
            <div className="max-w-xl">
              <SectionLabel>The proprietary data asset</SectionLabel>
              <h1 className="mt-2 font-cb-serif text-[22px] font-semibold leading-[1.15] text-cb-ink-text">
                The Hong Kong subcontractor register, screened.
              </h1>
              <p className="mt-2 max-w-lg font-cb-sans text-[11.5px] leading-[1.6] text-cb-muted">
                The full CIC Registered Subcontractors register — every firm with its registered trades and enquiry
                contact — cross-referenced against the public enforcement record. The moat is the data and the
                cross-reference, not a generic chatbot.
              </p>
            </div>

            {/* RISK OVERLAY breathing matrix */}
            <div className="flex-none">
              <div className="mb-2 flex items-center justify-between gap-3.5">
                <SectionLabel>Risk overlay</SectionLabel>
                <div className="flex gap-3 font-cb-mono text-[10px] text-cb-faint">
                  <span className="inline-flex items-center gap-1.5"><span className="h-2 w-2 rounded-cb-mark bg-cb-bad" />flagged</span>
                  <span className="inline-flex items-center gap-1.5"><span className="h-2 w-2 rounded-cb-mark bg-cb-track" />clear</span>
                </div>
              </div>
              <div className="grid w-[300px] gap-[3.5px] sm:w-[360px]" style={{ gridTemplateColumns: "repeat(24,1fr)" }}>
                {cells.map((c, i) => (
                  <span
                    key={i}
                    className={cx("w-full animate-pulse rounded-cb-mark", c.cls)}
                    style={{ aspectRatio: "1", animationDuration: c.dur, animationDelay: c.delay }}
                  />
                ))}
              </div>
            </div>
          </div>

          {/* Headline figures (count-up), register chips, and the honest composition line. */}
          <div className="mt-5 border-t border-cb-divider pt-4">
            <div className="flex flex-wrap items-center gap-x-8 gap-y-4">
              <Figure value={counts.firms} label="Subcontractors screened" />
              <Figure value={counts.flagged} label="With an enforcement flag" tone="danger" />
              <Figure value={counts.registers} label="Issuing registers cross-checked" />
              <div className="flex flex-wrap items-center gap-2 sm:ml-auto">
                {registerChips.map((r) => (
                  // Navy: an issuing register is a deterministic fact about where a flag came from.
                  // The source badges each body in its own identity hex; those are not tokens in
                  // this palette (and one of them is the same red this system reserves for a
                  // failure), so the chips carry the register's short name instead of its colour.
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
                    className="cb-press inline-flex cursor-pointer items-center gap-1.5 rounded-cb-chip border border-cb-border bg-cb-info-fill px-2.5 py-1.5 font-cb-mono text-[10px] font-semibold text-cb-navy hover:bg-cb-info"
                  >
                    {r.short}
                  </button>
                ))}
              </div>
            </div>
            {cov && (
              <p className="mt-3 font-cb-sans text-[11px] leading-relaxed text-cb-muted">
                <span className="font-cb-mono font-semibold text-cb-ink-text">{cov.register_count.toLocaleString("en-HK")}</span> on the CIC subcontractor register
                <span className="text-cb-faint"> · </span>
                <span className="font-cb-mono font-semibold text-cb-ink-text">{cov.overlay_count.toLocaleString("en-HK")}</span> from enforcement &amp; offer records
                <span className="text-cb-faint"> · </span>
                <span className="font-cb-mono font-semibold text-cb-bad-dark">{cov.flagged_count}</span> flagged
              </p>
            )}
          </div>
        </section>

        {/* CONTROLS */}
        <div className="flex flex-wrap items-center gap-3">
          <div className="relative flex h-9 min-w-64 flex-1 items-center gap-2.5 rounded-cb-btn border border-cb-border-strong bg-cb-page px-3">
            <span className="text-cb-faint" aria-hidden>⌕</span>
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search the register by company name…"
              className="h-full flex-1 border-none bg-transparent font-cb-sans text-[12px] text-cb-ink-text outline-none placeholder:text-cb-faint"
            />
            {loading && (
              <span className="flex-none text-cb-faint" title="Searching the register…" aria-hidden>
                <Spinner />
              </span>
            )}
          </div>
          <div className="flex items-center gap-2">
            <span className="font-cb-mono text-[10px] text-cb-faint">Rows</span>
            <div className="inline-flex overflow-hidden rounded-cb-btn border border-cb-border-strong">
              {PAGE_SIZES.map((n) => (
                <button
                  key={n}
                  type="button"
                  onClick={() => { setLimit(n); setOffset(0); }}
                  className={cx(
                    "cb-press border-l border-cb-border-strong px-2.5 py-1.5 font-cb-mono text-[10px] font-semibold first:border-l-0",
                    // A selected row-size is an interface state, not a judgement — ink, the
                    // system's neutral "chosen" fill, never brass (which would claim authorship).
                    limit === n ? "bg-cb-ink text-white" : "bg-white text-cb-muted hover:bg-cb-panel",
                  )}
                >
                  {n}
                </button>
              ))}
            </div>
          </div>
          <div className="whitespace-nowrap font-cb-sans text-[11px] text-cb-muted">
            <span className="font-cb-mono font-bold text-cb-ink-text">{total.toLocaleString("en-HK")}</span> registered subcontractors
            <span className="text-cb-faint"> · </span>
            <span className="font-cb-mono font-bold text-cb-bad-dark">{flagged}</span> with enforcement flags
          </div>
        </div>

        {/* TABLE */}
        <div className="overflow-hidden rounded-cb-card border border-cb-border bg-cb-page">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[880px] border-collapse text-left">
              <thead>
                <tr className="border-b border-cb-border bg-cb-panel">
                  {["Company", "Registered trades", "Registration", "Enforcement"].map((h) => (
                    <th key={h} className="px-3 py-2 font-cb-mono text-[10px] font-semibold uppercase tracking-cb-label text-cb-faint">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {page?.items.map((f) => <FirmRow key={f.firm_id} firm={f} onOpen={() => setDetail(f)} onCite={cite.open} />)}
                {!loading && (page?.items.length ?? 0) === 0 && (
                  <tr><td colSpan={4} className="px-4 py-10 text-center font-cb-sans text-[11px] text-cb-faint">No registered subcontractor matches “{debouncedQ}”.</td></tr>
                )}
              </tbody>
            </table>
          </div>

          {/* PAGER */}
          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-cb-divider px-3 py-2.5">
            <span className="font-cb-mono text-[10px] text-cb-faint">
              {from.toLocaleString("en-HK")}–{to.toLocaleString("en-HK")} of {(page?.total ?? 0).toLocaleString("en-HK")}
            </span>
            <div className="flex items-center gap-1.5">
              <PagerBtn label="« First" disabled={current <= 1} onClick={() => goPage(1)} />
              <PagerBtn label="‹ Prev" disabled={current <= 1} onClick={() => goPage(current - 1)} />
              {pageWindow(current, totalPages).map((p, i) => p === "…"
                ? <span key={`e${i}`} className="px-1.5 font-cb-mono text-[10px] text-cb-faint">…</span>
                : (
                  <button
                    key={p}
                    type="button"
                    onClick={() => goPage(p)}
                    className={cx(
                      "cb-press h-7 min-w-7 rounded-cb-btn border px-2 font-cb-mono text-[11px] font-semibold",
                      p === current
                        ? "border-cb-ink bg-cb-ink text-white"
                        : "border-cb-border-strong bg-white text-cb-muted hover:bg-cb-panel",
                    )}
                  >
                    {p}
                  </button>
                ))}
              <PagerBtn label="Next ›" disabled={current >= totalPages} onClick={() => goPage(current + 1)} />
              <PagerBtn label="Last »" disabled={current >= totalPages} onClick={() => goPage(totalPages)} />
            </div>
          </div>
        </div>

        <p className="font-cb-sans text-[10px] leading-[1.55] text-cb-faint">
          The browse and every figure count the real-provenance population only — the CIC register plus the
          enforcement overlay. Illustrative demo firms are present-but-excluded here and absent in the live profile;
          every flag carries its issuing source and reference.
        </p>

        <Drawer
          open={detail != null}
          onClose={() => setDetail(null)}
          eyebrow="Firm record"
          // Red when the record itself disqualifies the firm; navy otherwise, because everything in
          // this drawer is register data and a deterministic screen — no model wrote any of it.
          accent={detail && worstFlagSeverity(detail.public_flags) === "fatal" ? "bg-cb-bad" : "bg-cb-navy"}
          title={detail?.name ?? ""}
          subtitle={detail && (
            <span className="flex flex-wrap items-center gap-2">
              <span className="font-cb-mono">{detail.firm_id}</span>
              {detail.name_zh && <span className="text-cb-faint">{detail.name_zh}</span>}
            </span>
          )}
          footer="Real-provenance register firm — every enforcement flag carries its issuing government source and reference."
        >
          {detail && <FirmRecord firm={detail} />}
        </Drawer>
      </div>
    </div>
  );
}

/** One headline figure. `danger` is the enforcement count — an adverse fact about the population,
 *  so it takes the failure colour; the other two are plain counts and stay neutral ink. */
function Figure({ value, label, tone }: { value: number; label: string; tone?: "danger" }) {
  return (
    <div>
      <div className="relative inline-block">
        <span
          className={cx(
            "font-cb-mono text-[28px] font-bold leading-[0.9]",
            tone === "danger" ? "text-cb-bad-dark" : "text-cb-ink-text",
          )}
        >
          {value.toLocaleString("en-HK")}
        </span>
        {tone === "danger" && (
          <span className="absolute inset-x-0 -bottom-0.5 h-[3px] rounded-cb-mark bg-linear-to-r from-cb-bad to-cb-amber" />
        )}
      </div>
      <div className="mt-1.5 font-cb-sans text-[10px] uppercase tracking-cb-chip text-cb-faint">{label}</div>
    </div>
  );
}

function PagerBtn({ label, disabled, onClick }: { label: string; disabled: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="cb-press h-7 rounded-cb-btn border border-cb-border-strong bg-white px-2 font-cb-sans text-[10px] font-semibold text-cb-muted enabled:hover:bg-cb-panel disabled:text-cb-disabled"
    >
      {label}
    </button>
  );
}

function FirmRow({ firm, onOpen, onCite }: { firm: FirmProfile; onOpen: () => void; onCite: (c: Citation) => void }) {
  const flags = firm.public_flags;
  const worst = worstFlagSeverity(flags);
  const flagged = flags.length > 0;
  // The left rail states the firm's screen result: a fatal record is a disqualification (bad), a
  // warning-weight one is a degradation (amber), an info-only flag is a record with no judgement
  // attached (faint), and no flags at all is a clean pass (ok).
  const accent =
    worst === "fatal" ? "border-l-cb-bad"
      : worst === "warning" ? "border-l-cb-amber"
        : worst ? "border-l-cb-faint" : "border-l-cb-ok";
  const trades = firm.trades.slice(0, 3);
  const moreTrades = firm.trades.length - trades.length;
  const email = shownEmail(firm.enquiry_email);
  const expiry = parseRegDate(firm.expiry_date);
  // null, not false: a date we could not read is NOT an expired registration, and the cell below
  // renders "—" for it. Letting an unparsed date look like a finding is the failure this guards.
  const valid = expiry ? expiry.getTime() >= Date.now() : null;

  return (
    <tr
      onClick={onOpen}
      title="Open the firm record"
      className={cx(
        // Hover is on EVERY row, flagged or not — the source's structure. A flagged row is still
        // a clickable row, and withholding the affordance from it would be a behaviour change.
        "cursor-pointer border-b border-cb-divider transition-colors last:border-0 hover:bg-cb-panel/60",
        flagged && "bg-cb-bad-tint/40",
      )}
    >
      <td className={cx("border-l-[3px] px-3 py-2.5 align-top", accent)}>
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-cb-sans text-[12px] font-semibold text-cb-ink-text">{firm.name}</span>
          {firm.name_zh && <span className="text-[10px] text-cb-faint">{firm.name_zh}</span>}
        </div>
        {firm.description && <div className="mt-0.5 max-w-md text-[10.5px] leading-snug text-cb-muted">{firm.description}</div>}
        {email ? (
          // The enquiry contact is a fact off the register, so navy rather than brass — nothing
          // proposed it. The absence is said in words, never left blank.
          <span className="mt-1 inline-flex items-center gap-1.5 font-cb-mono text-[10px] text-cb-navy">✉ {email}</span>
        ) : (
          <span className="mt-1 inline-flex items-center gap-1.5 font-cb-mono text-[10px] italic text-cb-faint">✉ email not listed</span>
        )}
      </td>
      <td className="px-3 py-2.5 align-top">
        <span className="flex max-w-[280px] flex-wrap gap-1.5">
          {/* A registered trade is a register fact — navy, the same chip the firm record uses. */}
          {trades.map((t) => <Chip key={t} className="bg-cb-info-fill text-cb-navy">{tradeLabel(t)}</Chip>)}
          {moreTrades > 0 && <span className="font-cb-mono text-[10px] text-cb-faint">+{moreTrades}</span>}
        </span>
      </td>
      <td className="whitespace-nowrap px-3 py-2.5 align-top">
        {firm.registered_grade && <div className="text-[10.5px] text-cb-body">{firm.registered_grade}</div>}
        {valid == null ? (
          <span className="text-[10.5px] text-cb-faint">—</span>
        ) : (
          <span className={cx(
            "inline-flex items-center gap-1.5 rounded-cb-pill px-2 py-0.5 font-cb-sans text-[10px] font-semibold",
            valid ? "bg-cb-ok-tint text-cb-ok-dark" : "bg-cb-bad-tint text-cb-bad-dark",
          )}>
            <span className={cx("h-1.5 w-1.5 rounded-full", valid ? "bg-cb-ok" : "bg-cb-bad")} />{valid ? "Valid" : "Expired"}
          </span>
        )}
        {firm.expiry_date && <div className="mt-1 font-cb-mono text-[10px] text-cb-faint">to {firm.expiry_date}</div>}
        {firm.br_no && <div className="mt-0.5 font-cb-mono text-[10px] text-cb-faint">BR {firm.br_no}</div>}
      </td>
      <td className="px-3 py-2.5 align-top">
        {flagged ? (
          <>
            <button
              type="button"
              onClick={(e) => { e.stopPropagation(); onCite({ source: flagSource(flags[0]), reference: flagReference(flags[0]), detail: flags[0].label, date: null }); }}
              title="Open the government record"
              className="cb-press rounded-cb-pill"
            >
              {/* Warning takes border+text: this palette has no amber fill, and inventing one
                  would put an unowned colour in the system. Info-weight flags fall through to the
                  failure pill exactly as the source has them — kept, not corrected. */}
              <Pill className={worst === "warning" ? "border border-cb-brass-line text-cb-amber" : "bg-cb-bad-tint text-cb-bad-dark"}>
                {`⚑ ${flags.length} flag${flags.length === 1 ? "" : "s"}`}
              </Pill>
            </button>
            <div className="mt-1 font-cb-sans text-[10px] text-cb-amber">{signalLabel(flagSignal(flags[0]))}</div>
          </>
        ) : (
          // "clear" is the absence of a record, not a pass this product awarded — neutral panel.
          <Pill className="bg-cb-panel text-cb-muted">clear</Pill>
        )}
      </td>
    </tr>
  );
}
