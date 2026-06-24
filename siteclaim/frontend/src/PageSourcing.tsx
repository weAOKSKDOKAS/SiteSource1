import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import { useCite } from "./cite";
import { hkd, registerFor, rgba, tradeColor, tradeLabel } from "./theme";
import type {
  BidReply, Coverage, DispatchSet, FirmProfileFull, LevelledBid, Recommendation, ScopePackages, ShortlistSet,
} from "./types";

const MONO = "'Spline Sans Mono',monospace";
const DISPLAY = "'Bricolage Grotesque',sans-serif";
const INK = "#0F1B2D", SOFT = "#46566b", FAINT = "#8a98ab", BLUE = "#1F6FEB", TEAL = "#0FB5A6";
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
  demoMode, coverage,
}: {
  demoMode: boolean; coverage: Coverage | null;
}) {
  const cite = useCite().open;

  const [step, setStep] = useState(1);
  const [maxReached, setMaxReached] = useState(1);
  const [heroTrade, setHeroTrade] = useState("electrical");
  const [uploadedNames, setUploadedNames] = useState<string[]>([]);
  const [replies, setReplies] = useState<BidReply[]>([]);
  // Set for approval-driven cases: the SoR template bank the leveling replies are built
  // from (per the firms approved in dispatch). null => use the case's fixed replies.
  const [sorFixture, setSorFixture] = useState<string | null>(null);
  const [rationaleFixture, setRationaleFixture] = useState<string | null>(null);
  const [rationaleByTrade, setRationaleByTrade] = useState<Record<string, string>>({});
  const [scope, setScope] = useState<ScopePackages | null>(null);
  const [shortlist, setShortlist] = useState<ShortlistSet | null>(null);
  const [approvals, setApprovals] = useState<Record<string, string[]>>({});
  // Per-section flag: false while the section rides its auto top-2 default; flips true
  // the first time the buyer adds/removes a firm in that section, after which the
  // section carries only the explicit set the buyer has built (see toggleApprove).
  const [touched, setTouched] = useState<Record<string, boolean>>({});
  const [dispatch, setDispatch] = useState<DispatchSet | null>(null);
  const [dispatchSent, setDispatchSent] = useState(false);
  const [phase, setPhase] = useState<"idle" | "sending" | "collecting">("idle");
  const [levelled, setLevelled] = useState<LevelledBid[] | null>(null);
  const [levelStale, setLevelStale] = useState(false);
  const [recommendations, setRecommendations] = useState<Recommendation[]>([]);
  const [awards, setAwards] = useState<Record<string, string | null>>({});
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
    if (keep < 3) { setDispatch(null); setDispatchSent(false); }
    if (keep < 4) { setLevelled(null); setLevelStale(false); }
    if (keep < 5) { setRecommendations([]); setAwards({}); }
    setMaxReached((m) => Math.min(m, keep));
  }
  const goTo = (n: number) => { if (n <= maxReached) setStep(n); };

  // Upload any tender document(s); in the demo every upload routes to the GE/2026/14
  // drainage field-investigation tender. We load that case (for the downstream
  // replies/rationale/heroTrade) and ingest the uploaded files through the real
  // upload endpoint (which returns the drainage scope in DEMO_MODE).
  const runUpload = (files: File[]) => run(async () => {
    if (!files.length) return;
    const src = await api.demoCase("drainage");
    setHeroTrade(src.hero_trade);
    setReplies(src.replies); setSorFixture(src.sor_fixture ?? null); setRationaleFixture(src.rationale_fixture); setRationaleByTrade(src.rationale_by_trade ?? {});
    invalidateAfter(1); setUploadedNames(files.map((f) => f.name));
    setScope(await api.ingestUpload(files));
  });
  const goShortlist = () => run(async () => {
    if (!scope) return;
    const res = await api.shortlist(scope);
    setShortlist(res);
    // Each section defaults to the top two clean firms (benchmark + 2 is the leveling
    // cap), shown pre-added. On a re-run we keep a section the buyer already edited
    // (intersected with the firms still on the new shortlist) and only reset the rest.
    setApprovals((cur) => {
      const next: Record<string, string[]> = {};
      for (const [t, cs] of Object.entries(res.per_trade)) {
        const ids = new Set(cs.map((c) => c.firm.firm_id));
        if (touched[t]) {
          next[t] = (cur[t] ?? []).filter((id) => ids.has(id));
        } else {
          const clean = cs.filter((c) => !c.recommended_against);
          next[t] = (clean.length ? clean : cs).slice(0, 2).map((c) => c.firm.firm_id);
        }
      }
      return next;
    });
    advance(2);
  });
  // A selection action, not a stage re-run: it toggles one firm's membership and never
  // invalidates the leveled/recommend stages. Marking the section touched keeps the
  // buyer's edits from being clobbered if the shortlist is re-run. The auto top-2 are
  // shown pre-selected (never silent) so the buyer can see and change exactly what
  // dispatches; the same approvals drive the dispatch checkboxes and the leveling.
  function toggleApprove(t: string, id: string) {
    setTouched((cur) => (cur[t] ? cur : { ...cur, [t]: true }));
    setApprovals((cur) => {
      const ids = cur[t] ?? [];
      return { ...cur, [t]: ids.includes(id) ? ids.filter((x) => x !== id) : [...ids, id] };
    });
    setDispatch(null);
  }
  const prepareDispatch = () => run(async () => { if (!shortlist || !scope) return; setDispatch(await api.dispatch({ shortlist, approvals, scope, project_name: scope.project_name, send: false })); setDispatchSent(false); });
  const editBundle = (firmId: string, trade: string, patch: Partial<{ email_subject: string; email_body: string }>) =>
    setDispatch((d) => (d ? { ...d, bundles: d.bundles.map((b) => (b.firm_id === firmId && b.trade === trade ? { ...b, ...patch } : b)) } : d));
  const confirmSend = () => setPhase("sending");
  // After the sending animation, actually send: POST the approved (edited) bundles
  // with send=true. The server records the mock outbox and, if N8N_WEBHOOK_URL is set,
  // hands them to n8n which creates the Gmail drafts (status -> drafted_gmail).
  const onSendComplete = () => run(async () => {
    if (dispatch) setDispatch(await api.dispatch({ dispatch, project_name: scope?.project_name ?? "", send: true }));
    setDispatchSent(true); setPhase("idle");
  });
  const startLevel = () => setPhase("collecting");
  // Approval-driven: build the leveling replies from the firms approved in dispatch
  // (so the columns equal the approved firms), then level. Falls back to the case's
  // fixed replies when the scenario ships no SoR template bank.
  const runLevelAfterCollect = () => run(async () => {
    const built = sorFixture ? await api.collectReplies(approvals, sorFixture) : replies;
    if (sorFixture) setReplies(built);
    setLevelled(await api.level(built, scope)); setLevelStale(false); advance(4); setPhase("idle");
  });
  function editRate(firmId: string, ref: string, rate: number | null) {
    setReplies((cur) => cur.map((r) => r.firm_id !== firmId ? r : { ...r, line_items: r.line_items.map((l) => l.item_ref !== ref ? l : { ...l, rate, amount: rate == null ? null : l.qty * rate }) }));
    setLevelStale(true); setRecommendations([]); setAwards({}); setMaxReached((m) => Math.min(m, 4));
  }
  const recompute = () => run(async () => { setLevelled(await api.level(replies, scope)); setLevelStale(false); });
  // Per work section: run the recommendation once per trade the bids cover (hero
  // trade first), each narrated from its own rationale fixture when one exists.
  const goRecommend = () => run(async () => {
    if (!levelled) return;
    const trades = Array.from(new Set(levelled.map((b) => b.trade)))
      .sort((a, b) => (a === heroTrade ? -1 : b === heroTrade ? 1 : a.localeCompare(b)));
    const recs = await Promise.all(
      trades.map((t) => api.recommend(levelled, t, rationaleByTrade[t] ?? (t === heroTrade ? rationaleFixture : null))),
    );
    setRecommendations(recs);
    const aw: Record<string, string | null> = {};
    for (const r of recs) aw[r.trade] = r.recommended_firm_id;
    setAwards(aw); advance(5);
  });
  function reset() {
    setStep(1); setMaxReached(1); setUploadedNames([]); setReplies([]); setSorFixture(null); setRationaleFixture(null);
    setRationaleByTrade({});
    setScope(null); setShortlist(null); setApprovals({}); setTouched({}); setDispatch(null); setDispatchSent(false); setPhase("idle"); setLevelled(null); setLevelStale(false); setRecommendations([]); setAwards({});
  }

  const covTotal = coverage?.total_firms ?? 149, covFlagged = coverage?.flagged_firms ?? 47;

  return (
    <main style={{ maxWidth: 1220, margin: "0 auto", padding: "30px 30px 80px" }}>
      <div style={{ display: "grid", gridTemplateColumns: "262px 1fr", gap: 42, alignItems: "start" }}>
        <Stepper step={step} maxReached={maxReached} goTo={goTo} covTotal={covTotal} covFlagged={covFlagged} />
        <div style={{ minWidth: 0 }}>
          {error && <div style={{ marginBottom: 16, borderRadius: 12, border: "1px solid rgba(229,72,77,0.3)", background: rgba("#E5484D", 0.08), padding: "12px 15px", fontSize: 13.5, color: "#E5484D" }}>Something went wrong: {error}</div>}
          {phase === "sending" && dispatch && <ProcessingOverlay kind="sending" steps={sendingSteps(dispatch)} onDone={onSendComplete} />}
          {phase === "collecting" && <ProcessingOverlay kind="collecting" steps={collectingSteps(sorFixture ? Object.values(approvals).reduce((n, ids) => n + Math.min(ids.length, 2), 0) : new Set(replies.map((r) => r.firm_id)).size)} onDone={runLevelAfterCollect} />}
          {phase === "idle" && <>
          {step === 1 && <StepIngest {...{ demoMode, scope, loading, uploadedNames, runUpload, goShortlist }} />}
          {step === 2 && shortlist && <StepShortlist {...{ shortlist, heroTrade, covTotal, covFlagged, loading, cite, approvals, toggleApprove, onBack: () => goTo(1), onNext: () => advance(3), onLevel: startLevel }} />}
          {step === 3 && shortlist && <StepDispatch {...{ shortlist, approvals, dispatch, dispatchSent, loading, toggleApprove, prepareDispatch, editBundle, confirmSend, onBack: () => goTo(2), onNext: startLevel }} />}
          {step === 4 && levelled && <StepLevel {...{ levelled, replies, heroTrade, levelStale, loading, editRate, recompute, onBack: () => goTo(3), onNext: goRecommend }} />}
          {step === 5 && recommendations.length > 0 && <StepRecommend {...{ recommendations, awards, heroTrade, barReveal, cite, setAward: (t: string, id: string) => setAwards((a) => ({ ...a, [t]: id })), onBack: () => goTo(4), onReset: reset }} />}
          </>}
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
function StepIngest({ demoMode, scope, loading, uploadedNames, runUpload, goShortlist }: {
  demoMode: boolean; scope: ScopePackages | null; loading: boolean; uploadedNames: string[];
  runUpload: (files: File[]) => void; goShortlist: () => void;
}) {
  const [files, setFiles] = useState<File[]>([]);
  const [dragOver, setDragOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const accept = ".pdf,.png,.jpg,.jpeg,.webp,image/*";
  const take = (list: FileList | null) => { if (list && list.length) setFiles((cur) => [...cur, ...Array.from(list)]); };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 22 }}>
      <div>
        {kicker("Step 01 · Ingest")}
        <h1 style={h1Sx}>Upload the tender documents</h1>
        <p style={leadSx}>Drop in the tender package — Method of Measurement, Particular Specification, Schedule of Rates (PDF or images). SiteSource ingests it and splits the work by section, then validates each section against the taxonomy.{demoMode ? " In this demo the upload is routed to the prepared GE/2026/14 ground-investigation tender." : ""}</p>
      </div>

      {!scope && (
        <>
          <div
            onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
            onDragLeave={() => setDragOver(false)}
            onDrop={(e) => { e.preventDefault(); setDragOver(false); take(e.dataTransfer.files); }}
            onClick={() => inputRef.current?.click()}
            style={{ ...cardSx, cursor: "pointer", border: `2px dashed ${dragOver ? BLUE : "rgba(15,27,45,0.18)"}`, background: dragOver ? rgba(BLUE, 0.05) : "#fbfcfe", boxShadow: "none", padding: "40px 24px", display: "flex", flexDirection: "column", alignItems: "center", textAlign: "center", gap: 10 }}
          >
            <div style={{ display: "flex", alignItems: "center", justifyContent: "center", width: 52, height: 52, borderRadius: 14, background: rgba(BLUE, 0.1), color: BLUE, fontSize: 24 }}>⤒</div>
            <div style={{ fontSize: 15, fontWeight: 600, color: INK }}>Drag &amp; drop tender documents here</div>
            <div style={{ fontSize: 12.5, color: FAINT }}>PDF, PNG or JPEG · or <span style={{ color: BLUE, fontWeight: 600 }}>browse files</span></div>
            <input ref={inputRef} type="file" multiple accept={accept} onChange={(e) => { take(e.target.files); e.target.value = ""; }} style={{ display: "none" }} />
          </div>

          {files.length > 0 && (
            <div style={{ ...cardSx, padding: 16 }}>
              <div style={{ fontFamily: MONO, fontSize: 10.5, letterSpacing: "0.08em", textTransform: "uppercase", color: FAINT, marginBottom: 10 }}>{files.length} file{files.length === 1 ? "" : "s"} selected</div>
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {files.map((f, i) => (
                  <div key={`${f.name}-${i}`} style={{ display: "flex", alignItems: "center", gap: 10, padding: "9px 12px", border: "1px solid #eef1f6", borderRadius: 10, background: "#f8fafc" }}>
                    <span style={{ fontSize: 15 }}>📄</span>
                    <span style={{ flex: 1, minWidth: 0, fontSize: 13, color: INK, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{f.name}</span>
                    <span style={{ fontFamily: MONO, fontSize: 11, color: FAINT }}>{(f.size / 1024).toFixed(0)} KB</span>
                    <button type="button" onClick={() => setFiles((cur) => cur.filter((_, j) => j !== i))} style={{ border: "none", background: "transparent", color: FAINT, fontSize: 15, cursor: "pointer", lineHeight: 1 }}>✕</button>
                  </div>
                ))}
              </div>
            </div>
          )}

          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
            <span style={{ fontSize: 13, color: SOFT }}>{loading ? "Ingesting tender documents…" : files.length ? `${files.length} document${files.length === 1 ? "" : "s"} ready to ingest.` : "Add at least one document to begin."}</span>
            <button type="button" onClick={() => runUpload(files)} disabled={!files.length || loading} style={primaryBtn(!!files.length && !loading)}>Ingest tender →</button>
          </div>
        </>
      )}

      {scope && (
        <>
          {uploadedNames.length > 0 && (
            <div className="ssRise" style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 9, border: `1px solid ${rgba("#2EA56A", 0.3)}`, background: rgba("#2EA56A", 0.06), borderRadius: 12, padding: "11px 15px" }}>
              <span style={{ display: "inline-flex", alignItems: "center", gap: 6, fontFamily: MONO, fontSize: 10.5, fontWeight: 600, letterSpacing: "0.06em", textTransform: "uppercase", color: "#1a8a56" }}><span style={{ fontSize: 13 }}>✓</span> Ingested</span>
              {uploadedNames.map((n) => <span key={n} style={{ display: "inline-flex", alignItems: "center", gap: 5, fontFamily: MONO, fontSize: 11.5, color: INK, background: "#fff", border: "1px solid #e7edf4", borderRadius: 7, padding: "3px 9px" }}>📄 {n}</span>)}
              <span style={{ fontSize: 12, color: SOFT }}>· routed to the GE/2026/14 ground-investigation tender</span>
            </div>
          )}
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
    <button type="button" onClick={(ev) => { ev.stopPropagation(); cite({ source: e.source, reference: e.reference, detail: e.snippet }); }} style={{ display: "inline-flex", alignItems: "center", gap: 8, marginTop: 7, cursor: "pointer", border: `1px solid ${rgba(reg.color, 0.3)}`, background: "#fff", borderRadius: 8, padding: "5px 10px" }}>
      <span style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", minWidth: 16, height: 16, padding: "0 3px", borderRadius: 5, background: reg.color, color: "#fff", fontFamily: MONO, fontSize: 10, fontWeight: 600 }}>{reg.short}</span>
      <span style={{ fontFamily: MONO, fontSize: 11, fontWeight: 600, color: reg.color }}>{reg.short}</span>
      {e.reference && <span style={{ fontFamily: MONO, fontSize: 11, color: FAINT }}>{e.reference}</span>}
      <span style={{ fontSize: 11, color: FAINT }}>→ source</span>
    </button>
  );
}

// Shared "add to dispatch" toggle used on the shortlist card and in the firm modal.
// Quiet outline "Add to dispatch" when not selected; tinted-filled "Added" when in the
// dispatch selection (teal, or a fatal-red caution when the firm is recommend-against).
function DispatchToggle({ selected, flagged, onClick }: { selected: boolean; flagged: boolean; onClick: (e: React.MouseEvent) => void }) {
  const accent = flagged ? "#E5484D" : TEAL;
  const base: React.CSSProperties = { display: "inline-flex", alignItems: "center", gap: 6, borderRadius: 999, padding: "6px 13px", fontFamily: MONO, fontSize: 11.5, fontWeight: 600, letterSpacing: "0.02em", cursor: "pointer", whiteSpace: "nowrap" };
  return (
    <button
      type="button"
      onClick={onClick}
      style={selected
        ? { ...base, background: rgba(accent, 0.13), border: `1px solid ${rgba(accent, 0.5)}`, color: accent }
        : { ...base, background: "#fff", border: `1px solid ${rgba(BLUE, 0.45)}`, color: BLUE }}
    >
      {selected ? (flagged ? "⚠ Added · override" : "✓ Added") : "+ Add to dispatch"}
    </button>
  );
}

// Compact inline dispatch control for a shortlist row — no extra row height. A quiet
// outline "+" when unselected; a filled check when selected (teal, or fatal-red as a
// caution for a recommend-against firm). Stops propagation so it never opens the modal.
function DispatchCheck({ selected, flagged, onClick }: { selected: boolean; flagged: boolean; onClick: (e: React.MouseEvent) => void }) {
  const accent = flagged ? "#E5484D" : TEAL;
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={selected ? "Remove from dispatch" : "Add to dispatch"}
      title={selected ? "In dispatch — click to remove" : "Add to dispatch"}
      style={{
        flexShrink: 0, width: 26, height: 26, borderRadius: "50%", cursor: "pointer", padding: 0,
        display: "inline-flex", alignItems: "center", justifyContent: "center", fontSize: 14, fontWeight: 700, lineHeight: 1,
        border: selected ? `1px solid ${accent}` : `1.5px solid ${rgba(BLUE, 0.4)}`,
        background: selected ? accent : "#fff",
        color: selected ? "#fff" : BLUE,
        transition: "background 0.12s, border-color 0.12s, color 0.12s",
      }}
    >
      {selected ? "✓" : "+"}
    </button>
  );
}

