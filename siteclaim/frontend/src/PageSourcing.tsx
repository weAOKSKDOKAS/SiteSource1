import { useEffect, useState } from "react";
import { api } from "./api";
import { useCite } from "./cite";
import { hkd, registerFor, rgba, tradeColor, tradeLabel } from "./theme";
import type {
  BidReply, Coverage, DemoCaseSummary, DispatchSet, LevelledBid, Recommendation, ScopePackages, ShortlistSet, TenderPackage,
} from "./types";

const MONO = "'Spline Sans Mono',monospace";
const DISPLAY = "'Bricolage Grotesque',sans-serif";
const INK = "#0F1B2D", SOFT = "#46566b", FAINT = "#8a98ab", BLUE = "#1F6FEB";
const cardSx: React.CSSProperties = { background: "#fff", border: "1px solid rgba(15,27,45,0.07)", borderRadius: 16, boxShadow: "0 10px 30px -24px rgba(15,27,45,0.4)" };
const primaryBtn = (on = true): React.CSSProperties => ({ background: on ? BLUE : "#aeb9c5", border: "none", color: "#fff", borderRadius: 11, padding: "11px 19px", fontSize: 14, fontWeight: 600, cursor: on ? "pointer" : "not-allowed", boxShadow: on ? "0 12px 26px -14px rgba(31,111,235,0.7)" : "none" });
const ghostBtn: React.CSSProperties = { background: "#fff", border: "1px solid rgba(15,27,45,0.12)", color: INK, borderRadius: 11, padding: "11px 17px", fontSize: 14, fontWeight: 600, cursor: "pointer" };
const kicker = (text: string) => <div style={{ fontFamily: MONO, fontSize: 11, letterSpacing: "0.14em", textTransform: "uppercase", color: BLUE, marginBottom: 8 }}>{text}</div>;
const h1Sx: React.CSSProperties = { margin: 0, fontFamily: DISPLAY, fontSize: 28, fontWeight: 700, letterSpacing: "-0.02em", color: INK };
const leadSx: React.CSSProperties = { margin: "9px 0 0", maxWidth: 690, fontSize: 14, lineHeight: 1.62, color: SOFT };

function formatBand(b: string): string {
  return ({ up_to_50m: "≤50m", "50m_to_200m": "50m–200m", above_200m: "≥200m" } as Record<string, string>)[b] || b.replace(/_/g, " ");
}

type Cite = (c: { source: string | null; reference: string | null; detail: string; date?: string | null }) => void;

export function PageSourcing({
  demoMode, demoCases, coverage,
}: {
  demoMode: boolean; demoCases: DemoCaseSummary[]; coverage: Coverage | null;
}) {
  const cite = useCite().open;

  const [step, setStep] = useState(1);
  const [maxReached, setMaxReached] = useState(1);
  const [caseId, setCaseId] = useState<string | null>(null);
  const [heroTrade, setHeroTrade] = useState("electrical");
  const [tender, setTender] = useState<TenderPackage | null>(null);
  const [scopeFixture, setScopeFixture] = useState<string | null>(null);
  const [replies, setReplies] = useState<BidReply[]>([]);
  const [rationaleFixture, setRationaleFixture] = useState<string | null>(null);
  const [scope, setScope] = useState<ScopePackages | null>(null);
  const [shortlist, setShortlist] = useState<ShortlistSet | null>(null);
  const [approvals, setApprovals] = useState<Record<string, string[]>>({});
  const [dispatch, setDispatch] = useState<DispatchSet | null>(null);
  const [levelled, setLevelled] = useState<LevelledBid[] | null>(null);
  const [levelStale, setLevelStale] = useState(false);
  const [recommendation, setRecommendation] = useState<Recommendation | null>(null);
  const [award, setAward] = useState<string | null>(null);
  const [barReveal, setBarReveal] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { if (step === 5) { setBarReveal(false); const t = setTimeout(() => setBarReveal(true), 90); return () => clearTimeout(t); } }, [step]);

  async function run(fn: () => Promise<void>) {
    setLoading(true); setError(null);
    try { await fn(); } catch (e) { setError(e instanceof Error ? e.message : String(e)); } finally { setLoading(false); }
  }
  function advance(to: number) { setStep(to); setMaxReached((m) => Math.max(m, to)); }
  function invalidateAfter(keep: number) {
    if (keep < 2) { setShortlist(null); setApprovals({}); }
    if (keep < 3) setDispatch(null);
    if (keep < 4) { setLevelled(null); setLevelStale(false); }
    if (keep < 5) setRecommendation(null);
    setMaxReached((m) => Math.min(m, keep));
  }
  const goTo = (n: number) => { if (n <= maxReached) setStep(n); };

  const pickDemo = (id: string) => run(async () => {
    const src = await api.demoCase(id);
    setCaseId(id); setHeroTrade(src.hero_trade); setTender(src.tender); setScopeFixture(src.scope_fixture); setReplies(src.replies); setRationaleFixture(src.rationale_fixture);
    setScope(null); invalidateAfter(1);
  });
  const runIngest = () => run(async () => { if (!tender) return; setScope(await api.ingest(tender, scopeFixture)); invalidateAfter(1); });
  const goShortlist = () => run(async () => {
    if (!scope) return;
    const res = await api.shortlist(scope);
    setShortlist(res);
    const def: Record<string, string[]> = {};
    for (const [t, cs] of Object.entries(res.per_trade)) { const p = cs.find((c) => !c.recommended_against) ?? cs[0]; if (p) def[t] = [p.firm.firm_id]; }
    setApprovals(def); advance(2);
  });
  function toggleApprove(t: string, id: string) {
    setApprovals((cur) => { const ids = cur[t] ?? []; return { ...cur, [t]: ids.includes(id) ? ids.filter((x) => x !== id) : [...ids, id] }; });
    setDispatch(null);
  }
  const sendDispatch = () => run(async () => { if (!shortlist || !scope) return; setDispatch(await api.dispatch({ shortlist, approvals, scope, project_name: scope.project_name, send: true })); });
  const goLevel = () => run(async () => { setLevelled(await api.level(replies, scope)); setLevelStale(false); advance(4); });
  function editRate(firmId: string, ref: string, rate: number | null) {
    setReplies((cur) => cur.map((r) => r.firm_id !== firmId ? r : { ...r, line_items: r.line_items.map((l) => l.item_ref !== ref ? l : { ...l, rate, amount: rate == null ? null : l.qty * rate }) }));
    setLevelStale(true); setRecommendation(null); setMaxReached((m) => Math.min(m, 4));
  }
  const recompute = () => run(async () => { setLevelled(await api.level(replies, scope)); setLevelStale(false); });
  const goRecommend = () => run(async () => { if (!levelled) return; const r = await api.recommend(levelled, heroTrade, rationaleFixture); setRecommendation(r); setAward(r.recommended_firm_id); advance(5); });
  function reset() {
    setStep(1); setMaxReached(1); setCaseId(null); setTender(null); setScopeFixture(null); setReplies([]); setRationaleFixture(null);
    setScope(null); setShortlist(null); setApprovals({}); setDispatch(null); setLevelled(null); setLevelStale(false); setRecommendation(null); setAward(null);
  }

  const covTotal = coverage?.total_firms ?? 134, covFlagged = coverage?.flagged_firms ?? 46;

  return (
    <main style={{ maxWidth: 1220, margin: "0 auto", padding: "30px 30px 80px" }}>
      <div style={{ display: "grid", gridTemplateColumns: "262px 1fr", gap: 42, alignItems: "start" }}>
        <Stepper step={step} maxReached={maxReached} goTo={goTo} covTotal={covTotal} covFlagged={covFlagged} />
        <div style={{ minWidth: 0 }}>
          {error && <div style={{ marginBottom: 16, borderRadius: 12, border: "1px solid rgba(229,72,77,0.3)", background: rgba("#E5484D", 0.08), padding: "12px 15px", fontSize: 13.5, color: "#E5484D" }}>Something went wrong: {error}</div>}
          {step === 1 && <StepIngest {...{ demoMode, demoCases, caseId, scope, loading, pickDemo, runIngest, goShortlist }} />}
          {step === 2 && shortlist && <StepShortlist {...{ shortlist, heroTrade, covTotal, covFlagged, loading, cite, onBack: () => goTo(1), onNext: () => advance(3), onLevel: goLevel }} />}
          {step === 3 && shortlist && <StepDispatch {...{ shortlist, approvals, dispatch, loading, toggleApprove, sendDispatch, onBack: () => goTo(2), onNext: goLevel }} />}
          {step === 4 && levelled && <StepLevel {...{ levelled, replies, levelStale, loading, editRate, recompute, onBack: () => goTo(3), onNext: goRecommend }} />}
          {step === 5 && recommendation && <StepRecommend {...{ recommendation, award, barReveal, cite, setAward, onBack: () => goTo(4), onReset: reset }} />}
        </div>
      </div>
    </main>
  );
}

