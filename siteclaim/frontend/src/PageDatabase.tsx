import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import { useCite } from "./cite";
import {
  registerFor, rgba, signalLabel, signalSeverity, tradeColor, tradeLabel, type Sev,
} from "./theme";
import type { Coverage, Firm, FirmsPage, PublicFlag } from "./types";

const MONO = "'Spline Sans Mono',monospace";
const DISPLAY = "'Bricolage Grotesque',sans-serif";
const PAGE_SIZES = [10, 25, 50, 100];
const _MONTHS: Record<string, number> = { jan: 0, feb: 1, mar: 2, apr: 3, may: 4, jun: 5, jul: 6, aug: 7, sep: 8, oct: 9, nov: 10, dec: 11 };

// Display-only: a usable enquiry e-mail, or null when it is blank, has no "@", or
// is the source's "[email protected]" redaction. The stored value stays faithful.
function shownEmail(email: string): string | null {
  const e = (email || "").trim();
  if (!e || !e.includes("@") || e.toLowerCase().includes("[email")) return null;
  return e;
}

function parseRegDate(s: string): Date | null {
  const m = /(\d{1,2})\s+([A-Za-z]{3})\w*\s+(\d{4})/.exec(s || "");
  if (!m) return null;
  const mo = _MONTHS[m[2].toLowerCase()];
  return mo == null ? null : new Date(Number(m[3]), mo, Number(m[1]));
}

// Build a windowed pager: 1 … 7 [8] 9 … 55
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