function StepShortlist({ shortlist, heroTrade, covTotal, covFlagged, loading, cite, approvals, toggleApprove, onBack, onNext, onLevel }: {
  shortlist: ShortlistSet; heroTrade: string; covTotal: number; covFlagged: number; loading: boolean; cite: Cite;
  approvals: Record<string, string[]>; toggleApprove: (trade: string, firmId: string) => void;
  onBack: () => void; onNext: () => void; onLevel: () => void;
}) {
  const trades = Object.keys(shortlist.per_trade).sort((a, b) => (a === heroTrade ? -1 : b === heroTrade ? 1 : a.localeCompare(b)));
  const totalCandidates = Object.values(shortlist.per_trade).reduce((n, cs) => n + cs.length, 0);
  const [selectedFirm, setSelectedFirm] = useState<{ id: string; trade: string } | null>(null);
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const approvedIn = (trade: string, firmId: string) => (approvals[trade] ?? []).includes(firmId);

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
      {selectedFirm && <FirmModal firmId={selectedFirm.id} selected={approvedIn(selectedFirm.trade, selectedFirm.id)} flagged={(shortlist.per_trade[selectedFirm.trade] ?? []).find((c) => c.firm.firm_id === selectedFirm.id)?.recommended_against ?? false} onToggle={() => toggleApprove(selectedFirm.trade, selectedFirm.id)} onClose={() => setSelectedFirm(null)} />}
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
        const selIds = approvals[t] ?? [];
        return (
          <div key={t} style={{ background: "#fff", border: `1px solid ${isHero ? rgba("#E5484D", 0.3) : "rgba(15,27,45,0.07)"}`, borderRadius: 16, boxShadow: isHero ? `0 0 0 4px ${rgba("#E5484D", 0.06)}, 0 12px 32px -24px rgba(15,27,45,0.4)` : "0 10px 30px -24px rgba(15,27,45,0.4)" }}>
            {/* section header + selection tray, pinned (below the 64px global header) while scrolling the section */}
            <div style={{ position: "sticky", top: 64, zIndex: 2, background: "#fff", borderRadius: "16px 16px 0 0", borderBottom: "1px solid #eef1f6" }}>
              <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", justifyContent: "space-between", gap: 8, padding: "13px 18px" }}>
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
              <div style={{ display: "flex", alignItems: "center", flexWrap: "wrap", gap: 7, padding: "8px 18px", borderTop: "1px solid #f4f6f9", background: rgba(TEAL, 0.045) }}>
                <span style={{ fontFamily: MONO, fontSize: 10, letterSpacing: "0.06em", textTransform: "uppercase", color: selIds.length ? "#0c8e83" : FAINT, fontWeight: 600 }}>Selected for dispatch ({selIds.length})</span>
                {selIds.length === 0
                  ? <span style={{ fontSize: 11.5, color: FAINT }}>Tap <span style={{ fontFamily: MONO, fontWeight: 700, color: BLUE }}>+</span> to add a firm</span>
                  : selIds.map((id) => {
                      const c = cands.find((x) => x.firm.firm_id === id);
                      const name = c ? c.firm.name : id;
                      const chipAccent = c?.recommended_against ? "#E5484D" : TEAL;
                      return (
                        <span key={id} title={name} style={{ display: "inline-flex", alignItems: "center", gap: 6, maxWidth: 230, background: "#fff", border: `1px solid ${rgba(chipAccent, 0.45)}`, borderRadius: 999, padding: "3px 4px 3px 11px", fontSize: 12 }}>
                          <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: INK, fontWeight: 500 }}>{name}</span>
                          <button type="button" onClick={(e) => { e.stopPropagation(); toggleApprove(t, id); }} aria-label={`Remove ${name} from dispatch`} style={{ flexShrink: 0, width: 17, height: 17, borderRadius: "50%", border: "none", background: rgba(chipAccent, 0.14), color: chipAccent, cursor: "pointer", fontSize: 12, lineHeight: 1, display: "inline-flex", alignItems: "center", justifyContent: "center" }}>×</button>
                        </span>
                      );
                    })}
              </div>
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 3, padding: "7px 9px" }}>
              {cands.map((c, i) => {
                const fatal = c.risk_flags.filter((f) => f.severity === "fatal");
                const warnN = c.risk_flags.filter((f) => f.severity !== "fatal").length;
                const against = c.recommended_against;
                const pct = Math.round(c.match_score * 100);
                const mb = c.match_score >= 0.7 ? "#2EA56A" : c.match_score >= 0.5 ? BLUE : FAINT;
                const isIllustrative = c.firm.firm_id.startsWith("F-");
                const isHov = hoveredId === c.firm.firm_id;
                const meta = [c.firm.registered_grade, c.firm.value_band ? formatBand(c.firm.value_band) : ""].filter(Boolean).join(" · ");
                const selected = approvedIn(t, c.firm.firm_id);
                const accent = against ? "#E5484D" : TEAL;
                return (
                  <div
                    key={c.firm.firm_id}
                    onClick={() => setSelectedFirm({ id: c.firm.firm_id, trade: t })}
                    onMouseEnter={() => setHoveredId(c.firm.firm_id)}
                    onMouseLeave={() => setHoveredId(null)}
                    style={{
                      borderLeft: `3px solid ${selected ? accent : "transparent"}`,
                      background: isHov ? rgba(BLUE, 0.03) : against ? rgba("#E5484D", 0.028) : "transparent",
                      borderRadius: 8, padding: "9px 12px 9px 11px", cursor: "pointer", transition: "background 0.12s",
                    }}
                  >
                    <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                      <span style={{ flex: "none", width: 16, textAlign: "center", fontFamily: MONO, fontSize: 11.5, fontWeight: 600, color: against ? "#E5484D" : FAINT }}>{i + 1}</span>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ display: "flex", alignItems: "center", flexWrap: "wrap", gap: 8 }}>
                          <span style={{ fontFamily: DISPLAY, fontSize: 15, fontWeight: 700, color: INK, lineHeight: 1.25 }}>{c.firm.name}</span>
                          {isIllustrative && <span style={{ background: rgba("#D99513", 0.12), color: "#9a6a08", fontFamily: MONO, fontSize: 9, fontWeight: 600, letterSpacing: "0.05em", textTransform: "uppercase", padding: "1px 6px", borderRadius: 5 }}>Illustrative</span>}
                          {i === 0 && !against && <span style={{ display: "inline-flex", alignItems: "center", gap: 4, background: rgba("#2EA56A", 0.1), color: "#1F8A52", fontSize: 10, fontWeight: 600, padding: "1px 8px", borderRadius: 999 }}>✓ Top pick</span>}
                          {against && <span style={{ display: "inline-flex", alignItems: "center", gap: 4, background: rgba("#E5484D", 0.1), color: "#E5484D", fontSize: 10, fontWeight: 700, padding: "1px 8px", borderRadius: 999, whiteSpace: "nowrap" }}>⛔ Recommend against</span>}
                          {!against && warnN > 0 && <span title="Open profile for the cited caution" style={{ display: "inline-flex", alignItems: "center", gap: 4, background: rgba("#D99513", 0.13), color: "#9a6a08", fontSize: 10, fontWeight: 600, padding: "1px 8px", borderRadius: 999, whiteSpace: "nowrap" }}>⚠ {warnN} caution</span>}
                        </div>
                        {meta && <div style={{ fontSize: 11, color: FAINT, marginTop: 2, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{meta}</div>}
                      </div>
                      <div style={{ display: "flex", alignItems: "center", gap: 7, flexShrink: 0 }}>
                        <span style={{ fontFamily: MONO, fontSize: 8.5, letterSpacing: "0.08em", textTransform: "uppercase", color: FAINT, fontWeight: 600 }}>Match</span>
                        <span style={{ width: 46, height: 5, borderRadius: 3, background: "#EEF2F7", overflow: "hidden" }}><span style={{ display: "block", height: "100%", width: `${pct}%`, background: mb }} /></span>
                        <span style={{ fontFamily: MONO, fontSize: 12, fontWeight: 700, color: mb, fontVariantNumeric: "tabular-nums", minWidth: 32, textAlign: "right" }}>{pct}%</span>
                      </div>
                      <DispatchCheck selected={selected} flagged={against} onClick={(e) => { e.stopPropagation(); toggleApprove(t, c.firm.firm_id); }} />
                    </div>
                    {fatal.length > 0 && (
                      <div style={{ marginTop: 10, marginLeft: 28, border: `1px solid ${rgba("#E5484D", 0.3)}`, background: "linear-gradient(180deg,rgba(229,72,77,0.06),rgba(229,72,77,0.02))", borderRadius: 12, padding: 13 }}>
                        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 9 }}>
                          <span style={{ fontSize: 14 }}>⛔</span>
                          <p style={{ margin: 0, fontFamily: MONO, fontSize: 10, fontWeight: 600, letterSpacing: "0.07em", textTransform: "uppercase", color: "#E5484D" }}>Disqualifying — do not award regardless of price</p>
                        </div>
                        {fatal.map((fl, fi) => <FlagPanel key={fi} flag={fl} sev="fatal" cite={cite} />)}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
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
const modalLabel: React.CSSProperties = { fontFamily: MONO, fontSize: 10.5, letterSpacing: "0.1em", textTransform: "uppercase", color: FAINT, fontWeight: 600, marginBottom: 10 };

function FirmModal({ firmId, selected, flagged, onToggle, onClose }: { firmId: string; selected: boolean; flagged: boolean; onToggle: () => void; onClose: () => void }) {
  const [firm, setFirm] = useState<FirmProfileFull | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    setLoading(true); setErr(null); setFirm(null);
    api.firmById(firmId)
      .then((f) => { if (live) { setFirm(f); setLoading(false); } })
      .catch((e) => { if (live) { setErr(e instanceof Error ? e.message : String(e)); setLoading(false); } });
    return () => { live = false; };
  }, [firmId]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [onClose]);

  const isIllustrative = firm?.provenance === "illustrative";
  const shownEmail = (email: string) =>
    email && email.includes("@") && !email.includes("[email") ? email : null;

  return (
    <>
      <div onClick={onClose} style={{ position: "fixed", inset: 0, background: "rgba(15,27,45,0.55)", backdropFilter: "blur(2px)", zIndex: 1000 }} />
      <div style={{ position: "fixed", top: "50%", left: "50%", transform: "translate(-50%,-50%)", width: "min(720px,94vw)", maxHeight: "88vh", overflowY: "auto", zIndex: 1001, background: "#fff", borderRadius: 20, boxShadow: "0 24px 60px -16px rgba(15,27,45,0.45)" }}>
        {/* sticky header */}
        <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12, padding: "20px 22px 16px", borderBottom: "1px solid #eef1f6", position: "sticky", top: 0, background: "#fff", zIndex: 1 }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            {loading && <div style={{ fontSize: 14, color: FAINT }}>Loading…</div>}
            {!loading && err && <div style={{ fontSize: 14, color: "#E5484D" }}>{err}</div>}
            {!loading && firm && (
              <>
                <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 8, marginBottom: 4 }}>
                  <h2 style={{ margin: 0, fontFamily: DISPLAY, fontSize: 20, fontWeight: 700, color: INK }}>{firm.name_en}</h2>
                  {isIllustrative && <span style={{ background: rgba("#D99513", 0.15), color: "#9a6a08", fontFamily: MONO, fontSize: 10, fontWeight: 600, letterSpacing: "0.06em", textTransform: "uppercase", padding: "3px 8px", borderRadius: 6 }}>Illustrative</span>}
                  {firm.public_flags.length > 0 && <span style={{ background: rgba("#E5484D", 0.1), color: "#E5484D", fontSize: 11, fontWeight: 600, padding: "3px 10px", borderRadius: 999 }}>⚠ Compliance flags</span>}
                </div>
                <div style={{ fontFamily: MONO, fontSize: 11, color: FAINT }}>{[firm.registered_grade, firm.value_band ? formatBand(firm.value_band) : ""].filter(Boolean).join(" · ")}</div>
              </>
            )}
          </div>
          <button type="button" onClick={onClose} style={{ border: "none", background: "transparent", cursor: "pointer", fontSize: 20, color: FAINT, lineHeight: 1, padding: 4, marginTop: -2, flexShrink: 0 }}>✕</button>
        </div>

        {!loading && firm && (
          <div style={{ padding: "18px 22px 26px", display: "flex", flexDirection: "column", gap: 22 }}>
            {/* Illustrative disclaimer */}
            {isIllustrative && (
              <div style={{ border: `1px solid ${rgba("#D99513", 0.3)}`, background: rgba("#D99513", 0.07), borderRadius: 11, padding: "11px 15px", fontSize: 13, color: "#9a6a08", lineHeight: 1.55 }}>
                <strong>Illustrative firm.</strong> This entry is a fictional demo stub, not a real registered subcontractor. It appears in the shortlist to demonstrate how the risk-screening system works.
              </div>
            )}

            {/* Overview — the curated one-liner for known firms (register blurb otherwise) */}
            {(firm.profile.overview || firm.description) && (
              <section>
                <div style={modalLabel}>Overview</div>
                <p style={{ margin: 0, fontSize: 13.5, lineHeight: 1.65, color: SOFT }}>{firm.profile.overview || firm.description}</p>
              </section>
            )}

            {/* What they do — curated services, else the firm's registered CIC specialties */}
            {(firm.profile.services.length > 0 || firm.registered_trades.length > 0) && (
              <section>
                <div style={modalLabel}>What they do</div>
                {firm.profile.services.length > 0 && (
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                    {firm.profile.services.map((s, i) => (
                      <span key={i} style={{ fontSize: 12, color: INK, background: rgba(BLUE, 0.07), border: `1px solid ${rgba(BLUE, 0.16)}`, borderRadius: 7, padding: "4px 10px" }}>{s}</span>
                    ))}
                  </div>
                )}
                {firm.registered_trades.length > 0 && (
                  <>
                    <div style={{ fontSize: 11, color: FAINT, margin: `${firm.profile.services.length > 0 ? 12 : 0}px 0 7px` }}>CIC-registered specialties</div>
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                      {firm.registered_trades.map((rt, i) => (
                        <span key={i} style={{ display: "inline-flex", alignItems: "center", gap: 5, fontSize: 12, color: INK, background: "#EEF2F7", borderRadius: 7, padding: "4px 10px" }}>
                          {rt.code && <span style={{ fontFamily: MONO, fontSize: 10.5, color: FAINT }}>{rt.code}</span>}
                          {rt.specialty || rt.group}
                        </span>
                      ))}
                    </div>
                  </>
                )}
              </section>
            )}

            {/* Track record — curated notable projects, then the cited government awards */}
            {(firm.profile.notable_projects.length > 0 || firm.award_history.length > 0) && (
            <section>
              <div style={modalLabel}>Track record</div>
              {firm.profile.notable_projects.length > 0 && (
                <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: firm.award_history.length > 0 ? 8 : 0 }}>
                  {firm.profile.notable_projects.map((proj, i) => (
                    <div key={i} style={{ display: "flex", alignItems: "flex-start", gap: 10, padding: "10px 13px", border: "1px solid #eef1f6", borderRadius: 10 }}>
                      <span style={{ color: BLUE, fontSize: 13, lineHeight: 1.5, flexShrink: 0 }}>▹</span>
                      <div style={{ flex: 1, minWidth: 0, fontSize: 13, lineHeight: 1.55, color: INK }}>
                        {proj.title}
                        {proj.source && proj.source.startsWith("http") && (
                          <a href={proj.source} target="_blank" rel="noopener noreferrer" style={{ marginLeft: 8, fontSize: 11, color: BLUE, textDecoration: "none", whiteSpace: "nowrap" }}>↗ source</a>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}
              {firm.award_history.length > 0 && (
                <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                  {firm.award_history.map((a, i) => (
                    <div key={i} style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12, padding: "10px 13px", border: "1px solid #eef1f6", borderRadius: 10, background: "#f9fbfc" }}>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontSize: 13, fontWeight: 500, color: INK }}>{a.project}</div>
                        {a.client && <div style={{ fontSize: 12, color: SOFT, marginTop: 2 }}>{a.client}</div>}
                      </div>
                      <div style={{ display: "flex", alignItems: "center", gap: 8, flexShrink: 0 }}>
                        {a.year && <span style={{ fontFamily: MONO, fontSize: 11.5, color: FAINT }}>{a.year}</span>}
                        {a.source && a.source.startsWith("http") && (
                          <a href={a.source} target="_blank" rel="noopener noreferrer" style={{ display: "inline-flex", alignItems: "center", gap: 4, fontSize: 11, color: BLUE, textDecoration: "none", border: `1px solid ${rgba(BLUE, 0.25)}`, borderRadius: 7, padding: "3px 8px" }}>↗ source</a>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </section>
            )}

            {/* Compliance — always shown: cited flags, or a clean-screen statement */}
            <section>
                <div style={modalLabel}>Compliance</div>
                {firm.public_flags.length === 0 && (
                  <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, color: "#1F8A52", background: rgba("#2EA56A", 0.07), border: `1px solid ${rgba("#2EA56A", 0.22)}`, borderRadius: 10, padding: "10px 13px" }}>
                    <span>✓</span> No enforcement records found in the registers checked.
                  </div>
                )}
                {firm.public_flags.length > 0 && isIllustrative && (
                  <div style={{ fontSize: 12, color: "#9a6a08", background: rgba("#D99513", 0.08), border: `1px solid ${rgba("#D99513", 0.2)}`, borderRadius: 8, padding: "7px 11px", marginBottom: 10 }}>
                    The flags below are illustrative example data and are not cited to real government records.
                  </div>
                )}
                {firm.public_flags.length > 0 && (
                <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
                  {firm.public_flags.map((fl, i) => {
                    const isSevere = ["winding_up", "debarment"].includes(fl.signal_type);
                    return (
                      <div key={i} style={{ border: `1px solid ${isSevere ? rgba("#E5484D", 0.3) : rgba("#D99513", 0.3)}`, background: isSevere ? rgba("#E5484D", 0.04) : rgba("#D99513", 0.04), borderRadius: 11, padding: "12px 14px" }}>
                        <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 8, marginBottom: 6 }}>
                          <span style={{ fontFamily: MONO, fontSize: 10, fontWeight: 600, letterSpacing: "0.05em", textTransform: "uppercase", color: isSevere ? "#E5484D" : "#9a6a08", background: isSevere ? rgba("#E5484D", 0.12) : rgba("#D99513", 0.14), padding: "2px 7px", borderRadius: 5 }}>{fl.signal_type.replace(/_/g, " ")}</span>
                          <span style={{ fontSize: 13.5, fontWeight: 600, color: INK }}>{fl.label}</span>
                          {fl.date && <span style={{ fontFamily: MONO, fontSize: 11, color: FAINT }}>{fl.date}</span>}
                        </div>
                        <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 8 }}>
                          {fl.source && <span style={{ fontSize: 12, color: SOFT }}>{fl.source}</span>}
                          {!isIllustrative && fl.reference && fl.reference.startsWith("http") && (
                            <a href={fl.reference} target="_blank" rel="noopener noreferrer" style={{ display: "inline-flex", alignItems: "center", gap: 4, fontSize: 11, color: BLUE, textDecoration: "none", border: `1px solid ${rgba(BLUE, 0.25)}`, borderRadius: 7, padding: "3px 8px" }}>↗ source</a>
                          )}
                          {isIllustrative && <span style={{ fontSize: 11.5, color: FAINT, fontStyle: "italic" }}>not cited to a real government record</span>}
                        </div>
                      </div>
                    );
                  })}
                </div>
                )}
            </section>

            {/* Credentials — accreditations, group/parent, staff, offices (curated firms) */}
            {(firm.profile.accreditations.length > 0 || firm.profile.group_parent || firm.profile.staff_note || firm.profile.offices.length > 0) && (
              <section>
                <div style={modalLabel}>Credentials</div>
                {firm.profile.accreditations.length > 0 && (
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 10 }}>
                    {firm.profile.accreditations.map((a, i) => (
                      <span key={i} style={{ fontSize: 12, color: "#1F8A52", background: rgba("#2EA56A", 0.1), border: `1px solid ${rgba("#2EA56A", 0.22)}`, borderRadius: 7, padding: "4px 10px" }}>{a}</span>
                    ))}
                  </div>
                )}
                <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                  {firm.profile.group_parent && <div style={{ fontSize: 13, color: SOFT }}><span style={{ color: FAINT }}>Group / parent: </span>{firm.profile.group_parent}</div>}
                  {firm.profile.staff_note && <div style={{ fontSize: 13, color: SOFT }}><span style={{ color: FAINT }}>Staff: </span>{firm.profile.staff_note}</div>}
                  {firm.profile.offices.length > 0 && <div style={{ fontSize: 13, color: SOFT }}><span style={{ color: FAINT }}>Offices: </span>{firm.profile.offices.join(" · ")}</div>}
                </div>
              </section>
            )}

            {/* Registration */}
            <section>
              <div style={modalLabel}>Registration</div>
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {firm.registers.length > 0 ? (
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                    {firm.registers.map((r, i) => (
                      <span key={i} style={{ fontSize: 12, color: INK, background: rgba(BLUE, 0.08), borderRadius: 7, padding: "4px 10px" }}>{r}</span>
                    ))}
                  </div>
                ) : (
                  <span style={{ fontSize: 13, color: FAINT, fontStyle: "italic" }}>No register entries.</span>
                )}
                {firm.value_band && (
                  <div style={{ fontSize: 13, color: SOFT }}><span style={{ color: FAINT }}>Value band: </span>{formatBand(firm.value_band)}</div>
                )}
                {firm.reg_date && (
                  <div style={{ fontSize: 13, color: SOFT }}>
                    <span style={{ color: FAINT }}>Registered: </span>{firm.reg_date}
                    {firm.expiry_date && <span style={{ marginLeft: 14 }}><span style={{ color: FAINT }}>Expires: </span>{firm.expiry_date}</span>}
                  </div>
                )}
                {shownEmail(firm.enquiry_email) && (
                  <div style={{ fontSize: 13, color: SOFT }}>
                    <span style={{ color: FAINT }}>Enquiry: </span>
                    <a href={`mailto:${shownEmail(firm.enquiry_email)!}`} style={{ color: BLUE, textDecoration: "none" }}>{shownEmail(firm.enquiry_email)}</a>
                  </div>
                )}
              </div>
            </section>
          </div>
        )}
        {!loading && firm && (
          <div style={{ position: "sticky", bottom: 0, display: "flex", alignItems: "center", justifyContent: "flex-end", gap: 12, padding: "14px 22px", borderTop: "1px solid #eef1f6", background: "#fff", borderRadius: "0 0 20px 20px" }}>
            <span style={{ fontSize: 12, color: FAINT }}>{selected ? "Selected for dispatch" : "Interested?"}</span>
            <DispatchToggle selected={selected} flagged={flagged} onClick={onToggle} />
          </div>
        )}
      </div>
    </>
  );
}