// ----------------------------------------------------------------------------
function Stepper({ step, maxReached, goTo, covTotal, covFlagged }: { step: number; maxReached: number; goTo: (n: number) => void; covTotal: number; covFlagged: number }) {
  const defs: [number, string, string][] = [[1, "Ingest", "Split the tender by trade"], [2, "Shortlist", "Rank firms with evidence"], [3, "Dispatch", "Invite & send (mock)"], [4, "Level", "Correct & compare bids"], [5, "Recommend", "Risk-adjusted award"]];
  return (
    <nav style={{ position: "sticky", top: 88 }}>
      <div style={{ fontFamily: MONO, fontSize: 10.5, letterSpacing: "0.14em", textTransform: "uppercase", color: FAINT, marginBottom: 16, paddingLeft: 4 }}>Sourcing workflow</div>
      <ol style={{ margin: 0, padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 2 }}>
        {defs.map(([n, label, hint]) => {
          const active = n === step, done = n < step, reachable = n <= maxReached;
          return (
            <li key={n} style={{ position: "relative" }}>
              {n !== 5 && <span style={{ position: "absolute", left: 21, top: 44, width: 2, height: "calc(100% - 26px)", background: done ? BLUE : "rgba(15,27,45,0.12)" }} />}
              <button type="button" onClick={() => goTo(n)} style={{ width: "100%", display: "flex", alignItems: "center", gap: 13, textAlign: "left", border: "none", background: active ? rgba(BLUE, 0.07) : "transparent", borderRadius: 12, padding: "9px 11px", cursor: reachable ? "pointer" : "not-allowed" }}>
                <span style={{ display: "flex", alignItems: "center", justifyContent: "center", width: 32, height: 32, flex: "none", borderRadius: 10, border: `1.5px solid ${active ? BLUE : done ? rgba(BLUE, 0.4) : "rgba(15,27,45,0.14)"}`, background: active ? BLUE : done ? rgba(BLUE, 0.1) : "#fff", color: active ? "#fff" : done ? BLUE : FAINT, fontFamily: MONO, fontSize: 13, fontWeight: 600, boxShadow: active ? "0 8px 18px -8px rgba(31,111,235,0.7)" : "none" }}>{done ? "✓" : n}</span>
                <span style={{ minWidth: 0 }}>
                  <span style={{ display: "block", fontSize: 13.5, fontWeight: 600, color: n > step && !reachable ? FAINT : INK }}>{label}</span>
                  <span style={{ display: "block", fontSize: 11.5, color: FAINT, marginTop: 1 }}>{hint}</span>
                </span>
              </button>
            </li>
          );
        })}
      </ol>
      <div style={{ marginTop: 20, padding: "14px 15px", borderRadius: 13, ...cardSx, boxShadow: "0 8px 24px -20px rgba(15,27,45,0.4)" }}>
        <div style={{ fontFamily: MONO, fontSize: 10, letterSpacing: "0.1em", textTransform: "uppercase", color: FAINT, marginBottom: 8 }}>Cross-referencing</div>
        <div style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
          <span style={{ fontFamily: DISPLAY, fontSize: 26, fontWeight: 700, color: INK }}>{covTotal}</span>
          <span style={{ fontSize: 12, color: SOFT }}>firms ·</span>
          <span style={{ fontFamily: DISPLAY, fontSize: 26, fontWeight: 700, color: "#E5484D" }}>{covFlagged}</span>
          <span style={{ fontSize: 12, color: SOFT }}>flagged</span>
        </div>
        <p style={{ margin: "8px 0 0", fontSize: 11.5, lineHeight: 1.5, color: FAINT }}>Every shortlist below is checked against the live register.</p>
      </div>
    </nav>
  );
}