export function PageDatabase({
  active,
  coverage,
  registers,
}: {
  active: boolean;
  coverage: Coverage | null;
  registers: number;
}) {
  const cite = useCite();
  const [q, setQ] = useState("");
  const [debouncedQ, setDebouncedQ] = useState("");
  const [limit, setLimit] = useState(25);
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<FirmsPage | null>(null);
  const [loading, setLoading] = useState(false);

  const total = coverage?.total_firms ?? 0;
  const flagged = coverage?.flagged_firms ?? 0;

  // debounce the search box → resets to the first page
  useEffect(() => {
    const t = setTimeout(() => { setDebouncedQ(q.trim()); setOffset(0); }, 300);
    return () => clearTimeout(t);
  }, [q]);

  // server-side fetch on page / size / search change
  const reqId = useRef(0);
  useEffect(() => {
    const id = ++reqId.current;
    setLoading(true);
    api.firms({ limit, offset, q: debouncedQ })
      .then((p) => { if (id === reqId.current) setPage(p); })
      .catch(() => { if (id === reqId.current) setPage({ items: [], total: 0, limit, offset }); })
      .finally(() => { if (id === reqId.current) setLoading(false); });
  }, [limit, offset, debouncedQ]);

  // ---- count-up over the coverage headline (replays when the page becomes active) ----
  const [counts, setCounts] = useState({ firms: 0, flagged: 0, registers: 0 });
  const raf = useRef(0);
  useEffect(() => {
    if (!active || !coverage) return;
    const dur = 1150, t0 = performance.now();
    const tick = (now: number) => {
      const p = Math.min(1, (now - t0) / dur), e = 1 - Math.pow(1 - p, 3);
      setCounts({ firms: Math.round(total * e), flagged: Math.round(flagged * e), registers: Math.round(registers * e) });
      if (p < 1) raf.current = requestAnimationFrame(tick);
    };
    raf.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf.current);
  }, [active, total, flagged, registers, coverage]);

  // ---- breathing matrix (a representative grid, proportionally flagged) ----
  const cells = useMemo(() => {
    const N = 240, flaggedN = total > 0 ? Math.max(1, Math.round((flagged / total) * N)) : 0;
    return Array.from({ length: N }, (_, i) => ({
      color: i < flaggedN ? (i < flaggedN * 0.7 ? "#E5484D" : "#D99513") : "rgba(159,180,214,0.26)",
      dur: (2.4 + (i % 5) * 0.45).toFixed(2) + "s",
      delay: ((i % 13) * 0.13).toFixed(2) + "s",
    }));
  }, [total, flagged]);

  const registerChips = useMemo(() => {
    const map = new Map<string, ReturnType<typeof registerFor>>();
    for (const s of coverage?.flag_sources ?? []) { const r = registerFor(s); map.set(r.short, r); }
    return [...map.values()];
  }, [coverage]);

  const totalPages = Math.max(1, Math.ceil((page?.total ?? 0) / limit));
  const current = Math.floor(offset / limit) + 1;
  const goPage = (p: number) => setOffset((Math.max(1, Math.min(p, totalPages)) - 1) * limit);
  const from = (page?.total ?? 0) === 0 ? 0 : offset + 1;
  const to = Math.min(offset + limit, page?.total ?? 0);

  return (
    <main style={{ maxWidth: 1260, margin: "0 auto", padding: "26px 30px 72px" }}>
      {/* HERO */}
      <section style={{ position: "relative", overflow: "hidden", borderRadius: 22, padding: "32px 36px 28px", color: "#EAF0FB", background: "radial-gradient(820px 420px at 86% -20%, rgba(110,86,207,0.55), transparent 62%), radial-gradient(680px 520px at 6% 130%, rgba(15,181,166,0.34), transparent 56%), linear-gradient(135deg,#0F1B2D 0%, #14213B 55%, #182347 100%)", boxShadow: "0 24px 60px -28px rgba(15,27,45,0.55)" }}>
        <div style={{ position: "relative", zIndex: 2, display: "flex", gap: 40, flexWrap: "wrap", alignItems: "flex-end", justifyContent: "space-between" }}>
          <div style={{ maxWidth: 560 }}>
            <div style={{ display: "inline-flex", alignItems: "center", gap: 8, fontFamily: MONO, fontSize: 11, letterSpacing: "0.16em", textTransform: "uppercase", color: "#9fb4d6", border: "1px solid rgba(159,180,214,0.28)", borderRadius: 999, padding: "5px 12px", marginBottom: 16 }}>
              <span style={{ width: 6, height: 6, borderRadius: "50%", background: "#0FB5A6" }} /> The proprietary data asset
            </div>
            <h1 style={{ margin: 0, fontFamily: DISPLAY, fontSize: 38, fontWeight: 700, lineHeight: 1.05, letterSpacing: "-0.025em", color: "#fff" }}>The Hong Kong subcontractor register, screened.</h1>
            <p style={{ margin: "14px 0 0", fontSize: 14.5, lineHeight: 1.6, color: "#b9c7de", maxWidth: 500 }}>The full CIC Registered Subcontractors register — every firm with its registered trades and enquiry contact — cross-referenced against the public enforcement record. The moat is the data and the cross-reference, not the model.</p>
          </div>
          <div style={{ flex: "none" }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 14, marginBottom: 11 }}>
              <span style={{ fontFamily: MONO, fontSize: 10.5, letterSpacing: "0.12em", textTransform: "uppercase", color: "#9fb4d6" }}>Risk overlay</span>
              <div style={{ display: "flex", gap: 12, fontFamily: MONO, fontSize: 10, color: "#9fb4d6" }}>
                <span style={{ display: "inline-flex", alignItems: "center", gap: 5 }}><span style={{ width: 8, height: 8, borderRadius: 2, background: "#E5484D" }} />flagged</span>
                <span style={{ display: "inline-flex", alignItems: "center", gap: 5 }}><span style={{ width: 8, height: 8, borderRadius: 2, background: "rgba(159,180,214,0.30)" }} />clear</span>
              </div>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(24,1fr)", gap: 3.5, width: 360 }}>
              {cells.map((c, i) => (
                <span key={i} style={{ width: "100%", aspectRatio: "1", borderRadius: 2, background: c.color, animation: `ssPulse ${c.dur} ease-in-out ${c.delay} infinite` }} />
              ))}
            </div>
          </div>
        </div>

        <div style={{ position: "relative", zIndex: 2, marginTop: 26, paddingTop: 22, borderTop: "1px solid rgba(159,180,214,0.18)" }}>
          <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 34 }}>
            <Figure value={counts.firms} label="Subcontractors screened" color="#fff" />
            <Figure value={counts.flagged} label="With an enforcement flag" color="#FF8E8E" underline />
            <Figure value={counts.registers} label="Issuing registers cross-checked" color="#fff" />
            <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 9, marginLeft: "auto" }}>
              {registerChips.map((r) => (
                <button key={r.short} type="button" onClick={() => cite.open({ source: r.name, reference: r.home, detail: `${r.name} — cross-checked against all ${total.toLocaleString("en-HK")} screened firms; adverse records matched by company name and registration number.`, date: null })} style={{ display: "inline-flex", alignItems: "center", gap: 7, cursor: "pointer", background: "rgba(255,255,255,0.04)", border: `1px solid ${rgba(r.color, 0.4)}`, borderRadius: 8, padding: "6px 11px", fontSize: 11, color: "#dbe5f4" }}>
                  <span style={{ width: 7, height: 7, borderRadius: "50%", background: r.color }} />{r.short}
                </button>
              ))}
            </div>
          </div>
          {/* self-explaining composition — answers "the CSV only has 1,366" before it's asked */}
          {coverage && (
            <p style={{ margin: "14px 0 0", fontSize: 12.5, lineHeight: 1.55, color: "#9fb4d6" }}>
              <span style={{ color: "#cdd9ec", fontWeight: 600 }}>{coverage.register_count.toLocaleString("en-HK")}</span> on the CIC subcontractor register
              <span style={{ opacity: 0.5 }}> · </span>
              <span style={{ color: "#cdd9ec", fontWeight: 600 }}>{coverage.overlay_count.toLocaleString("en-HK")}</span> from enforcement &amp; offer records
              <span style={{ opacity: 0.5 }}> · </span>
              <span style={{ color: "#FFB3B3", fontWeight: 600 }}>{coverage.flagged_count}</span> flagged
            </p>
          )}
        </div>
      </section>

      {/* CONTROLS */}
      <section style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 12, margin: "22px 0 14px" }}>
        <div style={{ flex: 1, minWidth: 280, display: "flex", alignItems: "center", gap: 10, background: "#fff", border: "1px solid rgba(15,27,45,0.10)", borderRadius: 12, padding: "0 14px", height: 46, boxShadow: "0 6px 18px -14px rgba(15,27,45,0.4)" }}>
          <span style={{ color: "#1F6FEB", fontSize: 16 }}>⌕</span>
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search the register by company name…" style={{ flex: 1, border: "none", outline: "none", background: "transparent", fontSize: 14, color: "#0F1B2D", height: "100%" }} />
          {loading && <span style={{ width: 8, height: 8, borderRadius: "50%", background: "#1F6FEB", animation: "ssLive 1.2s ease-in-out infinite" }} />}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontFamily: MONO, fontSize: 11, color: "#8a98ab", letterSpacing: "0.04em" }}>Rows</span>
          <div style={{ display: "inline-flex", background: "#fff", border: "1px solid rgba(15,27,45,0.12)", borderRadius: 10, overflow: "hidden" }}>
            {PAGE_SIZES.map((n) => (
              <button key={n} type="button" onClick={() => { setLimit(n); setOffset(0); }} style={{ border: "none", borderLeft: n === PAGE_SIZES[0] ? "none" : "1px solid rgba(15,27,45,0.08)", background: limit === n ? "#0F1B2D" : "#fff", color: limit === n ? "#fff" : "#46566b", fontSize: 12.5, fontWeight: 600, padding: "9px 13px", cursor: "pointer" }}>{n}</button>
            ))}
          </div>
        </div>
        <div style={{ fontFamily: MONO, fontSize: 12.5, color: "#46566b", whiteSpace: "nowrap" }}>
          <span style={{ fontWeight: 700, color: "#0F1B2D" }}>{total.toLocaleString("en-HK")}</span> registered subcontractors
          <span style={{ color: "#8a98ab" }}> · </span>
          <span style={{ fontWeight: 700, color: "#E5484D" }}>{flagged}</span> with enforcement flags
        </div>
      </section>

      {/* TABLE */}
      <section style={{ background: "#fff", border: "1px solid rgba(15,27,45,0.08)", borderRadius: 16, overflow: "hidden", boxShadow: "0 12px 34px -26px rgba(15,27,45,0.45)" }}>
        <div className="ssx" style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", minWidth: 880, borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ borderBottom: "1px solid #eef1f6", background: "#f8fafc" }}>
                {["Company", "Registered trades", "Registration", "Enforcement"].map((h, i) => (
                  <th key={h} style={{ textAlign: i > 1 ? "left" : "left", fontFamily: MONO, fontSize: 10.5, fontWeight: 600, letterSpacing: "0.08em", textTransform: "uppercase", color: "#8a98ab", padding: "12px 18px" }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {(page?.items ?? []).map((f) => <FirmRow key={f.firm_id} firm={f} onCite={cite.open} />)}
              {!loading && (page?.items.length ?? 0) === 0 && (
                <tr><td colSpan={4} style={{ padding: "40px 18px", textAlign: "center", color: "#8a98ab", fontSize: 13.5 }}>No registered subcontractor matches “{debouncedQ}”.</td></tr>
              )}
            </tbody>
          </table>
        </div>

        {/* PAGER */}
        <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", justifyContent: "space-between", gap: 12, padding: "13px 18px", borderTop: "1px solid #eef1f6" }}>
          <span style={{ fontFamily: MONO, fontSize: 12, color: "#8a98ab" }}>{from.toLocaleString("en-HK")}–{to.toLocaleString("en-HK")} of {(page?.total ?? 0).toLocaleString("en-HK")}</span>
          <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
            <PagerBtn label="« First" disabled={current <= 1} onClick={() => goPage(1)} />
            <PagerBtn label="‹ Prev" disabled={current <= 1} onClick={() => goPage(current - 1)} />
            {pageWindow(current, totalPages).map((p, i) => p === "…"
              ? <span key={`e${i}`} style={{ padding: "0 6px", color: "#8a98ab" }}>…</span>
              : <button key={p} type="button" onClick={() => goPage(p)} style={{ minWidth: 34, height: 34, border: `1px solid ${p === current ? "#1F6FEB" : "rgba(15,27,45,0.12)"}`, background: p === current ? "#1F6FEB" : "#fff", color: p === current ? "#fff" : "#46566b", borderRadius: 9, fontFamily: MONO, fontSize: 13, fontWeight: 600, cursor: "pointer" }}>{p}</button>)}
            <PagerBtn label="Next ›" disabled={current >= totalPages} onClick={() => goPage(current + 1)} />
            <PagerBtn label="Last »" disabled={current >= totalPages} onClick={() => goPage(totalPages)} />
          </div>
        </div>
      </section>
    </main>
  );
}

function PagerBtn({ label, disabled, onClick }: { label: string; disabled: boolean; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} disabled={disabled} style={{ height: 34, padding: "0 11px", border: "1px solid rgba(15,27,45,0.12)", background: "#fff", color: disabled ? "#c4cfdc" : "#46566b", borderRadius: 9, fontSize: 12.5, fontWeight: 600, cursor: disabled ? "not-allowed" : "pointer" }}>{label}</button>
  );
}

function Figure({ value, label, color, underline }: { value: number; label: string; color: string; underline?: boolean }) {
  return (
    <div>
      <div style={{ position: "relative", display: "inline-block" }}>
        <span style={{ fontFamily: DISPLAY, fontVariantNumeric: "tabular-nums", fontSize: 46, fontWeight: 700, lineHeight: 0.9, color }}>{value.toLocaleString("en-HK")}</span>
        {underline && <span style={{ position: "absolute", left: 0, right: 0, bottom: -3, height: 3, borderRadius: 2, background: "linear-gradient(90deg,#E5484D,#D99513)" }} />}
      </div>
      <div style={{ fontSize: 11.5, letterSpacing: "0.05em", textTransform: "uppercase", color: "#9fb4d6", marginTop: 8 }}>{label}</div>
    </div>
  );
}

function FirmRow({ firm, onCite }: { firm: Firm; onCite: (c: { source: string | null; reference: string | null; detail: string; date?: string | null }) => void }) {
  const sevOf = (fl: PublicFlag): Sev => signalSeverity(fl.signal_type);
  const worst: Sev | null = firm.public_flags.some((f) => sevOf(f) === "fatal") ? "fatal"
    : firm.public_flags.some((f) => sevOf(f) === "warning") ? "warning"
    : firm.public_flags.length ? "info" : null;
  const flagged = firm.public_flags.length > 0;
  const accent = worst === "fatal" ? "#E5484D" : worst === "warning" ? "#D99513" : worst ? "#8a98ab" : "#2EA56A";
  const trades = firm.trades.slice(0, 3);
  const moreTrades = firm.trades.length - trades.length;

  const expiry = parseRegDate(firm.expiry_date);
  const valid = expiry ? expiry.getTime() >= Date.now() : null;

  return (
    <tr style={{ borderBottom: "1px solid #f1f4f8", background: flagged ? rgba("#E5484D", 0.025) : "transparent" }}>
      <td style={{ padding: "13px 18px", verticalAlign: "top", borderLeft: `3px solid ${accent}` }}>
        <div style={{ display: "flex", alignItems: "center", gap: 9, flexWrap: "wrap" }}>
          <span style={{ fontFamily: DISPLAY, fontSize: 14.5, fontWeight: 600, color: "#0F1B2D" }}>{firm.name_en}</span>
          {firm.name_zh && <span style={{ fontSize: 12, color: "#8a98ab" }}>{firm.name_zh}</span>}
        </div>
        <div style={{ fontSize: 12, color: "#5a6b80", marginTop: 3, lineHeight: 1.45, maxWidth: 440 }}>{firm.description}</div>
        {(() => {
          const email = shownEmail(firm.enquiry_email);
          return email
            ? <a href={`mailto:${email}`} style={{ display: "inline-flex", alignItems: "center", gap: 5, marginTop: 5, fontFamily: MONO, fontSize: 11, color: "#1F6FEB", textDecoration: "none" }}>✉ {email}</a>
            : <span style={{ display: "inline-flex", alignItems: "center", gap: 5, marginTop: 5, fontFamily: MONO, fontSize: 11, color: "#a8b3c2", fontStyle: "italic" }}>✉ email not listed</span>;
        })()}
      </td>
      <td style={{ padding: "13px 18px", verticalAlign: "top" }}>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 5, maxWidth: 280 }}>
          {trades.map((t) => {
            const col = tradeColor(t);
            return <span key={t} style={{ display: "inline-flex", alignItems: "center", gap: 5, fontSize: 11, fontWeight: 500, color: col, background: rgba(col, 0.1), borderRadius: 6, padding: "2px 8px" }}><span style={{ width: 5, height: 5, borderRadius: "50%", background: col }} />{tradeLabel(t)}</span>;
          })}
          {moreTrades > 0 && <span style={{ fontSize: 11, color: "#8a98ab", padding: "2px 4px" }}>+{moreTrades}</span>}
        </div>
      </td>
      <td style={{ padding: "13px 18px", verticalAlign: "top", whiteSpace: "nowrap" }}>
        {valid == null ? (
          <span style={{ fontSize: 12, color: "#8a98ab" }}>—</span>
        ) : (
          <span style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 12, fontWeight: 600, color: valid ? "#1a8a56" : "#E5484D", background: valid ? rgba("#2EA56A", 0.1) : rgba("#E5484D", 0.1), borderRadius: 999, padding: "3px 10px" }}>
            <span style={{ width: 6, height: 6, borderRadius: "50%", background: valid ? "#2EA56A" : "#E5484D" }} />{valid ? "Valid" : "Expired"}
          </span>
        )}
        {firm.expiry_date && <div style={{ fontFamily: MONO, fontSize: 10.5, color: "#8a98ab", marginTop: 4 }}>to {firm.expiry_date}</div>}
      </td>
      <td style={{ padding: "13px 18px", verticalAlign: "top" }}>
        {flagged ? (
          <button type="button" onClick={() => { const fl = firm.public_flags[0]; onCite({ source: fl.source, reference: fl.reference, detail: fl.label, date: fl.date }); }} style={{ display: "inline-flex", alignItems: "center", gap: 6, cursor: "pointer", border: `1px solid ${rgba("#E5484D", 0.4)}`, background: rgba("#E5484D", 0.08), color: "#E5484D", borderRadius: 999, padding: "4px 11px", fontSize: 11.5, fontWeight: 700 }}>
            ⚑ {firm.public_flags.length} flag{firm.public_flags.length === 1 ? "" : "s"}
          </button>
        ) : (
          <span style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 11.5, fontWeight: 500, color: "#1a8a56", background: rgba("#2EA56A", 0.08), borderRadius: 999, padding: "4px 11px" }}>
            <span style={{ width: 6, height: 6, borderRadius: "50%", background: "#2EA56A" }} />Clear
          </span>
        )}
        {flagged && (
          <div style={{ marginTop: 5, fontSize: 11, color: "#9a6a08" }}>{signalLabel(firm.public_flags[0].signal_type)}</div>
        )}
      </td>
    </tr>
  );
}