// ----------------------------------------------------------------------------
function sendingSteps(d: DispatchSet): string[] {
  const firms = Array.from(new Set(d.bundles.map((b) => b.firm_name)));
  return ["Composing enquiry emails", "Attaching each firm's trade document bundle", ...firms.map((f) => `Sent → ${f}`), "Mock outbox updated"];
}

function collectingSteps(n: number): string[] {
  return ["Fetching replies from the mock outbox", "Reading the returned Schedules of Rates (PDF)", `Extracting priced line items from ${n} repl${n === 1 ? "y" : "ies"}`, "Flagging arithmetic errors and scope gaps", "Normalising every bid onto one scope basis"];
}

function ProcessingOverlay({ kind, steps, onDone }: { kind: "sending" | "collecting"; steps: string[]; onDone: () => void }) {
  const [done, setDone] = useState(0);
  useEffect(() => {
    const timers: number[] = [];
    let i = 0;
    const tick = () => {
      i += 1;
      setDone(i);
      timers.push(window.setTimeout(i < steps.length ? tick : onDone, i < steps.length ? 600 : 720));
    };
    timers.push(window.setTimeout(tick, 460));
    return () => timers.forEach((t) => clearTimeout(t));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const sending = kind === "sending";
  const accent = sending ? "#2EA56A" : BLUE;
  const title = sending ? "Dispatching enquiries" : "Reading replies & leveling";
  const sub = sending
    ? "Composing each firm's bundle and writing it to the mock outbox."
    : "The agent reads the returned Schedules of Rates and prepares the like-for-like comparison.";
  return (
    <div className="ssRise" style={{ ...cardSx, overflow: "hidden", maxWidth: 560, margin: "7vh auto 0" }}>
      <div style={{ position: "relative", padding: "22px 24px", borderBottom: "1px solid #eef1f6", overflow: "hidden" }}>
        <div className="ssScan" style={{ background: `linear-gradient(90deg, transparent, ${rgba(accent, 0.18)}, transparent)` }} />
        {kicker(sending ? "Dispatch" : "Level")}
        <h2 style={{ margin: 0, fontFamily: DISPLAY, fontSize: 21, fontWeight: 700, color: INK }}>{title}</h2>
        <p style={{ margin: "6px 0 0", fontSize: 13, color: SOFT, lineHeight: 1.55 }}>{sub}</p>
      </div>
      <ul style={{ margin: 0, padding: "10px 0 14px", listStyle: "none" }}>
        {steps.map((label, idx) => {
          const state = idx < done ? "done" : idx === done ? "active" : "pending";
          return (
            <li key={idx} className={state === "pending" ? undefined : "ssStep"} style={{ display: "flex", alignItems: "center", gap: 11, padding: "9px 24px", opacity: state === "pending" ? 0.32 : 1 }}>
              <span style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", width: 20, height: 20, flex: "none", borderRadius: "50%", border: `1.5px solid ${state === "done" ? accent : "rgba(15,27,45,0.2)"}`, background: state === "done" ? accent : "#fff", color: "#fff", fontSize: 11 }}>
                {state === "done" ? "✓" : state === "active" ? <span className="ssDot" style={{ width: 6, height: 6, borderRadius: "50%", background: accent }} /> : null}
              </span>
              <span style={{ fontSize: 13.5, color: state === "done" ? INK : SOFT, fontWeight: state === "active" ? 600 : 400 }}>{label}</span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function StepDispatch({ shortlist, approvals, dispatch, dispatchSent, loading, toggleApprove, prepareDispatch, editBundle, confirmSend, onBack, onNext }: {
  shortlist: ShortlistSet; approvals: Record<string, string[]>; dispatch: DispatchSet | null; dispatchSent: boolean; loading: boolean;
  toggleApprove: (t: string, id: string) => void; prepareDispatch: () => void;
  editBundle: (firmId: string, trade: string, patch: Partial<{ email_subject: string; email_body: string }>) => void;
  confirmSend: () => void; onBack: () => void; onNext: () => void;
}) {
  const trades = Object.keys(shortlist.per_trade);
  const approved = Object.values(approvals).reduce((n, ids) => n + ids.length, 0);
  const drafting = !!dispatch && !dispatchSent;
  // n8n created the Gmail drafts (webhook configured); otherwise it's the mock outbox.
  const gmail = !drafting && !!dispatch?.bundles.some((b) => b.status === "drafted_gmail");
  const labelSx: React.CSSProperties = { display: "block", fontFamily: MONO, fontSize: 10, letterSpacing: "0.06em", textTransform: "uppercase", color: FAINT, marginBottom: 4 };
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      <div>
        {kicker("Step 03 · Dispatch")}
        <h1 style={h1Sx}>Dispatch document bundles</h1>
        <p style={leadSx}>Approve which firms to invite (the human gate). Each firm receives only its trade's documents and a composed enquiry email — review and edit any email before it goes to the mock outbox.</p>
      </div>

      {!dispatch && trades.map((t) => (
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

      {!dispatch && (
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
          <span style={{ fontSize: 13.5, color: SOFT }}>{approved} firm{approved === 1 ? "" : "s"} approved.</span>
          <button type="button" onClick={prepareDispatch} disabled={approved === 0 || loading} style={primaryBtn(approved > 0)}>Prepare enquiry emails →</button>
        </div>
      )}

      {dispatch && (
        <div className="ssRise" style={{ ...cardSx, overflow: "hidden" }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "14px 19px", borderBottom: "1px solid #eef1f6", background: drafting ? "linear-gradient(90deg,rgba(31,111,235,0.07),transparent)" : gmail ? "linear-gradient(90deg,rgba(15,181,166,0.10),transparent)" : "linear-gradient(90deg,rgba(46,165,106,0.08),transparent)" }}>
            <h2 style={{ margin: 0, fontSize: 14.5, fontWeight: 600, color: INK }}>{drafting ? "Draft enquiries — review & edit" : gmail ? "Drafts created in Gmail ✓" : "Mock outbox"}</h2>
            <span style={{ background: drafting ? rgba(BLUE, 0.12) : gmail ? rgba(TEAL, 0.14) : rgba("#2EA56A", 0.12), color: drafting ? BLUE : gmail ? TEAL : "#2EA56A", fontSize: 11, fontWeight: 600, padding: "4px 11px", borderRadius: 999 }}>{dispatch.bundles.length} {drafting ? "drafted" : gmail ? "in Gmail" : "sent"}</span>
          </div>
          <ul style={{ margin: 0, padding: 0, listStyle: "none" }}>
            {dispatch.bundles.map((b) => (
              <li key={`${b.trade}-${b.firm_id}`} style={{ padding: "16px 19px", borderBottom: "1px solid #eef1f6" }}>
                <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 9 }}>
                  <span style={{ fontSize: 14, fontWeight: 600, color: INK }}>{b.firm_name}</span>
                  <span style={{ fontFamily: MONO, fontSize: 11, color: FAINT }}>{b.firm_id}</span>
                  <span style={{ background: rgba(BLUE, 0.1), color: BLUE, fontSize: 11, fontWeight: 500, padding: "3px 9px", borderRadius: 999 }}>{tradeLabel(b.trade)}</span>
                  <span style={{ marginLeft: "auto", background: drafting ? rgba("#8a98ab", 0.16) : b.status === "drafted_gmail" ? rgba(TEAL, 0.14) : rgba("#2EA56A", 0.12), color: drafting ? SOFT : b.status === "drafted_gmail" ? TEAL : "#2EA56A", fontSize: 11, fontWeight: 600, padding: "3px 11px", borderRadius: 999 }}>{drafting ? "Draft" : b.status === "drafted_gmail" ? "Draft in Gmail" : "Sent (mock)"}</span>
                </div>
                <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 7, marginTop: 11 }}>
                  <span style={{ fontSize: 12, fontWeight: 500, color: SOFT }}>Enclosed:</span>
                  {b.bundle_doc_refs.map((d) => <span key={d} style={{ fontFamily: MONO, fontSize: 11, color: SOFT, background: "#EEF2F7", borderRadius: 6, padding: "2px 8px" }}>{d}</span>)}
                </div>
                {drafting ? (
                  <div style={{ marginTop: 11, border: "1px solid #e4e9f0", background: "#fff", borderRadius: 10, padding: "12px 14px" }}>
                    <label style={labelSx}>Subject</label>
                    <input value={b.email_subject} onChange={(e) => editBundle(b.firm_id, b.trade, { email_subject: e.target.value })} style={{ width: "100%", border: "1px solid rgba(15,27,45,0.12)", borderRadius: 8, padding: "8px 10px", fontSize: 12.5, fontWeight: 600, color: INK, outline: "none", boxSizing: "border-box" }} />
                    <label style={{ ...labelSx, margin: "10px 0 4px" }}>Body</label>
                    <textarea value={b.email_body} onChange={(e) => editBundle(b.firm_id, b.trade, { email_body: e.target.value })} rows={6} style={{ width: "100%", border: "1px solid rgba(15,27,45,0.12)", borderRadius: 8, padding: "9px 11px", fontSize: 12, lineHeight: 1.6, color: SOFT, outline: "none", resize: "vertical", boxSizing: "border-box", fontFamily: "inherit" }} />
                  </div>
                ) : (
                  <div style={{ marginTop: 11, border: "1px solid #eef1f6", background: "#f6f9fc", borderRadius: 10, padding: "13px 15px" }}>
                    <div style={{ fontSize: 12.5, fontWeight: 600, color: INK }}>{b.email_subject}</div>
                    <p style={{ margin: "6px 0 0", whiteSpace: "pre-line", fontSize: 12, lineHeight: 1.6, color: SOFT }}>{b.email_body}</p>
                  </div>
                )}
              </li>
            ))}
          </ul>
          {drafting && (
            <div style={{ display: "flex", alignItems: "center", justifyContent: "flex-end", gap: 12, padding: "14px 19px", borderTop: "1px solid #eef1f6" }}>
              <button type="button" onClick={confirmSend} disabled={loading} style={primaryBtn(true)}>Send to approved firms (mock) →</button>
            </div>
          )}
        </div>
      )}

      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, paddingTop: 4 }}>
        <button type="button" onClick={onBack} style={ghostBtn}>← Back</button>
        <button type="button" onClick={onNext} disabled={!dispatchSent || loading} style={primaryBtn(dispatchSent)}>Level the bids →</button>
      </div>
    </div>
  );
}

// ----------------------------------------------------------------------------
function CalloutCol({ title, color, children }: { title: string; color: string; children: React.ReactNode }) {
  const items = Array.isArray(children) ? children.flat() : children;
  const empty = !items || (Array.isArray(items) && items.length === 0);
  return (
    <div style={{ ...cardSx, padding: "14px 16px" }}>
      <div style={{ fontFamily: MONO, fontSize: 10.5, letterSpacing: "0.1em", textTransform: "uppercase", color, fontWeight: 600, marginBottom: 6 }}>{title}</div>
      {empty
        ? <div style={{ fontSize: 12, color: FAINT, padding: "6px 0" }}>None</div>
        : <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>{items}</ul>}
    </div>
  );
}

// ----------------------------------------------------------------------------
// The tender's own Schedule of Rates rides in the levelled set as a baseline "bid"
// under this id — always shown first and styled as a benchmark, never a tenderer.
const BENCHMARK_FIRM_ID = "tender-scheduled-rates";
// Honesty scoping for the drainage demo: the named real bidders whose columns carry
// their true submitted rates. Every other tenderer in a benchmarked section is
// representative; field testing returned no subcontractor SoR, so it is illustrative.
const REAL_BID_FIRM_IDS = new Set([
  "kai-wai-engineering-survey-and-geophysics-limited-3f7b",
  "sixense-limited-5d2c",
]);
const ILLUSTRATIVE_TRADES = new Set(["field_testing"]);

function StepLevel({ levelled, replies, heroTrade, levelStale, loading, editRate, recompute, onBack, onNext }: {
  levelled: LevelledBid[]; replies: BidReply[]; heroTrade: string; levelStale: boolean; loading: boolean;
  editRate: (firmId: string, ref: string, rate: number | null) => void; recompute: () => void; onBack: () => void; onNext: () => void;
}) {
  const tradesOrder = Array.from(new Set(levelled.map((b) => b.trade))).sort((a, b) => (a === heroTrade ? -1 : b === heroTrade ? 1 : a.localeCompare(b)));
  const nameOf = new Map(levelled.map((b) => [b.firm_id, b.firm_name]));
  const stickyCol: React.CSSProperties = { position: "sticky", left: 0, zIndex: 1 };

  const chipFor = (firmId: string, isBench: boolean, hasBench: boolean, trade: string): { label: string; bg: string; fg: string } | null => {
    if (isBench) return { label: "Benchmark", bg: rgba(BLUE, 0.12), fg: BLUE };
    if (!hasBench) return null;
    if (ILLUSTRATIVE_TRADES.has(trade)) return { label: "Illustrative", bg: rgba("#D99513", 0.16), fg: "#B7791F" };
    if (REAL_BID_FIRM_IDS.has(firmId)) return { label: "Submitted rates", bg: rgba("#2EA56A", 0.14), fg: "#1F8A52" };
    return { label: "Representative", bg: rgba("#6E56CF", 0.14), fg: "#6E56CF" };
  };
  const captionFor = (hasBench: boolean, trade: string): string | null => {
    if (!hasBench) return null;
    return ILLUSTRATIVE_TRADES.has(trade)
      ? "No subcontractor schedule of rates was returned for this package, so these bid figures are illustrative. The benchmark column is the tender's own scheduled rates (real)."
      : "The named firm's column is its real submitted rates; the competitor column is representative. The benchmark column is the tender's own scheduled rates.";
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 22 }}>
      <div>
        {kicker("Step 04 · Level")}
        <h1 style={h1Sx}>Level the bids on a like-for-like basis</h1>
        <p style={leadSx}>The rules engine recomputes every amount as qty × rate, flags arithmetic errors, treats a missing rate or provisional sum as a scope gap, and keeps exclusions non-comparable. Each work section is leveled separately against the tender's own scheduled rates. Edit a rate and recompute to see the ranking move.</p>
      </div>

      {tradesOrder.map((trade) => {
        const bids = levelled.filter((b) => b.trade === trade);
        const reps = replies.filter((r) => r.trade === trade);
        const benchRep = reps.find((r) => r.firm_id === BENCHMARK_FIRM_ID) ?? null;
        const hasBench = benchRep != null;
        const otherReps = reps.filter((r) => r.firm_id !== BENCHMARK_FIRM_ID);
        const colReps = hasBench ? [benchRep as BidReply, ...otherReps] : otherReps;

        const tenderBids = bids.filter((b) => b.firm_id !== BENCHMARK_FIRM_ID);
        const benchBid = bids.find((b) => b.firm_id === BENCHMARK_FIRM_ID) ?? null;
        const claimedOf = new Map(reps.map((r) => [r.firm_id, r.claimed_total ?? 0]));
        const correctedOf = new Map(bids.map((b) => [b.firm_id, b.corrected_total]));
        const normalizedOf = new Map(bids.map((b) => [b.firm_id, b.normalized_total]));
        const lowestNorm = tenderBids.length ? Math.min(...tenderBids.map((b) => b.normalized_total)) : 0;
        const lowestCorr = tenderBids.length ? Math.min(...tenderBids.map((b) => b.corrected_total)) : 0;
        const ranked = [...tenderBids].sort((a, b) => a.normalized_total - b.normalized_total);

        const itemSource = benchRep ?? [...reps].sort((a, b) => b.line_items.length - a.line_items.length)[0];
        const items = itemSource?.line_items.map((l) => ({ ref: l.item_ref, desc: l.description, unit: l.unit, qty: l.qty })) ?? [];
        const line = (fid: string, ref: string) => reps.find((r) => r.firm_id === fid)?.line_items.find((l) => l.item_ref === ref);
        const isHero = trade === heroTrade;
        const caption = captionFor(hasBench, trade);

        const bb = "1px solid #eef1f6";
        const ITEMW = 250, BENCHW = 152, FIRMW = 168;
        const minW = ITEMW + (hasBench ? BENCHW : 0) + otherReps.length * FIRMW + 14;
        const benchEdge = `1px solid ${rgba(BLUE, 0.18)}`;
        const benchTint = rgba(BLUE, 0.05);
        const headTh: React.CSSProperties = { padding: "9px 16px", fontFamily: MONO, fontSize: 10, fontWeight: 600, letterSpacing: "0.07em", textTransform: "uppercase", color: FAINT };

        return (
          <section key={trade} style={{ ...cardSx, padding: 18, display: "flex", flexDirection: "column", gap: 15 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <span style={{ width: 11, height: 11, borderRadius: "50%", background: tradeColor(trade) }} />
              <h2 style={{ margin: 0, fontFamily: DISPLAY, fontSize: 18, fontWeight: 700, color: INK }}>{tradeLabel(trade)}</h2>
              {isHero && <span style={{ background: rgba(BLUE, 0.1), color: BLUE, fontFamily: MONO, fontSize: 10, fontWeight: 600, letterSpacing: "0.06em", textTransform: "uppercase", padding: "3px 9px", borderRadius: 999 }}>Hero scope</span>}
              <span style={{ marginLeft: "auto", fontFamily: MONO, fontSize: 11.5, color: FAINT }}>{tenderBids.length} bid{tenderBids.length === 1 ? "" : "s"}{hasBench ? " + benchmark" : ""}</span>
            </div>

            {caption && <p style={{ margin: 0, fontSize: 12, lineHeight: 1.55, color: FAINT, maxWidth: 780 }}>{caption}</p>}

            <div style={{ border: bb, borderRadius: 12, overflow: "hidden" }}>
              <table style={{ width: "100%", borderCollapse: "collapse" }}>
                <thead>
                  <tr style={{ borderBottom: bb, background: "#fbfcfe" }}>
                    <th style={{ ...headTh, textAlign: "left" }}>Firm</th>
                    <th style={{ ...headTh, textAlign: "right" }}>Claimed</th>
                    <th style={{ ...headTh, textAlign: "right" }}>Corrected</th>
                    <th style={{ ...headTh, textAlign: "right" }}>Normalised</th>
                    <th style={{ ...headTh, textAlign: "left" }}>Notes</th>
                  </tr>
                </thead>
                <tbody>
                  {ranked.map((b) => {
                    const claimed = claimedOf.get(b.firm_id) ?? 0, delta = b.corrected_total - claimed;
                    const isWinner = Math.abs(b.normalized_total - lowestNorm) < 0.5;
                    const flip = !isWinner && Math.abs(b.corrected_total - lowestCorr) < 0.5;
                    return (
                      <tr key={b.firm_id} style={{ borderBottom: bb, background: isWinner ? rgba("#2EA56A", 0.06) : "transparent" }}>
                        <td style={{ padding: "12px 16px" }}><span style={{ fontSize: 13.5, fontWeight: 600, color: INK }}>{b.firm_name}</span></td>
                        <td style={{ padding: "12px 16px", textAlign: "right", fontFamily: MONO, fontVariantNumeric: "tabular-nums", fontSize: 12.5, color: SOFT }}>{hkd(claimed)}</td>
                        <td style={{ padding: "12px 16px", textAlign: "right", fontFamily: MONO, fontVariantNumeric: "tabular-nums", fontSize: 12.5, fontWeight: 600, color: INK }}>{hkd(b.corrected_total)}{Math.abs(delta) > 0.5 && <span style={{ color: "#E5484D", fontWeight: 500 }}>  ({delta > 0 ? "+" : ""}{hkd(delta)})</span>}</td>
                        <td style={{ padding: "12px 16px", textAlign: "right", fontFamily: MONO, fontVariantNumeric: "tabular-nums", fontSize: 13, fontWeight: isWinner ? 700 : 600, color: isWinner ? "#1F8A52" : INK }}>{hkd(b.normalized_total)}</td>
                        <td style={{ padding: "12px 16px" }}>
                          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                            {isWinner && <span style={{ background: rgba("#2EA56A", 0.12), color: "#1F8A52", fontSize: 11, fontWeight: 600, padding: "2px 9px", borderRadius: 999 }}>Lowest like-for-like</span>}
                            {flip && <span style={{ background: rgba("#D99513", 0.14), color: "#B7791F", fontSize: 11, fontWeight: 600, padding: "2px 9px", borderRadius: 999 }}>Lowest before normalisation</span>}
                            {b.arithmetic_findings.length > 0 && <span style={{ background: rgba("#E5484D", 0.1), color: "#E5484D", fontSize: 11, fontWeight: 500, padding: "2px 9px", borderRadius: 999 }}>{b.arithmetic_findings.length} corrected</span>}
                            {b.scope_gaps.length > 0 && <span style={{ background: rgba(BLUE, 0.1), color: BLUE, fontSize: 11, fontWeight: 500, padding: "2px 9px", borderRadius: 999 }}>{b.scope_gaps.length} scope gap</span>}
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                  {hasBench && benchBid && (
                    <tr style={{ background: benchTint }}>
                      <td style={{ padding: "12px 16px" }}><span style={{ fontSize: 13.5, fontWeight: 600, color: BLUE }}>Tender scheduled rates</span><span style={{ marginLeft: 8, background: rgba(BLUE, 0.12), color: BLUE, fontFamily: MONO, fontSize: 9.5, fontWeight: 600, letterSpacing: "0.04em", textTransform: "uppercase", padding: "2px 7px", borderRadius: 999 }}>Benchmark</span></td>
                      <td style={{ padding: "12px 16px", textAlign: "right", fontFamily: MONO, fontVariantNumeric: "tabular-nums", fontSize: 12.5, color: SOFT }}>{hkd(claimedOf.get(BENCHMARK_FIRM_ID) ?? 0)}</td>
                      <td style={{ padding: "12px 16px", textAlign: "right", fontFamily: MONO, fontVariantNumeric: "tabular-nums", fontSize: 12.5, fontWeight: 600, color: INK }}>{hkd(benchBid.corrected_total)}</td>
                      <td style={{ padding: "12px 16px", textAlign: "right", fontFamily: MONO, fontVariantNumeric: "tabular-nums", fontSize: 13, fontWeight: 600, color: INK }}>{hkd(benchBid.normalized_total)}</td>
                      <td style={{ padding: "12px 16px", fontSize: 11.5, color: FAINT }}>Tender Schedule of Rates — baseline, not a tenderer</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>

            <div className="ssx" style={{ border: bb, borderRadius: 12, overflowX: "auto" }}>
              <table style={{ width: "100%", minWidth: minW, borderCollapse: "separate", borderSpacing: 0 }}>
                <colgroup>
                  <col style={{ width: ITEMW }} />
                  {colReps.map((r) => <col key={r.firm_id} style={{ width: r.firm_id === BENCHMARK_FIRM_ID ? BENCHW : FIRMW }} />)}
                </colgroup>
                <thead>
                  <tr>
                    <th style={{ ...stickyCol, zIndex: 2, background: "#fbfcfe", textAlign: "left", verticalAlign: "bottom", padding: "10px 16px", borderBottom: bb, borderRight: bb, fontFamily: MONO, fontSize: 10, fontWeight: 600, letterSpacing: "0.07em", textTransform: "uppercase", color: FAINT }}>Rates by item</th>
                    {colReps.map((r) => {
                      const isBench = r.firm_id === BENCHMARK_FIRM_ID;
                      const chip = chipFor(r.firm_id, isBench, hasBench, trade);
                      const label = isBench ? "Tender scheduled rates" : (nameOf.get(r.firm_id) ?? r.firm_id);
                      return (
                        <th key={r.firm_id} style={{ verticalAlign: "bottom", textAlign: "right", padding: "10px 14px", borderBottom: bb, background: isBench ? benchTint : "#fbfcfe", borderLeft: isBench ? benchEdge : undefined, borderRight: isBench ? benchEdge : undefined }}>
                          <div title={label} style={{ display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden", minHeight: 32, fontFamily: DISPLAY, fontSize: 12.5, fontWeight: 600, lineHeight: 1.28, color: isBench ? BLUE : INK }}>{label}</div>
                          {chip && <span style={{ display: "inline-block", marginTop: 5, background: chip.bg, color: chip.fg, fontFamily: MONO, fontSize: 9.5, fontWeight: 600, letterSpacing: "0.04em", textTransform: "uppercase", padding: "2px 7px", borderRadius: 999 }}>{chip.label}</span>}
                        </th>
                      );
                    })}
                  </tr>
                </thead>
                <tbody>
                  {items.map(({ ref, desc, unit, qty }) => {
                    const benchLine = hasBench ? line(BENCHMARK_FIRM_ID, ref) : undefined;
                    const benchRate = benchLine?.rate ?? null;
                    return (
                      <tr key={ref}>
                        <td style={{ ...stickyCol, background: "#fff", verticalAlign: "top", padding: "10px 16px", borderBottom: bb, borderRight: bb }}>
                          <div style={{ fontFamily: MONO, fontSize: 11.5, fontWeight: 600, color: INK }}>{ref}</div>
                          <div style={{ fontSize: 11.5, color: FAINT, marginTop: 2, lineHeight: 1.4 }}>{desc}</div>
                          <div style={{ fontFamily: MONO, fontSize: 10, color: FAINT, marginTop: 3 }}>{unit} · qty {qty.toLocaleString("en-US")}</div>
                        </td>
                        {colReps.map((r) => {
                          const isBench = r.firm_id === BENCHMARK_FIRM_ID;
                          const l = line(r.firm_id, ref);
                          const missing = l == null;
                          const gap = l != null && l.rate == null;
                          const amt = l && l.rate != null ? l.qty * l.rate : null;
                          const above = !isBench && l?.rate != null && benchRate != null && l.rate > benchRate;
                          const cellBg = isBench ? benchTint : gap ? rgba("#D99513", 0.06) : "transparent";
                          return (
                            <td key={r.firm_id} style={{ textAlign: "right", verticalAlign: "top", padding: "9px 14px", borderBottom: bb, background: cellBg, borderLeft: isBench ? benchEdge : undefined, borderRight: isBench ? benchEdge : undefined }}>
                              {isBench ? (
                                <div style={{ fontFamily: MONO, fontVariantNumeric: "tabular-nums", fontSize: 12.5, fontWeight: 600, color: INK }}>{benchRate != null ? hkd(benchRate) : "—"}</div>
                              ) : missing ? (
                                <div style={{ fontFamily: MONO, fontSize: 12, color: FAINT }}>—</div>
                              ) : (
                                <input type="number" placeholder={gap ? "—" : ""} value={l?.rate ?? ""} onChange={(e) => editRate(r.firm_id, ref, e.target.value === "" ? null : Number(e.target.value))} style={{ width: "100%", maxWidth: 124, border: `1px solid ${gap ? rgba("#D99513", 0.55) : above ? rgba("#E5484D", 0.5) : "rgba(15,27,45,0.12)"}`, borderRadius: 8, background: gap ? rgba("#D99513", 0.06) : above ? rgba("#E5484D", 0.05) : "#fff", padding: "6px 8px", textAlign: "right", fontFamily: MONO, fontVariantNumeric: "tabular-nums", fontSize: 12, color: INK, outline: "none" }} />
                              )}
                              <div style={{ fontFamily: MONO, fontSize: 10, marginTop: 3, fontWeight: gap ? 600 : 400, color: gap ? "#B7791F" : above ? "#E5484D" : FAINT }}>{isBench ? (benchLine && benchLine.rate != null ? hkd(benchLine.qty * benchLine.rate) : "—") : gap ? "scope gap" : missing ? "" : amt != null ? hkd(amt) : ""}{above ? " · above SR" : ""}</div>
                            </td>
                          );
                        })}
                      </tr>
                    );
                  })}
                  {([["Corrected total", correctedOf, false], ["Normalised total (like-for-like)", normalizedOf, true]] as [string, Map<string, number>, boolean][]).map(([label, map, isNorm]) => (
                    <tr key={label}>
                      <td style={{ ...stickyCol, background: "#f6f9fc", padding: "11px 16px", borderTop: isNorm ? bb : "2px solid rgba(15,27,45,0.12)", borderRight: bb, fontFamily: MONO, fontSize: 10, fontWeight: 600, letterSpacing: "0.05em", textTransform: "uppercase", color: SOFT }}>{label}</td>
                      {colReps.map((r) => {
                        const isBench = r.firm_id === BENCHMARK_FIRM_ID;
                        const v = map.get(r.firm_id) ?? 0;
                        const isWinner = !isBench && isNorm && Math.abs(v - lowestNorm) < 0.5;
                        return (
                          <td key={r.firm_id} style={{ textAlign: "right", padding: "11px 14px", borderTop: isNorm ? bb : "2px solid rgba(15,27,45,0.12)", background: isBench ? rgba(BLUE, 0.08) : isWinner ? rgba("#2EA56A", 0.12) : "#f6f9fc", borderLeft: isBench ? benchEdge : undefined, borderRight: isBench ? benchEdge : undefined, fontFamily: MONO, fontVariantNumeric: "tabular-nums", fontSize: 13, fontWeight: 700, color: isBench ? BLUE : isWinner ? "#1F8A52" : INK }}>{hkd(v)}</td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        );
      })}

      {levelStale && (
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, border: `1px solid ${rgba("#D99513", 0.35)}`, background: rgba("#D99513", 0.08), borderRadius: 12, padding: "13px 17px" }}>
          <span style={{ fontSize: 13.5, color: INK }}>⚠ A rate changed — the corrected totals are stale.</span>
          <button type="button" onClick={recompute} style={{ background: BLUE, border: "none", color: "#fff", borderRadius: 9, padding: "8px 16px", fontSize: 13.5, fontWeight: 600, cursor: "pointer" }}>Recompute</button>
        </div>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 14 }}>
        <CalloutCol title="Arithmetic corrections" color="#E5484D">
          {levelled.flatMap((b) => b.arithmetic_findings.map((f, i) => (
            <li key={`${b.firm_id}-${b.trade}-${i}`} style={{ padding: "8px 0", borderBottom: "1px solid #f3f5f9" }}>
              <span style={{ fontSize: 12.5, fontWeight: 600, color: INK }}>{nameOf.get(b.firm_id)}</span> <span style={{ fontFamily: MONO, fontSize: 11, color: FAINT }}>· {f.location}</span>
              <div style={{ fontSize: 11.5, color: SOFT, lineHeight: 1.5, marginTop: 2 }}>{f.issue} → {hkd(f.corrected_value)}</div>
            </li>
          )))}
        </CalloutCol>
        <CalloutCol title="Scope gaps" color={BLUE}>
          {levelled.flatMap((b) => b.scope_gaps.map((g, i) => (
            <li key={`${b.firm_id}-${b.trade}-${i}`} style={{ padding: "8px 0", borderBottom: "1px solid #f3f5f9" }}>
              <span style={{ fontSize: 12.5, fontWeight: 600, color: INK }}>{nameOf.get(b.firm_id)}</span>
              <div style={{ fontSize: 11.5, color: SOFT, lineHeight: 1.5, marginTop: 2 }}>{g}</div>
            </li>
          )))}
        </CalloutCol>
        <CalloutCol title="Exclusions" color="#6E56CF">
          {levelled.flatMap((b) => b.exclusions.map((x, i) => (
            <li key={`${b.firm_id}-${b.trade}-${i}`} style={{ padding: "8px 0", borderBottom: "1px solid #f3f5f9" }}>
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

function StepRecommend({ recommendations, awards, heroTrade, barReveal, cite, setAward, onBack, onReset }: {
  recommendations: Recommendation[]; awards: Record<string, string | null>; heroTrade: string; barReveal: boolean; cite: Cite;
  setAward: (trade: string, id: string) => void; onBack: () => void; onReset: () => void;
}) {
  const multi = recommendations.length > 1;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 26 }}>
      <div>
        {kicker("Step 05 · Recommend")}
        <h1 style={h1Sx}>The risk-adjusted recommendation{multi ? " · per work section" : ""}</h1>
        <p style={leadSx}>The engine ranks each section by corrected price but reads every firm against the database — a firm with a fatal flag is recommended against regardless of price. Where a tender benchmark is shown it is the scheduled-rate baseline, not a competing bid. The rationale is narrated; the engine never chooses the winner.</p>
      </div>
      {recommendations.map((rec) => (
        <RecommendSection key={rec.trade} rec={rec} isHero={rec.trade === heroTrade} multi={multi} award={awards[rec.trade] ?? null} onAward={(id) => setAward(rec.trade, id)} barReveal={barReveal} cite={cite} />
      ))}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, paddingTop: 4 }}>
        <button type="button" onClick={onBack} style={ghostBtn}>← Back</button>
        <button type="button" onClick={onReset} style={ghostBtn}>Start over</button>
      </div>
    </div>
  );
}

function RecommendSection({ rec, isHero, multi, award, onAward, barReveal, cite }: {
  rec: Recommendation; isHero: boolean; multi: boolean; award: string | null; onAward: (id: string) => void; barReveal: boolean; cite: Cite;
}) {
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
  const sectionWrap: React.CSSProperties = multi ? { border: "1px solid rgba(15,27,45,0.08)", borderRadius: 18, padding: 20 } : {};

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 18, ...sectionWrap }}>
      {multi && (
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ width: 12, height: 12, borderRadius: "50%", background: tradeColor(rec.trade) }} />
          <h2 style={{ margin: 0, fontFamily: DISPLAY, fontSize: 20, fontWeight: 700, color: INK }}>{tradeLabel(rec.trade)}</h2>
          {isHero && <span style={{ background: rgba(BLUE, 0.1), color: BLUE, fontFamily: MONO, fontSize: 10, fontWeight: 600, letterSpacing: "0.06em", textTransform: "uppercase", padding: "3px 9px", borderRadius: 999 }}>Hero scope</span>}
        </div>
      )}
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

      <div style={{ ...cardSx, overflow: "hidden" }}>
        <div style={{ padding: "14px 19px", borderBottom: "1px solid #eef1f6" }}>
          <h3 style={{ margin: 0, fontSize: 14.5, fontWeight: 600, color: INK }}>Bid distribution{band ? " & historical band" : ""}</h3>
          <p style={{ margin: "4px 0 0", fontSize: 12, color: FAINT }}>Corrected totals on the same measured quantities.{band ? " Shaded region is the historical band (low–high), dashed line the median." : ""}</p>
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

      <div style={{ ...cardSx, overflow: "hidden" }}>
        <h3 style={{ margin: 0, padding: "14px 19px", borderBottom: "1px solid #eef1f6", fontFamily: MONO, fontSize: 10.5, fontWeight: 600, letterSpacing: "0.1em", textTransform: "uppercase", color: SOFT }}>Ranked — clean firms first, flagged firms demoted</h3>
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

      <div style={{ ...cardSx, padding: 19 }}>
        <h3 style={{ margin: "0 0 11px", fontFamily: MONO, fontSize: 10.5, fontWeight: 600, letterSpacing: "0.1em", textTransform: "uppercase", color: SOFT }}>Rationale — narrated, not decided</h3>
        <blockquote style={{ margin: 0, borderLeft: "3px solid #6E56CF", background: "linear-gradient(120deg,rgba(110,86,207,0.06),rgba(31,111,235,0.04))", borderRadius: "0 11px 11px 0", padding: "15px 17px", fontSize: 14, lineHeight: 1.7, color: "#1d2c40" }}>{rec.rationale}</blockquote>
      </div>

      <div style={{ ...cardSx, padding: 19 }}>
        <h3 style={{ margin: 0, fontSize: 14.5, fontWeight: 600, color: INK }}>Award — the human decision</h3>
        <p style={{ margin: "5px 0 14px", fontSize: 12.5, color: FAINT }}>The recommendation is decision support. Select the firm to award — overriding onto a flagged firm is recorded.</p>
        <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
          {rec.ranked.map((r) => {
            const on = award === r.firm_id;
            return (
              <label key={r.firm_id} style={{ display: "flex", alignItems: "center", gap: 11, border: `1.5px solid ${on ? BLUE : "rgba(15,27,45,0.12)"}`, background: on ? rgba(BLUE, 0.05) : "#fff", borderRadius: 12, padding: "12px 15px", cursor: "pointer" }}>
                <input type="radio" name={`award-${rec.trade}`} checked={on} onChange={() => onAward(r.firm_id)} style={{ width: 17, height: 17, accentColor: BLUE, cursor: "pointer" }} />
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
    </div>
  );
}