// ----------------------------------------------------------------------------
function StepIngest({ demoMode, demoCases, caseId, scope, loading, pickDemo, runIngest, goShortlist }: {
  demoMode: boolean; demoCases: DemoCaseSummary[]; caseId: string | null; scope: ScopePackages | null; loading: boolean;
  pickDemo: (id: string) => void; runIngest: () => void; goShortlist: () => void;
}) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 22 }}>
      <div>
        {kicker("Step 01 · Ingest")}
        <h1 style={h1Sx}>Ingest the tender, split by trade</h1>
        <p style={leadSx}>Choose a demo tender or upload the four documents. The engine reads them and splits the work into one package per trade; the rules engine validates each trade against the taxonomy.</p>
      </div>
      <div style={{ ...cardSx, padding: 22 }}>
        <label style={{ display: "block", fontSize: 14, fontWeight: 600, color: INK, marginBottom: 3 }}>Choose a scenario</label>
        <p style={{ margin: "0 0 16px", fontSize: 12.5, color: FAINT }}>{demoMode ? "Demo mode is offline — each scenario runs the whole pipeline against the seeded database and reproduces identically." : "Prepared scenarios."}</p>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 13 }}>
          {demoCases.map((d) => {
            const on = caseId === d.id, col = tradeColor(d.hero_trade);
            return (
              <button key={d.id} type="button" onClick={() => pickDemo(d.id)} style={{ position: "relative", display: "flex", flexDirection: "column", textAlign: "left", border: `1.5px solid ${on ? BLUE : "rgba(15,27,45,0.12)"}`, background: on ? rgba(BLUE, 0.06) : "#fff", borderRadius: 13, padding: 16, cursor: "pointer" }}>
                <span style={{ display: "inline-flex", width: 30, height: 30, alignItems: "center", justifyContent: "center", borderRadius: 9, background: col, color: "#fff", fontFamily: DISPLAY, fontWeight: 700, fontSize: 14, marginBottom: 11 }}>{d.name[0]}</span>
                <span style={{ fontSize: 13.5, fontWeight: 600, color: on ? BLUE : INK }}>{d.name}</span>
                <span style={{ fontSize: 12, lineHeight: 1.5, color: SOFT, marginTop: 6 }}>{d.blurb}</span>
                <span style={{ fontFamily: MONO, fontSize: 9.5, letterSpacing: "0.06em", textTransform: "uppercase", color: FAINT, marginTop: 12 }}>Hero trade · {tradeLabel(d.hero_trade)}</span>
              </button>
            );
          })}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 11, marginTop: 16, padding: 14, border: "1.5px dashed #c4cfdc", borderRadius: 12, background: "#f6f9fc", fontSize: 13, color: FAINT }}>
          <span style={{ fontSize: 16 }}>⤒</span> Or upload the four tender documents (PDF, JPEG, PNG) for live extraction
        </div>
      </div>
      <div style={{ display: "flex", justifyContent: "flex-end" }}>
        <button type="button" onClick={runIngest} disabled={!caseId || loading} style={primaryBtn(!!caseId)}>Split the tender →</button>
      </div>
      {scope && (
        <>
          <div className="ssRise" style={{ ...cardSx, overflow: "hidden" }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "15px 20px", borderBottom: "1px solid #eef1f6", background: "linear-gradient(90deg,rgba(31,111,235,0.06),transparent)" }}>
              <h2 style={{ margin: 0, fontSize: 14.5, fontWeight: 600, color: INK }}>{scope.project_name}</h2>
              <span style={{ background: rgba(BLUE, 0.12), color: BLUE, fontSize: 11, fontWeight: 600, padding: "4px 11px", borderRadius: 999 }}>{scope.packages.length} trades</span>
            </div>
            <ul style={{ margin: 0, padding: 0, listStyle: "none" }}>
              {scope.packages.map((p) => (
                <li key={p.trade} style={{ padding: "16px 20px", borderBottom: "1px solid #eef1f6" }}>
                  <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 9 }}>
                    <span style={{ width: 9, height: 9, borderRadius: "50%", background: tradeColor(p.trade) }} />
                    <span style={{ fontSize: 14, fontWeight: 600, color: INK }}>{tradeLabel(p.trade)}</span>
                    <span style={{ background: "#EEF2F7", color: SOFT, fontSize: 11, fontWeight: 500, padding: "3px 9px", borderRadius: 999 }}>{p.sor_items.length} SoR items</span>
                    {p.source_refs.map((r) => <span key={r} style={{ fontFamily: MONO, fontSize: 11, color: FAINT }}>{r}</span>)}
                  </div>
                  <p style={{ margin: "8px 0 0", fontSize: 13, lineHeight: 1.55, color: SOFT }}>{p.scope_summary}</p>
                </li>
              ))}
            </ul>
          </div>
          <div style={{ display: "flex", justifyContent: "flex-end" }}>
            <button type="button" onClick={goShortlist} style={primaryBtn(true)}>Shortlist subcontractors →</button>
          </div>
        </>
      )}
    </div>
  );
}

// ----------------------------------------------------------------------------
function citeButton(e: { source: string; reference: string | null; snippet: string }, cite: Cite) {
  const reg = registerFor(e.source);
  return (
    <button type="button" onClick={() => cite({ source: e.source, reference: e.reference, detail: e.snippet })} style={{ display: "inline-flex", alignItems: "center", gap: 8, marginTop: 7, cursor: "pointer", border: `1px solid ${rgba(reg.color, 0.3)}`, background: "#fff", borderRadius: 8, padding: "5px 10px" }}>
      <span style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", minWidth: 16, height: 16, padding: "0 3px", borderRadius: 5, background: reg.color, color: "#fff", fontFamily: MONO, fontSize: 10, fontWeight: 600 }}>{reg.short}</span>
      <span style={{ fontFamily: MONO, fontSize: 11, fontWeight: 600, color: reg.color }}>{reg.short}</span>
      {e.reference && <span style={{ fontFamily: MONO, fontSize: 11, color: FAINT }}>{e.reference}</span>}
      <span style={{ fontSize: 11, color: FAINT }}>→ source</span>
    </button>
  );
}

