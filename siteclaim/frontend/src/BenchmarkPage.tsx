import { useEffect, useState } from "react";

import { api } from "./api";
import { Pill, StepHeading } from "./components";
import type {
  BenchmarkProject,
  BenchmarkSummary,
  MatchConfirm,
  MatchPair,
  MatchProposal,
  ProjectEOS,
  ReasonCandidate,
  ReasonCode,
  VarianceRecord,
} from "./types";
import { Button, Card, ErrorBanner, LayerBadge, Modal, cx } from "./ui";

function fmt(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return n.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

// Variance direction marker. Red is reserved for fatal risk elsewhere, so an over-run is
// amber (caution) and a saving is green (ok) — never red.
function DeltaTag({ value, label }: { value: number | null; label?: string }) {
  if (value === null || value === undefined) return <span className="tabular text-xs text-ink-faint">—</span>;
  const over = value > 0.005;
  const under = value < -0.005;
  const tone = over ? "bg-warn-bg text-warn" : under ? "bg-ok-bg text-ok" : "bg-line-soft text-ink-soft";
  const arrow = over ? "▲" : under ? "▼" : "•";
  const word = over ? "over" : under ? "under" : "level";
  return (
    <span className={cx("tabular inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs font-medium", tone)}>
      {arrow} {label ?? word} {fmt(Math.abs(value))}
    </span>
  );
}

function TierBadge({ tier }: { tier: number }) {
  const tone = tier === 1 ? "ok" : tier === 2 ? "brand" : "neutral";
  const label = tier === 1 ? "Exact ref" : tier === 2 ? "Similar desc" : "Unmatched";
  return <Pill tone={tone as "ok" | "brand" | "neutral"}>{`T${tier} · ${label}`}</Pill>;
}

// ---------------------------------------------------------------------------
// Project list
// ---------------------------------------------------------------------------
function ProjectList({
  projects,
  summary,
  onOpen,
  onCreate,
}: {
  projects: BenchmarkProject[];
  summary: BenchmarkSummary | null;
  onOpen: (id: number) => void;
  onCreate: (name: string, trade: string, contractRef: string) => void;
}) {
  const [name, setName] = useState("");
  const [trade, setTrade] = useState("ground_investigation");
  const [contractRef, setContractRef] = useState("");

  return (
    <div className="space-y-5">
      <StepHeading
        title="Benchmark — tender vs outturn"
        lead="Capture each completed project's priced tender against its actual final account, item-matched behind a human gate, into queryable variance records."
      />

      {summary && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {[
            ["Live projects", summary.projects],
            ["Tender items", summary.tender_items],
            ["Actual items", summary.actual_items],
            ["Variance records", summary.variance_records],
          ].map(([label, n]) => (
            <Card key={label} className="px-4 py-3">
              <div className="tabular text-xl font-bold text-ink">{n}</div>
              <div className="text-xs text-ink-faint">{label}</div>
            </Card>
          ))}
        </div>
      )}

      <Card className="p-4">
        <h3 className="mb-2 text-sm font-semibold text-ink">New project</h3>
        <div className="flex flex-wrap items-end gap-2">
          <label className="text-xs text-ink-soft">
            Name
            <input className="mt-1 block w-56 rounded-lg border border-line px-2 py-1.5 text-sm" value={name} onChange={(e) => setName(e.target.value)} placeholder="GI Term Contract 2026" />
          </label>
          <label className="text-xs text-ink-soft">
            Trade
            <input className="mt-1 block w-44 rounded-lg border border-line px-2 py-1.5 text-sm" value={trade} onChange={(e) => setTrade(e.target.value)} />
          </label>
          <label className="text-xs text-ink-soft">
            Contract ref
            <input className="mt-1 block w-36 rounded-lg border border-line px-2 py-1.5 text-sm" value={contractRef} onChange={(e) => setContractRef(e.target.value)} placeholder="GE/2026/14" />
          </label>
          <Button disabled={!name.trim()} onClick={() => { onCreate(name.trim(), trade.trim(), contractRef.trim()); setName(""); setContractRef(""); }}>
            Create
          </Button>
        </div>
      </Card>

      <div className="space-y-2">
        {projects.length === 0 && <p className="text-sm text-ink-faint">No projects yet — create one, or (in demo) the illustrative scenario appears here.</p>}
        {projects.map((p) => (
          <Card key={p.id} className="flex flex-wrap items-center gap-3 p-4">
            <button className="text-left" onClick={() => onOpen(p.id)}>
              <div className="flex items-center gap-2">
                <span className="text-sm font-semibold text-ink hover:text-brand">{p.name}</span>
                {p.provenance === "demo" && <Pill tone="neutral">Illustrative</Pill>}
                {p.status === "closed" && <Pill tone="ok">Closed</Pill>}
              </div>
              <div className="text-xs text-ink-faint">{[p.contract_ref, p.trade].filter(Boolean).join(" · ")}</div>
            </button>
            <div className="ml-auto flex items-center gap-1.5">
              <Pill tone="neutral">{`${p.tender_item_count} tender`}</Pill>
              <Pill tone="neutral">{`${p.actual_item_count} actual`}</Pill>
              <Pill tone="brand">{`${p.variance_count} variance`}</Pill>
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Project detail — uploads, match review, variance table
// ---------------------------------------------------------------------------
function UploadButton({ label, onPick }: { label: string; onPick: (files: File[]) => void }) {
  return (
    <label className="inline-flex cursor-pointer items-center rounded-lg border border-line bg-card px-3 py-2 text-sm font-semibold text-ink hover:bg-line-soft">
      {label}
      <input
        type="file"
        className="hidden"
        onChange={(e) => { const fs = Array.from(e.target.files ?? []); if (fs.length) onPick(fs); e.target.value = ""; }}
      />
    </label>
  );
}

function MatchRow({ pair, onConfirm, confirmed }: { pair: MatchPair; onConfirm: () => void; confirmed: boolean }) {
  return (
    <div className="flex flex-wrap items-center gap-3 border-b border-line-soft px-3 py-2 last:border-0">
      <div className="min-w-0 flex-1">
        <div className="text-xs text-ink-faint">Tender</div>
        <div className="truncate text-sm text-ink">{pair.tender ? `${pair.tender.item_ref} — ${pair.tender.description}` : "— (arrived unpriced)"}</div>
      </div>
      <div className="min-w-0 flex-1">
        <div className="text-xs text-ink-faint">Actual</div>
        <div className="truncate text-sm text-ink">{pair.actual ? `${pair.actual.item_ref || "(coarse)"} — ${pair.actual.description}` : "— (omitted at tender)"}</div>
      </div>
      <TierBadge tier={pair.tier} />
      {pair.similarity !== null && pair.tier === 2 && <span className="tabular text-xs text-ink-faint">{Math.round(pair.similarity * 100)}%</span>}
      <Button variant="ghost" disabled={confirmed} onClick={onConfirm}>{confirmed ? "Confirmed" : "Confirm"}</Button>
    </div>
  );
}

function pairKey(p: MatchPair): string {
  return `${p.tender?.id ?? "x"}-${p.actual?.id ?? "x"}`;
}

function toConfirm(p: MatchPair): MatchConfirm {
  return { tender_item_id: p.tender?.id ?? null, actual_item_id: p.actual?.id ?? null, match_tier: p.tier };
}

// The reason cell: the EOS-sourced candidate (Layer-2 suggestion) with its narrative
// snippet and a one-click confirm, over the override dropdown. The human always writes —
// confirming or overriding routes through the same reason POST (the sole writer).
function ReasonCell({
  record,
  candidate,
  reasonCodes,
  onSet,
}: {
  record: VarianceRecord;
  candidate: ReasonCandidate | undefined;
  reasonCodes: ReasonCode[];
  onSet: (code: string, note: string) => void;
}) {
  const label = (code: string) => reasonCodes.find((c) => c.code === code)?.label ?? code;
  const confirmed = !!candidate && record.reason_code === candidate.reason_code;
  return (
    <div className="min-w-[13rem] space-y-1.5">
      {candidate && (
        <div className="rounded-lg border border-brand/30 bg-brand-bg/40 px-2 py-1.5">
          <div className="flex items-center gap-1.5">
            <LayerBadge layer="L2" />
            <span className="text-xs font-semibold text-ink">EOS · {label(candidate.reason_code)}</span>
            {confirmed ? (
              <Pill tone="ok">Confirmed</Pill>
            ) : (
              <button
                className="ml-auto rounded bg-brand px-2 py-0.5 text-xs font-semibold text-white hover:opacity-90"
                onClick={() => onSet(candidate.reason_code, candidate.snippet)}
              >
                Confirm
              </button>
            )}
          </div>
          {candidate.snippet && (
            <p className="mt-1 text-xs italic leading-snug text-ink-soft">“{candidate.snippet}”</p>
          )}
        </div>
      )}
      <select
        className={cx("w-full rounded-lg border px-2 py-1 text-xs", record.reason_code ? "border-line text-ink" : "border-warn/40 text-ink-soft")}
        value={record.reason_code}
        onChange={(e) => onSet(e.target.value, record.reason_note)}
      >
        <option value="">
          {candidate
            ? `Override (EOS: ${label(candidate.reason_code)})`
            : record.suggested_reason
              ? `Suggested: ${record.suggested_reason}`
              : "— set reason —"}
        </option>
        {reasonCodes.map((c) => (
          <option key={c.code} value={c.code}>{c.label}</option>
        ))}
      </select>
    </div>
  );
}

// The per-project EOS field report — the narrative account the reason candidates are drawn
// from. Layer-2 reads it; the human confirms each reason. Illustrative until a partner
// archive exists. Includes a paste-the-narrative attach affordance (the live path).
function EosPanel({ eos, onAttach }: { eos: ProjectEOS | null; onAttach: (narrative: string) => void }) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  return (
    <Card className="p-4">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <h3 className="text-sm font-semibold text-ink">EOS field report</h3>
        <LayerBadge layer="L2" />
        {eos?.provenance === "demo" && <Pill tone="neutral">Illustrative</Pill>}
        {eos?.has_images && <Pill tone="neutral">has site photos</Pill>}
        <Button variant="subtle" className="ml-auto" onClick={() => { setText(eos?.narrative ?? ""); setOpen(true); }}>
          {eos ? "Update narrative" : "Attach narrative"}
        </Button>
      </div>
      {eos ? (
        <>
          {eos.summary && <p className="text-sm text-ink">{eos.summary}</p>}
          <p className="mt-2 text-xs leading-relaxed text-ink-soft">{eos.narrative}</p>
          <p className="mt-2 text-xs text-ink-faint">
            The AI reads the narrative and proposes a reason per variance line below; a person confirms it. The
            reason is never written by the AI.
          </p>
        </>
      ) : (
        <p className="text-sm text-ink-faint">
          No EOS narrative attached. Paste the field account and the AI will propose a reason — with its
          supporting sentence — for each variance line.
        </p>
      )}
      <Modal open={open} onClose={() => setOpen(false)} title="EOS narrative">
        <p className="mb-2 text-xs text-ink-soft">
          Paste the End-of-Site field account — the narrative of what happened on site. It supplies the reason
          behind each variance, never a number.
        </p>
        <textarea
          className="h-48 w-full rounded-lg border border-line px-2 py-1.5 text-sm"
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="On site, the rig stood idle while utility diversions were completed…"
        />
        <div className="mt-3 flex justify-end gap-2">
          <Button variant="ghost" onClick={() => setOpen(false)}>Cancel</Button>
          <Button disabled={!text.trim()} onClick={() => { onAttach(text.trim()); setOpen(false); }}>Save narrative</Button>
        </div>
      </Modal>
    </Card>
  );
}

function ProjectDetail({
  project,
  reasonCodes,
  onBack,
  onChanged,
}: {
  project: BenchmarkProject;
  reasonCodes: ReasonCode[];
  onBack: () => void;
  onChanged: () => void;
}) {
  const [matches, setMatches] = useState<MatchProposal | null>(null);
  const [variance, setVariance] = useState<VarianceRecord[]>([]);
  const [confirmedKeys, setConfirmedKeys] = useState<Set<string>>(new Set());
  const [eos, setEos] = useState<ProjectEOS | null>(null);
  const [suggestions, setSuggestions] = useState<Record<number, ReasonCandidate>>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const id = project.id;
  const loadMatches = () => api.benchmarkMatches(id).then(setMatches).catch((e) => setError(String(e.message ?? e)));
  const loadVariance = () => api.benchmarkVariance(id).then(setVariance).catch((e) => setError(String(e.message ?? e)));
  const loadEos = () => api.benchmarkEos(id).then(setEos).catch(() => {});
  const loadSuggestions = () =>
    api.reasonSuggestions(id)
      .then((s) =>
        setSuggestions(Object.fromEntries(
          s.candidates.filter((c) => c.record_id != null).map((c) => [c.record_id as number, c]),
        )),
      )
      .catch(() => {});
  useEffect(() => { loadMatches(); loadVariance(); loadEos(); loadSuggestions(); /* eslint-disable-next-line */ }, [id]);

  const upload = (path: string, files: File[]) => {
    setBusy(true); setError(null);
    api.uploadBenchmarkFile(path, files)
      .then(() => { loadMatches(); loadVariance(); loadSuggestions(); onChanged(); })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setBusy(false));
  };

  const confirm = (pairs: MatchPair[]) => {
    setBusy(true); setError(null);
    api.confirmMatches(id, pairs.map(toConfirm))
      .then((recs) => {
        setVariance(recs);
        setConfirmedKeys((cur) => { const next = new Set(cur); pairs.forEach((p) => next.add(pairKey(p))); return next; });
        loadSuggestions();  // new variance records -> refresh the EOS reason candidates
        onChanged();
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setBusy(false));
  };

  const setReason = (recordId: number, code: string, note: string) => {
    if (!code) return;
    api.setVarianceReason(id, recordId, { reason_code: code, note })
      .then((rec) => setVariance((cur) => cur.map((r) => (r.id === rec.id ? rec : r))))
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  };

  const attachEos = (narrative: string) => {
    setError(null);
    api.attachEos(id, narrative)
      .then(() => { loadEos(); loadSuggestions(); })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  };

  const allPairs = matches ? [...matches.tier1, ...matches.tier2, ...matches.tier3] : [];

  return (
    <div className="space-y-5">
      <div className="flex items-center gap-3">
        <Button variant="subtle" onClick={onBack}>← Projects</Button>
        <h2 className="text-base font-semibold text-ink">{project.name}</h2>
        {project.provenance === "demo" && <Pill tone="neutral">Illustrative</Pill>}
      </div>
      {error && <ErrorBanner message={error} />}

      <Card className="flex flex-wrap items-center gap-3 p-4">
        <h3 className="text-sm font-semibold text-ink">Documents</h3>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <UploadButton label="Upload priced tender (xlsx)" onPick={(f) => upload(`/benchmark/${id}/tender-upload`, f)} />
          <a className="inline-flex items-center rounded-lg border border-line bg-card px-3 py-2 text-sm font-semibold text-ink hover:bg-line-soft" href={api.actualsTemplateUrl(id)} target="_blank" rel="noreferrer">
            Download actuals template
          </a>
          <UploadButton label="Upload actuals (xlsx)" onPick={(f) => upload(`/benchmark/${id}/actuals-upload`, f)} />
        </div>
      </Card>

      <Card className="p-0">
        <div className="flex items-center justify-between border-b border-line-soft px-4 py-2.5">
          <h3 className="text-sm font-semibold text-ink">Match review</h3>
          <div className="flex items-center gap-2">
            {matches && matches.tier1.length > 0 && (
              <Button variant="ghost" loading={busy} onClick={() => confirm(matches.tier1)}>Confirm all Tier 1 ({matches.tier1.length})</Button>
            )}
            <Button variant="subtle" onClick={loadMatches}>Refresh</Button>
          </div>
        </div>
        {allPairs.length === 0 && <p className="px-4 py-3 text-sm text-ink-faint">Upload a tender and actuals to propose matches.</p>}
        {allPairs.map((p) => (
          <MatchRow key={pairKey(p)} pair={p} confirmed={confirmedKeys.has(pairKey(p))} onConfirm={() => confirm([p])} />
        ))}
      </Card>

      <EosPanel eos={eos} onAttach={attachEos} />

      <Card className="p-0">
        <div className="border-b border-line-soft px-4 py-2.5">
          <h3 className="text-sm font-semibold text-ink">Variance table</h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-line-soft text-left text-xs text-ink-faint">
                <th className="px-3 py-2">Item</th>
                <th className="px-3 py-2">Tender → Actual rate</th>
                <th className="px-3 py-2">Rate Δ</th>
                <th className="px-3 py-2">Amount Δ</th>
                <th className="px-3 py-2">qty / rate driven</th>
                <th className="px-3 py-2">Reason</th>
              </tr>
            </thead>
            <tbody>
              {variance.length === 0 && (
                <tr><td className="px-3 py-3 text-ink-faint" colSpan={6}>No variance records yet — confirm matches above.</td></tr>
              )}
              {variance.map((r) => (
                <tr key={r.id} className="border-b border-line-soft last:border-0">
                  <td className="px-3 py-2">
                    <div className="font-medium text-ink">{r.item_ref || "(coarse)"}</div>
                    <div className="text-xs text-ink-faint">{r.granularity !== "item" ? r.granularity : `T${r.match_tier}`}</div>
                  </td>
                  <td className="tabular px-3 py-2 text-ink-soft">{fmt(r.tender_rate)} → {fmt(r.actual_rate)}</td>
                  <td className="px-3 py-2"><DeltaTag value={r.rate_delta} /></td>
                  <td className="px-3 py-2"><DeltaTag value={r.amount_delta} /></td>
                  <td className="tabular px-3 py-2 text-xs text-ink-soft">{fmt(r.amount_delta_qty)} / {fmt(r.amount_delta_rate)}</td>
                  <td className="px-3 py-2 align-top">
                    <ReasonCell
                      record={r}
                      candidate={suggestions[r.id]}
                      reasonCodes={reasonCodes}
                      onSet={(code, note) => setReason(r.id, code, note)}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------------------
export function BenchmarkPage() {
  const [projects, setProjects] = useState<BenchmarkProject[]>([]);
  const [summary, setSummary] = useState<BenchmarkSummary | null>(null);
  const [reasonCodes, setReasonCodes] = useState<ReasonCode[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadList = () => {
    api.benchmarkProjects().then(setProjects).catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
    api.benchmarkSummary().then(setSummary).catch(() => {});
  };
  useEffect(() => {
    loadList();
    api.reasonCodes().then(setReasonCodes).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const selectedProject = projects.find((p) => p.id === selected) ?? null;

  return (
    <div className="min-w-0 space-y-4">
      {error && <ErrorBanner message={error} />}
      {selected != null && selectedProject ? (
        <ProjectDetail
          project={selectedProject}
          reasonCodes={reasonCodes}
          onBack={() => { setSelected(null); loadList(); }}
          onChanged={loadList}
        />
      ) : (
        <ProjectList
          projects={projects}
          summary={summary}
          onOpen={(id) => setSelected(id)}
          onCreate={(name, trade, contractRef) =>
            api.createBenchmarkProject({ name, trade, contract_ref: contractRef })
              .then(() => loadList())
              .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
          }
        />
      )}
    </div>
  );
}