function StepShortlist({ shortlist, heroTrade, covTotal, covFlagged, loading, cite, onBack, onNext, onLevel }: {
  shortlist: ShortlistSet; heroTrade: string; covTotal: number; covFlagged: number; loading: boolean; cite: Cite; onBack: () => void; onNext: () => void; onLevel: () => void;
}) {
  const trades = Object.keys(shortlist.per_trade).sort((a, b) => (a === heroTrade ? -1 : b === heroTrade ? 1 : a.localeCompare(b)));
  const totalCandidates = Object.values(shortlist.per_trade).reduce((n, cs) => n + cs.length, 0);

  // No firm in the discovery database does this tender's work sections (e.g. the
  // ground-investigation drainage scenario). Be honest rather than render a blank
  // panel, and route straight to leveling — the scenario's point is ingest + level.
  if (totalCandidates === 0) {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
        <div>
          {kicker("Step 02 · Shortlist")}
          <h1 style={h1Sx}>No matching subcontractors to screen</h1>
        </div>
        <div style={{ ...cardSx, padding: 22, borderColor: rgba("#D99513", 0.3) }}>
          <div style={{ display: "flex", alignItems: "center", gap: 11, marginBottom: 13 }}>
            <span style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", width: 34, height: 34, borderRadius: 10, background: rgba("#D99513", 0.12), fontSize: 18 }}>🛈</span>
            <span style={{ fontFamily: MONO, fontSize: 10.5, fontWeight: 600, letterSpacing: "0.08em", textTransform: "uppercase", color: "#9a6a08" }}>No risk screen for this work section</span>
          </div>
          <p style={{ margin: 0, fontSize: 14, lineHeight: 1.65, color: SOFT }}>
            No subcontractors in the discovery database match this work section. This demo's
            register data covers building contractors; ground-investigation specialists are on
            the roadmap. This scenario demonstrates document ingest and bid leveling.
          </p>
        </div>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, paddingTop: 4 }}>
          <button type="button" onClick={onBack} style={ghostBtn}>← Back</button>
          <button type="button" onClick={onLevel} disabled={loading} style={primaryBtn(true)}>Level the bids →</button>
        </div>
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      <div>
        {kicker("Step 02 · Shortlist")}
        <h1 style={h1Sx}>Shortlist per trade — with cited evidence</h1>
        <p style={leadSx}>The database returns firms scored by how well their closeout history matches the scope. The ranking is deterministic — a firm with a fatal flag is demoted below every clean firm regardless of price or match.</p>
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 12, background: "linear-gradient(120deg,rgba(31,111,235,0.08),rgba(110,86,207,0.08))", border: "1px solid rgba(31,111,235,0.18)", borderRadius: 13, padding: "14px 17px" }}>
        <span style={{ fontSize: 20 }}>🛡️</span>
        <p style={{ margin: 0, fontSize: 13, lineHeight: 1.55, color: INK }}>Screening against <span style={{ fontFamily: MONO, fontWeight: 600 }}>{covTotal}</span> firms from official registers — <span style={{ fontFamily: MONO, fontWeight: 600, color: "#E5484D" }}>{covFlagged}</span> carry verified public risk flags, each linked to its government source.</p>
      </div>
      {trades.map((t) => {
        const cands = shortlist.per_trade[t]; const isHero = t === heroTrade; const flaggedN = cands.filter((c) => c.recommended_against).length; const dot = tradeColor(t);
        return (
          <div key={t} style={{ background: "#fff", border: `1px solid ${isHero ? rgba("#E5484D", 0.3) : "rgba(15,27,45,0.07)"}`, borderRadius: 16, overflow: "hidden", boxShadow: isHero ? `0 0 0 4px ${rgba("#E5484D", 0.06)}, 0 12px 32px -24px rgba(15,27,45,0.4)` : "0 10px 30px -24px rgba(15,27,45,0.4)" }}>
            <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", justifyContent: "space-between", gap: 8, padding: "14px 19px", borderBottom: "1px solid #eef1f6" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
                <span style={{ width: 10, height: 10, borderRadius: "50%", background: dot }} />
                <h2 style={{ margin: 0, fontSize: 14.5, fontWeight: 600, color: INK }}>{tradeLabel(t)}</h2>
                {isHero && <span style={{ fontFamily: MONO, fontSize: 10, letterSpacing: "0.06em", textTransform: "uppercase", color: "#D99513", background: rgba("#D99513", 0.12), padding: "3px 8px", borderRadius: 6 }}>⚠ watch this trade</span>}
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                {flaggedN > 0 && <span style={{ background: rgba("#E5484D", 0.1), color: "#E5484D", fontSize: 11, fontWeight: 600, padding: "3px 10px", borderRadius: 999 }}>{flaggedN} flagged</span>}
                <span style={{ background: "#EEF2F7", color: SOFT, fontSize: 11, fontWeight: 500, padding: "3px 10px", borderRadius: 999 }}>{cands.length} firms</span>
              </div>
            </div>
            <ol style={{ margin: 0, padding: 0, listStyle: "none" }}>
              {cands.map((c, i) => {
                const fatal = c.risk_flags.filter((f) => f.severity === "fatal"); const warn = c.risk_flags.filter((f) => f.severity !== "fatal");
                const mb = c.match_score >= 0.7 ? "#2EA56A" : c.match_score >= 0.5 ? BLUE : FAINT;
                return (
                  <li key={c.firm.firm_id} style={{ padding: "16px 19px", borderBottom: "1px solid #eef1f6", background: c.recommended_against ? rgba("#E5484D", 0.04) : "transparent" }}>
                    <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 10 }}>
                      <span style={{ display: "flex", alignItems: "center", justifyContent: "center", width: 26, height: 26, flex: "none", borderRadius: 9, border: `1px solid ${c.recommended_against ? rgba("#E5484D", 0.4) : "rgba(15,27,45,0.14)"}`, fontFamily: MONO, fontSize: 12, fontWeight: 600, color: c.recommended_against ? "#E5484D" : SOFT, background: c.recommended_against ? rgba("#E5484D", 0.08) : "#fff" }}>{i + 1}</span>
                      <span style={{ fontFamily: DISPLAY, fontSize: 16, fontWeight: 600, color: INK }}>{c.firm.name}</span>
                      <span style={{ fontFamily: MONO, fontSize: 11, color: FAINT }}>{c.firm.firm_id}</span>
                      <span style={{ display: "inline-flex", alignItems: "center", gap: 7 }}>
                        <span style={{ width: 64, height: 6, borderRadius: 3, background: "#EEF2F7", overflow: "hidden" }}><span style={{ display: "block", height: "100%", width: `${Math.round(c.match_score * 100)}%`, background: mb }} /></span>
                        <span style={{ fontFamily: MONO, fontSize: 11.5, fontWeight: 600, color: c.match_score >= 0.7 ? "#2EA56A" : c.match_score >= 0.5 ? BLUE : SOFT }}>{Math.round(c.match_score * 100)}%</span>
                      </span>
                      {i === 0 && !c.recommended_against && <span style={{ background: rgba("#2EA56A", 0.12), color: "#2EA56A", fontSize: 11, fontWeight: 600, padding: "2px 10px", borderRadius: 999 }}>✓ Top pick</span>}
                      {c.recommended_against && <span style={{ display: "inline-flex", alignItems: "center", gap: 5, background: "#E5484D", color: "#fff", fontSize: 11, fontWeight: 700, padding: "3px 11px", borderRadius: 999, whiteSpace: "nowrap", boxShadow: "0 6px 16px -8px rgba(229,72,77,0.8)" }}>⛔ Recommend against</span>}
                      <span style={{ marginLeft: "auto", fontSize: 11.5, color: FAINT }}>{c.firm.registered_grade} · {formatBand(c.firm.value_band)}</span>
                    </div>
                    {c.firm.closeout_summary && <p style={{ margin: "10px 0 0", fontSize: 12.5, lineHeight: 1.55, color: SOFT }}>{c.firm.closeout_summary}</p>}
                    {fatal.length > 0 && (
                      <div style={{ marginTop: 12, border: `1px solid ${rgba("#E5484D", 0.3)}`, background: "linear-gradient(180deg,rgba(229,72,77,0.06),rgba(229,72,77,0.02))", borderRadius: 13, padding: 15 }}>
                        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 11 }}>
                          <span style={{ fontSize: 15 }}>⛔</span>
                          <p style={{ margin: 0, fontFamily: MONO, fontSize: 10.5, fontWeight: 600, letterSpacing: "0.08em", textTransform: "uppercase", color: "#E5484D" }}>Disqualifying — do not award regardless of price</p>
                        </div>
                        {fatal.map((fl, fi) => <FlagPanel key={fi} flag={fl} sev="fatal" cite={cite} />)}
                      </div>
                    )}
                    {warn.length > 0 && <div style={{ marginTop: 11 }}>{warn.map((fl, fi) => <FlagPanel key={fi} flag={fl} sev="warning" cite={cite} />)}</div>}
                  </li>
                );
              })}
            </ol>
          </div>
        );
      })}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, paddingTop: 4 }}>
        <button type="button" onClick={onBack} style={ghostBtn}>← Back</button>
        <button type="button" onClick={onNext} disabled={loading} style={primaryBtn(true)}>Dispatch enquiries →</button>
      </div>
    </div>
  );
}

function FlagPanel({ flag, sev, cite }: { flag: { label: string; rule_ref: string; evidence: { source: string; signal_type: string; snippet: string; reference: string }[] }; sev: "fatal" | "warning"; cite: Cite }) {
  const fatal = sev === "fatal";
  const tagBg = fatal ? rgba("#E5484D", 0.12) : rgba("#D99513", 0.14), tagFg = fatal ? "#E5484D" : "#9a6a08", dot = fatal ? "#E5484D" : "#D99513";
  return (
    <div style={{ background: "#fff", border: `1px solid ${fatal ? rgba("#E5484D", 0.22) : rgba("#D99513", 0.3)}`, borderRadius: 11, padding: 13, marginBottom: 9, ...(fatal ? {} : { background: rgba("#D99513", 0.06) }) }}>
      <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 8 }}>
        <span style={{ display: "inline-flex", alignItems: "center", gap: 5, background: tagBg, color: tagFg, fontFamily: MONO, fontSize: 9.5, fontWeight: 600, letterSpacing: "0.05em", textTransform: "uppercase", padding: "3px 8px", borderRadius: 6 }}><span style={{ width: 5, height: 5, borderRadius: "50%", background: dot }} />{fatal ? "Fatal" : "Warning"}</span>
        <span style={{ fontSize: 13.5, fontWeight: 600, color: INK }}>{flag.label}</span>
        <span style={{ fontFamily: MONO, fontSize: 10.5, color: FAINT }}>{flag.rule_ref}</span>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 10 }}>
        {flag.evidence.map((e, ei) => (
          <div key={ei} style={{ display: "flex", gap: 11, paddingLeft: 11, borderLeft: `2px solid ${registerFor(e.source).color}` }}>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 12, lineHeight: 1.5, color: SOFT }}>{e.snippet}</div>
              {citeButton(e, cite)}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ----------------------------------------------------------------------------
function StepDispatch({ shortlist, approvals, dispatch, loading, toggleApprove, sendDispatch, onBack, onNext }: {
  shortlist: ShortlistSet; approvals: Record<string, string[]>; dispatch: DispatchSet | null; loading: boolean;
  toggleApprove: (t: string, id: string) => void; sendDispatch: () => void; onBack: () => void; onNext: () => void;
}) {
  const trades = Object.keys(shortlist.per_trade);
  const approved = Object.values(approvals).reduce((n, ids) => n + ids.length, 0);
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      <div>
        {kicker("Step 03 · Dispatch")}
        <h1 style={h1Sx}>Dispatch document bundles</h1>
        <p style={leadSx}>Approve which firms to invite (the human gate). Each firm receives only its trade's documents and a composed enquiry email. Nothing is sent — this writes to a mock outbox.</p>
      </div>
      {trades.map((t) => (
        <div key={t} style={{ ...cardSx, overflow: "hidden" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 9, padding: "14px 19px", borderBottom: "1px solid #eef1f6" }}>
            <span style={{ width: 10, height: 10, borderRadius: "50%", background: tradeColor(t) }} />
            <span style={{ fontSize: 14.5, fontWeight: 600, color: INK }}>{tradeLabel(t)}</span>
          </div>
          <ul style={{ margin: 0, padding: 0, listStyle: "none" }}>
            {shortlist.per_trade[t].map((c) => (
              <li key={c.firm.firm_id} style={{ display: "flex", alignItems: "center", gap: 12, padding: "13px 19px", borderBottom: "1px solid #eef1f6" }}>
                <input type="checkbox" checked={(approvals[t] ?? []).includes(c.firm.firm_id)} onChange={() => toggleApprove(t, c.firm.firm_id)} style={{ width: 17, height: 17, accentColor: BLUE, cursor: "pointer" }} />
                <span style={{ fontSize: 14, fontWeight: 500, color: INK }}>{c.firm.name}</span>
                <span style={{ fontFamily: MONO, fontSize: 11, color: FAINT }}>{c.firm.firm_id}</span>
                {c.recommended_against && <span style={{ background: rgba("#E5484D", 0.1), color: "#E5484D", fontSize: 11, fontWeight: 600, padding: "2px 9px", borderRadius: 999 }}>recommended against</span>}
              </li>
            ))}
          </ul>
        </div>
      ))}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
        <span style={{ fontSize: 13.5, color: SOFT }}>{approved} firm{approved === 1 ? "" : "s"} approved.</span>
        <button type="button" onClick={sendDispatch} disabled={approved === 0 || loading} style={primaryBtn(approved > 0)}>Send to approved firms (mock) →</button>
      </div>
      {dispatch && (
        <div className="ssRise" style={{ ...cardSx, overflow: "hidden" }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "14px 19px", borderBottom: "1px solid #eef1f6", background: "linear-gradient(90deg,rgba(46,165,106,0.08),transparent)" }}>
            <h2 style={{ margin: 0, fontSize: 14.5, fontWeight: 600, color: INK }}>Mock outbox</h2>
            <span style={{ background: rgba("#2EA56A", 0.12), color: "#2EA56A", fontSize: 11, fontWeight: 600, padding: "4px 11px", borderRadius: 999 }}>{dispatch.bundles.length} sent</span>
          </div>
          <ul style={{ margin: 0, padding: 0, listStyle: "none" }}>
            {dispatch.bundles.map((b) => (
              <li key={`${b.trade}-${b.firm_id}`} style={{ padding: "16px 19px", borderBottom: "1px solid #eef1f6" }}>
                <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 9 }}>
                  <span style={{ fontSize: 14, fontWeight: 600, color: INK }}>{b.firm_name}</span>
                  <span style={{ fontFamily: MONO, fontSize: 11, color: FAINT }}>{b.firm_id}</span>
                  <span style={{ background: rgba(BLUE, 0.1), color: BLUE, fontSize: 11, fontWeight: 500, padding: "3px 9px", borderRadius: 999 }}>{tradeLabel(b.trade)}</span>
                  <span style={{ marginLeft: "auto", background: rgba("#2EA56A", 0.12), color: "#2EA56A", fontSize: 11, fontWeight: 600, padding: "3px 11px", borderRadius: 999 }}>Sent (mock)</span>
                </div>
                <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 7, marginTop: 11 }}>
                  <span style={{ fontSize: 12, fontWeight: 500, color: SOFT }}>Enclosed:</span>
                  {b.bundle_doc_refs.map((d) => <span key={d} style={{ fontFamily: MONO, fontSize: 11, color: SOFT, background: "#EEF2F7", borderRadius: 6, padding: "2px 8px" }}>{d}</span>)}
                </div>
                <div style={{ marginTop: 11, border: "1px solid #eef1f6", background: "#f6f9fc", borderRadius: 10, padding: "13px 15px" }}>
                  <div style={{ fontSize: 12.5, fontWeight: 600, color: INK }}>{b.email_subject}</div>
                  <p style={{ margin: "6px 0 0", whiteSpace: "pre-line", fontSize: 12, lineHeight: 1.6, color: SOFT }}>{b.email_body}</p>
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, paddingTop: 4 }}>
        <button type="button" onClick={onBack} style={ghostBtn}>← Back</button>
        <button type="button" onClick={onNext} disabled={!dispatch || loading} style={primaryBtn(!!dispatch)}>Level the bids →</button>
      </div>
    </div>
  );
}

// ----------------------------------------------------------------------------
function StepLevel({ levelled, replies, levelStale, loading, editRate, recompute, onBack, onNext }: {
  levelled: LevelledBid[]; replies: BidReply[]; levelStale: boolean; loading: boolean;
  editRate: (firmId: string, ref: string, rate: number | null) => void; recompute: () => void; onBack: () => void; onNext: () => void;
}) {
  const correctedOf = new Map(levelled.map((b) => [b.firm_id, b.corrected_total]));
  const claimedOf = new Map(replies.map((r) => [r.firm_id, r.claimed_total ?? 0]));
  const nameOf = new Map(levelled.map((b) => [b.firm_id, b.firm_name]));
  const cheapest = Math.min(...levelled.map((b) => b.corrected_total));
  const items = replies[0]?.line_items.map((l) => ({ ref: l.item_ref, desc: l.description })) ?? [];
  const line = (fid: string, ref: string) => replies.find((r) => r.firm_id === fid)?.line_items.find((l) => l.item_ref === ref);
  const th: React.CSSProperties = { textAlign: "left", fontFamily: MONO, fontSize: 10.5, fontWeight: 600, letterSpacing: "0.06em", textTransform: "uppercase", color: FAINT, padding: "10px 19px" };
  const thr: React.CSSProperties = { ...th, textAlign: "right" };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      <div>
        {kicker("Step 04 · Level")}
        <h1 style={h1Sx}>Level the bids on a like-for-like basis</h1>
        <p style={leadSx}>The rules engine recomputes every amount as qty × rate, flags arithmetic errors, treats a missing rate or provisional sum as a scope gap, and keeps exclusions non-comparable. Edit a rate and recompute to see the ranking move.</p>
      </div>

      <div style={{ ...cardSx, overflow: "hidden" }}>
        <h2 style={{ margin: 0, padding: "14px 19px", borderBottom: "1px solid #eef1f6", fontFamily: MONO, fontSize: 10.5, fontWeight: 600, letterSpacing: "0.1em", textTransform: "uppercase", color: SOFT }}>Claimed vs corrected</h2>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead><tr style={{ borderBottom: "1px solid #eef1f6" }}><th style={th}>Firm</th><th style={thr}>Claimed</th><th style={thr}>Corrected</th><th style={thr}>Normalised</th><th style={th}>Notes</th></tr></thead>
          <tbody>
            {[...levelled].sort((a, b) => a.corrected_total - b.corrected_total).map((b) => {
              const claimed = claimedOf.get(b.firm_id) ?? 0, delta = b.corrected_total - claimed;
              return (
                <tr key={b.firm_id} style={{ borderBottom: "1px solid #eef1f6", background: b.corrected_total === cheapest ? rgba("#2EA56A", 0.05) : "transparent" }}>
                  <td style={{ padding: "13px 19px" }}><span style={{ fontSize: 14, fontWeight: 600, color: INK }}>{b.firm_name}</span> <span style={{ fontFamily: MONO, fontSize: 11, color: FAINT }}>{b.firm_id}</span></td>
                  <td style={{ padding: "13px 19px", textAlign: "right", fontFamily: MONO, fontVariantNumeric: "tabular-nums", fontSize: 13, color: SOFT }}>{hkd(claimed)}</td>
                  <td style={{ padding: "13px 19px", textAlign: "right", fontFamily: MONO, fontVariantNumeric: "tabular-nums", fontSize: 13, fontWeight: 600, color: INK }}>{hkd(b.corrected_total)}{Math.abs(delta) > 0.5 && <span style={{ color: "#E5484D", fontWeight: 500 }}>  ({delta > 0 ? "+" : ""}{hkd(delta)})</span>}</td>
                  <td style={{ padding: "13px 19px", textAlign: "right", fontFamily: MONO, fontVariantNumeric: "tabular-nums", fontSize: 13, color: SOFT }}>{hkd(b.normalized_total)}</td>
                  <td style={{ padding: "13px 19px" }}>
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                      {b.arithmetic_findings.length > 0 && <span style={{ background: rgba("#E5484D", 0.1), color: "#E5484D", fontSize: 11, fontWeight: 500, padding: "2px 9px", borderRadius: 999 }}>{b.arithmetic_findings.length} corrected</span>}
                      {b.scope_gaps.length > 0 && <span style={{ background: rgba(BLUE, 0.1), color: BLUE, fontSize: 11, fontWeight: 500, padding: "2px 9px", borderRadius: 999 }}>{b.scope_gaps.length} scope gap</span>}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="ssx" style={{ ...cardSx, overflowX: "auto" }}>
        <h2 style={{ margin: 0, padding: "14px 19px", borderBottom: "1px solid #eef1f6", fontFamily: MONO, fontSize: 10.5, fontWeight: 600, letterSpacing: "0.1em", textTransform: "uppercase", color: SOFT }}>Rates by item — edit a rate to re-level</h2>
        <table style={{ width: "100%", minWidth: 680, borderCollapse: "collapse" }}>
          <thead><tr style={{ borderBottom: "1px solid #eef1f6" }}><th style={th}>Item</th>{replies.map((r) => <th key={r.firm_id} style={{ ...thr, textTransform: "none" }}>{r.firm_id}</th>)}</tr></thead>
          <tbody>
            {items.map(({ ref, desc }) => (
              <tr key={ref} style={{ borderBottom: "1px solid #eef1f6" }}>
                <td style={{ padding: "10px 17px", verticalAlign: "top" }}>
                  <div style={{ fontFamily: MONO, fontSize: 11.5, fontWeight: 600, color: INK }}>{ref}</div>
                  <div style={{ fontSize: 11.5, color: FAINT, marginTop: 2, maxWidth: 230 }}>{desc}</div>
                </td>
                {replies.map((r) => {
                  const l = line(r.firm_id, ref); const amt = l && l.rate != null ? l.qty * l.rate : null;
                  return (
                    <td key={r.firm_id} style={{ padding: "10px 17px", textAlign: "right", verticalAlign: "top" }}>
                      <input type="number" value={l?.rate ?? ""} onChange={(e) => editRate(r.firm_id, ref, e.target.value === "" ? null : Number(e.target.value))} style={{ width: 106, border: "1px solid rgba(15,27,45,0.12)", borderRadius: 8, background: "#fff", padding: "7px 9px", textAlign: "right", fontFamily: MONO, fontVariantNumeric: "tabular-nums", fontSize: 12, color: INK, outline: "none" }} />
                      <div style={{ fontFamily: MONO, fontSize: 11, color: FAINT, marginTop: 3 }}>{amt != null ? hkd(amt) : "scope gap"}</div>
                    </td>
                  );
                })}
              </tr>
            ))}
            <tr style={{ borderTop: "2px solid rgba(15,27,45,0.12)", background: "#f6f9fc" }}>
              <td style={{ padding: "12px 17px", fontFamily: MONO, fontSize: 10.5, fontWeight: 600, letterSpacing: "0.06em", textTransform: "uppercase", color: SOFT }}>Corrected total</td>
              {replies.map((r) => <td key={r.firm_id} style={{ padding: "12px 17px", textAlign: "right", fontFamily: MONO, fontVariantNumeric: "tabular-nums", fontSize: 14, fontWeight: 700, color: INK }}>{hkd(correctedOf.get(r.firm_id) ?? 0)}</td>)}
            </tr>
          </tbody>
        </table>
      </div>

      {levelStale && (
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, border: `1px solid ${rgba("#D99513", 0.35)}`, background: rgba("#D99513", 0.08), borderRadius: 12, padding: "13px 17px" }}>
          <span style={{ fontSize: 13.5, color: INK }}>⚠ A rate changed — the corrected totals are stale.</span>
          <button type="button" onClick={recompute} style={{ background: BLUE, border: "none", color: "#fff", borderRadius: 9, padding: "8px 16px", fontSize: 13.5, fontWeight: 600, cursor: "pointer" }}>Recompute</button>
        </div>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 14 }}>
        <CalloutCol title="Arithmetic corrections" color="#E5484D">
          {levelled.flatMap((b) => b.arithmetic_findings.map((f, i) => (
            <li key={`${b.firm_id}-${i}`} style={{ padding: "8px 0", borderBottom: "1px solid #f3f5f9" }}>
              <span style={{ fontSize: 12.5, fontWeight: 600, color: INK }}>{nameOf.get(b.firm_id)}</span> <span style={{ fontFamily: MONO, fontSize: 11, color: FAINT }}>· {f.location}</span>
              <div style={{ fontSize: 11.5, color: SOFT, lineHeight: 1.5, marginTop: 2 }}>{f.issue} → {hkd(f.corrected_value)}</div>
            </li>
          )))}
        </CalloutCol>
        <CalloutCol title="Scope gaps" color={BLUE}>
          {levelled.flatMap((b) => b.scope_gaps.map((g, i) => (
            <li key={`${b.firm_id}-${i}`} style={{ padding: "8px 0", borderBottom: "1px solid #f3f5f9" }}>
              <span style={{ fontSize: 12.5, fontWeight: 600, color: INK }}>{nameOf.get(b.firm_id)}</span>
              <div style={{ fontSize: 11.5, color: SOFT, lineHeight: 1.5, marginTop: 2 }}>{g}</div>
            </li>
          )))}
        </CalloutCol>
        <CalloutCol title="Exclusions" color="#6E56CF">
          {levelled.flatMap((b) => b.exclusions.map((x, i) => (
            <li key={`${b.firm_id}-${i}`} style={{ padding: "8px 0", borderBottom: "1px solid #f3f5f9" }}>
              <span style={{ fontSize: 12.5, fontWeight: 600, color: INK }}>{nameOf.get(b.firm_id)}</span>
              <div style={{ fontSize: 11.5, color: SOFT, lineHeight: 1.5, marginTop: 2 }}>{x}</div>
            </li>
          )))}
        </CalloutCol>
      </div>

      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, paddingTop: 4 }}>
        <button type="button" onClick={onBack} style={ghostBtn}>← Back</button>
        <a href={api.levelingXlsxUrl()} style={{ ...ghostBtn, textDecoration: "none", display: "inline-flex", alignItems: "center", gap: 8 }}>⤓ Download Excel</a>
        <button type="button" onClick={onNext} disabled={levelStale || loading} style={primaryBtn(!levelStale)}>Recommend an award →</button>
      </div>
    </div>
  );
}

function CalloutCol({ title, color, children }: { title: string; color: string; children: React.ReactNode }) {
  const arr = (Array.isArray(children) ? children.flat() : [children]).filter(Boolean);
  return (
    <div style={{ ...cardSx, borderRadius: 13, overflow: "hidden", boxShadow: "none" }}>
      <h3 style={{ margin: 0, padding: "11px 15px", borderBottom: "1px solid #eef1f6", fontFamily: MONO, fontSize: 10, fontWeight: 600, letterSpacing: "0.06em", textTransform: "uppercase", color }}>{title}</h3>
      {arr.length === 0 ? <p style={{ margin: 0, padding: "13px 15px", fontSize: 12, color: FAINT }}>None.</p> : <ul style={{ margin: 0, padding: "6px 15px", listStyle: "none" }}>{children}</ul>}
    </div>
  );
}

// ----------------------------------------------------------------------------
function StepRecommend({ recommendation, award, barReveal, cite, setAward, onBack, onReset }: {
  recommendation: Recommendation; award: string | null; barReveal: boolean; cite: Cite; setAward: (id: string) => void; onBack: () => void; onReset: () => void;
}) {
  const rec = recommendation;
  const winner = rec.ranked.find((r) => r.firm_id === rec.recommended_firm_id);
  const against = rec.ranked.find((r) => r.recommended_against);
  const band = rec.historical_band;
  const byName = new Map(rec.ranked.map((r) => [r.firm_name, r]));
  const maxVal = Math.max(...rec.ranked.map((r) => r.corrected_total), band?.high ?? 0) * 1.16;
  const chart = [...rec.bid_distribution].map((p) => {
    const r = byName.get(p.firm_name); const isWin = r && r.firm_id === rec.recommended_firm_id; const ag = r?.recommended_against;
    return { name: p.firm_name, value: p.corrected_total, fill: isWin ? "#2EA56A" : ag ? "#E5484D" : "#6E56CF", glow: isWin ? `0 6px 16px -8px ${rgba("#2EA56A", 0.8)}` : ag ? `0 6px 16px -8px ${rgba("#E5484D", 0.7)}` : "none" };
  }).sort((a, b) => a.value - b.value);
  const awardRow = rec.ranked.find((r) => r.firm_id === award); const overriding = !!awardRow?.recommended_against;
  const pct = (v: number) => `${((v / maxVal) * 100).toFixed(2)}%`;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      <div>
        {kicker("Step 05 · Recommend")}
        <h1 style={h1Sx}>The risk-adjusted recommendation</h1>
        <p style={leadSx}>The engine ranks by corrected price but reads each firm against the database. A firm with a fatal flag is recommended against regardless of price. The rationale is narrated — the engine never chooses the winner.</p>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
        {winner && (
          <div style={{ border: `1px solid ${rgba("#2EA56A", 0.35)}`, background: "linear-gradient(160deg,rgba(46,165,106,0.10),rgba(46,165,106,0.02))", borderRadius: 16, padding: 18 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, fontFamily: MONO, fontSize: 10.5, fontWeight: 600, letterSpacing: "0.08em", textTransform: "uppercase", color: "#2EA56A", marginBottom: 12 }}><span style={{ fontSize: 15 }}>✅</span> Recommend · award</div>
            <div style={{ fontFamily: DISPLAY, fontSize: 21, fontWeight: 700, lineHeight: 1.15, color: INK }}>{winner.firm_name}</div>
            <div style={{ fontFamily: MONO, fontSize: 12, color: SOFT, marginTop: 5 }}>{winner.firm_id} · {hkd(winner.corrected_total)}</div>
            <span style={{ display: "inline-block", marginTop: 12, background: rgba("#2EA56A", 0.14), color: "#2EA56A", fontSize: 11, fontWeight: 600, padding: "4px 11px", borderRadius: 999 }}>cheapest clean bid</span>
          </div>
        )}
        {against && (
          <div style={{ border: `1px solid ${rgba("#E5484D", 0.35)}`, background: "linear-gradient(160deg,rgba(229,72,77,0.10),rgba(229,72,77,0.02))", borderRadius: 16, padding: 18 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, fontFamily: MONO, fontSize: 10.5, fontWeight: 600, letterSpacing: "0.08em", textTransform: "uppercase", color: "#E5484D", marginBottom: 12 }}><span style={{ fontSize: 15 }}>⛔</span> Recommend against</div>
            <div style={{ fontFamily: DISPLAY, fontSize: 21, fontWeight: 700, lineHeight: 1.15, color: INK }}>{against.firm_name}</div>
            <div style={{ fontFamily: MONO, fontSize: 12, color: SOFT, marginTop: 5 }}>{against.firm_id} · {hkd(against.corrected_total)}</div>
            <span style={{ display: "inline-block", marginTop: 12, background: "#E5484D", color: "#fff", fontSize: 11, fontWeight: 700, padding: "4px 11px", borderRadius: 999 }}>cheapest overall — but disqualified</span>
          </div>
        )}
      </div>

      {against && (
        <div style={{ border: `1px solid ${rgba("#E5484D", 0.25)}`, background: "#fff", borderRadius: 16, padding: 18, boxShadow: "0 10px 30px -24px rgba(15,27,45,0.4)" }}>
          <p style={{ margin: "0 0 13px", fontSize: 13.5, lineHeight: 1.6, color: SOFT }}>{against.reason}</p>
          {against.risk_flags.filter((f) => f.severity === "fatal").map((fl, fi) => <FlagPanel key={fi} flag={fl} sev="fatal" cite={cite} />)}
        </div>
      )}

      {/* chart */}
      <div style={{ ...cardSx, overflow: "hidden" }}>
        <div style={{ padding: "14px 19px", borderBottom: "1px solid #eef1f6" }}>
          <h2 style={{ margin: 0, fontSize: 14.5, fontWeight: 600, color: INK }}>Bid distribution &amp; historical band</h2>
          <p style={{ margin: "4px 0 0", fontSize: 12, color: FAINT }}>Corrected totals; the shaded region is the historical band (low–high), the dashed line the median.</p>
        </div>
        <div style={{ padding: "24px 19px 18px" }}>
          <div style={{ position: "relative" }}>
            {band && (
              <div style={{ position: "absolute", left: 196, right: 16, top: 0, bottom: 30 }}>
                <div style={{ position: "absolute", top: -6, bottom: -6, left: pct(band.low), width: `${(((band.high - band.low)) / maxVal * 100).toFixed(2)}%`, background: "linear-gradient(180deg,rgba(31,111,235,0.10),rgba(110,86,207,0.08))", borderLeft: "1px solid rgba(31,111,235,0.3)", borderRight: "1px solid rgba(31,111,235,0.3)", borderRadius: 4 }} />
                <div style={{ position: "absolute", top: -12, bottom: -12, left: pct(band.median), width: 0, borderLeft: "1.5px dashed #6E56CF" }} />
                <div style={{ position: "absolute", top: -26, left: pct(band.median), transform: "translateX(-50%)", fontFamily: MONO, fontSize: 10, color: "#6E56CF", whiteSpace: "nowrap" }}>median {hkd(band.median)}</div>
              </div>
            )}
            <div style={{ position: "relative", display: "flex", flexDirection: "column", gap: 15 }}>
              {chart.map((r) => (
                <div key={r.name} style={{ display: "flex", alignItems: "center", gap: 11 }}>
                  <div style={{ width: 186, flex: "none", textAlign: "right", fontSize: 12.5, color: INK, lineHeight: 1.25 }}>{r.name}</div>
                  <div style={{ flex: 1, position: "relative", height: 26 }}>
                    <div style={{ position: "absolute", top: 0, left: 0, height: 26, width: barReveal ? pct(r.value) : "0%", background: r.fill, borderRadius: "0 6px 6px 0", boxShadow: r.glow, transition: "width .7s cubic-bezier(.2,.7,.2,1)" }} />
                    <div style={{ position: "absolute", top: 0, height: 26, left: `calc(${barReveal ? pct(r.value) : "0%"} + 9px)`, display: "flex", alignItems: "center", fontFamily: MONO, fontVariantNumeric: "tabular-nums", fontSize: 12, fontWeight: 600, color: INK, whiteSpace: "nowrap", transition: "left .7s cubic-bezier(.2,.7,.2,1)" }}>{hkd(r.value)}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* ranked */}
      <div style={{ ...cardSx, overflow: "hidden" }}>
        <h2 style={{ margin: 0, padding: "14px 19px", borderBottom: "1px solid #eef1f6", fontFamily: MONO, fontSize: 10.5, fontWeight: 600, letterSpacing: "0.1em", textTransform: "uppercase", color: SOFT }}>Ranked — clean firms first, flagged firms demoted</h2>
        <ol style={{ margin: 0, padding: 0, listStyle: "none" }}>
          {rec.ranked.map((r, i) => (
            <li key={r.firm_id} style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 10, padding: "14px 19px", borderBottom: "1px solid #eef1f6", background: r.recommended_against ? rgba("#E5484D", 0.04) : "transparent" }}>
              <span style={{ display: "flex", alignItems: "center", justifyContent: "center", width: 26, height: 26, borderRadius: 9, border: "1px solid rgba(15,27,45,0.12)", fontFamily: MONO, fontSize: 12, fontWeight: 600, color: SOFT }}>{i + 1}</span>
              <span style={{ fontSize: 14, fontWeight: 500, color: INK }}>{r.firm_name}</span>
              <span style={{ fontFamily: MONO, fontSize: 11, color: FAINT }}>{r.firm_id}</span>
              {r.firm_id === rec.recommended_firm_id && <span style={{ background: rgba("#2EA56A", 0.12), color: "#2EA56A", fontSize: 11, fontWeight: 600, padding: "2px 9px", borderRadius: 999 }}>recommended</span>}
              {r.recommended_against && <span style={{ background: rgba("#E5484D", 0.1), color: "#E5484D", fontSize: 11, fontWeight: 600, padding: "2px 9px", borderRadius: 999 }}>recommended against</span>}
              <span style={{ marginLeft: "auto", fontFamily: MONO, fontVariantNumeric: "tabular-nums", fontSize: 14, fontWeight: 600, color: INK }}>{hkd(r.corrected_total)}</span>
            </li>
          ))}
        </ol>
      </div>

      {/* rationale */}
      <div style={{ ...cardSx, padding: 19 }}>
        <h2 style={{ margin: "0 0 11px", fontFamily: MONO, fontSize: 10.5, fontWeight: 600, letterSpacing: "0.1em", textTransform: "uppercase", color: SOFT }}>Rationale — narrated, not decided</h2>
        <blockquote style={{ margin: 0, borderLeft: "3px solid #6E56CF", background: "linear-gradient(120deg,rgba(110,86,207,0.06),rgba(31,111,235,0.04))", borderRadius: "0 11px 11px 0", padding: "15px 17px", fontSize: 14, lineHeight: 1.7, color: "#1d2c40" }}>{rec.rationale}</blockquote>
      </div>

      {/* award */}
      <div style={{ ...cardSx, padding: 19 }}>
        <h2 style={{ margin: 0, fontSize: 14.5, fontWeight: 600, color: INK }}>Award — the human decision</h2>
        <p style={{ margin: "5px 0 14px", fontSize: 12.5, color: FAINT }}>The recommendation is decision support. Select the firm to award — overriding onto a flagged firm is recorded.</p>
        <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
          {rec.ranked.map((r) => {
            const on = award === r.firm_id;
            return (
              <label key={r.firm_id} style={{ display: "flex", alignItems: "center", gap: 11, border: `1.5px solid ${on ? BLUE : "rgba(15,27,45,0.12)"}`, background: on ? rgba(BLUE, 0.05) : "#fff", borderRadius: 12, padding: "12px 15px", cursor: "pointer" }}>
                <input type="radio" name="award" checked={on} onChange={() => setAward(r.firm_id)} style={{ width: 17, height: 17, accentColor: BLUE, cursor: "pointer" }} />
                <span style={{ fontSize: 14, fontWeight: 500, color: INK }}>{r.firm_name}</span>
                <span style={{ fontFamily: MONO, fontSize: 12, color: FAINT }}>{hkd(r.corrected_total)}</span>
                {r.recommended_against && <span style={{ marginLeft: "auto", background: rgba("#E5484D", 0.1), color: "#E5484D", fontSize: 11, fontWeight: 600, padding: "2px 9px", borderRadius: 999 }}>flagged</span>}
              </label>
            );
          })}
        </div>
        <div style={{ marginTop: 14, borderRadius: 11, padding: "12px 15px", fontSize: 13, fontWeight: 500, background: overriding ? rgba("#E5484D", 0.1) : rgba("#2EA56A", 0.1), color: overriding ? "#E5484D" : "#1a8a56" }}>
          {overriding ? `⚠ Override recorded: awarding ${awardRow!.firm_name}, which the engine recommends against.` : awardRow ? `✓ Award recorded: ${awardRow.firm_name} (${hkd(awardRow.corrected_total)}).` : "Select a firm to award."}
        </div>
      </div>

      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, paddingTop: 4 }}>
        <button type="button" onClick={onBack} style={ghostBtn}>← Back</button>
        <button type="button" onClick={onReset} style={ghostBtn}>Start over</button>
      </div>
    </div>
  );
}
