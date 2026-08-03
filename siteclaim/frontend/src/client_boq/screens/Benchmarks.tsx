// Benchmark corpus — the completed-project record: what a job was tendered at, against what
// it actually cost, line by line. Ported from BenchmarkPage; behaviour, wording and decision
// semantics unchanged, palette only.
//
// Two rules this screen exists to protect, which the colour therefore has to state out loud:
//
//  * A MATCH IS A PROPOSAL UNTIL A PERSON CONFIRMS IT. The matcher pairs a tender line to an
//    actual line — Tier 1 on an exact item ref, Tier 2 on a deterministic embedding
//    similarity, Tier 3 not at all — and that pair becomes a variance record only when
//    somebody presses Confirm. The tier is therefore drawn as a MAGNITUDE, on the same
//    ok / panel / panel scale MatchChip uses, and never in brass or navy: no model and no
//    rule is claiming the pairing, a person is about to.
//  * A REASON IS WRITTEN ONLY BY THE PERSON WHO POSTS IT. Claude reads the EOS field report
//    and PROPOSES one reason code per moved line, quoting the sentence it came from. The
//    proposal is brass and carries the CLAUDE mark; a recorded reason is green. If those two
//    ever come to look alike the corpus stops being evidence and becomes an opinion, and
//    that is the single failure this screen is built to prevent.
//
// Variance direction is never red — red is reserved for a check that failed. An over-run is
// amber (border and text; cb has no amber fill and one is not invented here) and a saving is
// green, exactly as the screen this was ported from had it.

import { useEffect, useState } from "react";

import { api } from "../api";
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
} from "../types";
import {
  AuthorBadge,
  Button,
  Card,
  Chip,
  Collapse,
  Docket,
  Drawer,
  ErrorNote,
  LoadingDots,
  Modal,
  Pill,
  SectionLabel,
  Spinner,
  StatCallout,
  StepHeading,
  cx,
} from "../ui";

/** Local, deliberately — client_boq imports nothing from the procurement tree. */
function fmt(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return n.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

/** The small controls this screen needs are hand-rolled rather than `Button`: a disabled cb
 *  Button renders dashed and grey, which reads "you cannot do this" — the wrong sentence for
 *  a gate that has already been passed. Shortlist makes the same call for the same reason. */
const SMALL_BTN =
  "cb-press rounded-cb-btn border px-2.5 py-1 font-cb-sans text-[10px] font-semibold";

// Variance direction marker. Red is reserved for a failed check, so an over-run is amber
// (caution) and a saving is ok — never red. cb has no amber FILL token, so the caution state
// is a brass hairline plus amber text rather than an invented tint.
function DeltaTag({ value, label }: { value: number | null; label?: string }) {
  if (value === null || value === undefined)
    return <span className="font-cb-mono text-[10px] text-cb-faint">—</span>;
  const over = value > 0.005;
  const under = value < -0.005;
  const tone = over
    ? "border border-cb-brass-line text-cb-amber"
    : under
      ? "bg-cb-ok-tint text-cb-ok-dark"
      : "bg-cb-panel text-cb-muted";
  const arrow = over ? "▲" : under ? "▼" : "•";
  const word = over ? "over" : under ? "under" : "level";
  return (
    <span
      className={cx(
        "inline-flex items-center gap-1 rounded-cb-chip px-1.5 py-0.5 font-cb-mono text-[10px] font-medium",
        tone,
      )}
    >
      {arrow} {label ?? word} {fmt(Math.abs(value))}
    </span>
  );
}

/** How the matcher paired the line. A magnitude, not an authorship claim — the pairing is
 *  deterministic (exact ref, then embedding cosine) and is still only a proposal, so it takes
 *  the same ok / panel / panel scale MatchChip uses rather than brass or navy. */
function TierBadge({ tier }: { tier: number }) {
  const cls =
    tier === 1
      ? "bg-cb-ok-tint text-cb-ok-dark"
      : tier === 2
        ? "bg-cb-panel text-cb-body"
        : "bg-cb-panel text-cb-faint";
  const label = tier === 1 ? "Exact ref" : tier === 2 ? "Similar desc" : "Unmatched";
  return <Chip className={cls}>{`T${tier} · ${label}`}</Chip>;
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

  const field =
    "rounded-cb-btn border border-cb-border bg-cb-warm px-2.5 py-1.5 font-cb-sans text-[11.5px] text-cb-ink-text placeholder:text-cb-faint";

  return (
    <div className="space-y-5">
      <StepHeading
        title="Benchmark — tender vs outturn"
        lead="Capture each completed project's priced tender against its actual final account, item-matched behind a human gate, into queryable variance records."
      />

      {summary && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {/* Counts, no judgement — the neutral panel treatment, mono digits. */}
          <StatCallout label="Live projects" value={summary.projects} />
          <StatCallout label="Tender items" value={summary.tender_items} />
          <StatCallout label="Actual items" value={summary.actual_items} />
          <StatCallout label="Variance records" value={summary.variance_records} />
        </div>
      )}

      <Card>
        <h3 className="mb-2 font-cb-sans text-[12px] font-semibold text-cb-ink-text">New project</h3>
        <div className="flex flex-wrap items-end gap-2">
          <label className="font-cb-sans text-[10px] text-cb-muted">
            Name
            <input
              className={cx(field, "mt-1 block w-56")}
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="GI Term Contract 2026"
            />
          </label>
          <label className="font-cb-sans text-[10px] text-cb-muted">
            Trade
            <input
              className={cx(field, "mt-1 block w-44")}
              value={trade}
              onChange={(e) => setTrade(e.target.value)}
            />
          </label>
          <label className="font-cb-sans text-[10px] text-cb-muted">
            Contract ref
            <input
              className={cx(field, "mt-1 block w-36 font-cb-mono text-[11px]")}
              value={contractRef}
              onChange={(e) => setContractRef(e.target.value)}
              placeholder="GE/2026/14"
            />
          </label>
          <Button
            variant="brass"
            disabled={!name.trim()}
            onClick={() => {
              onCreate(name.trim(), trade.trim(), contractRef.trim());
              setName("");
              setContractRef("");
            }}
          >
            Create
          </Button>
        </div>
      </Card>

      <div className="space-y-2">
        {projects.length === 0 && (
          <p className="font-cb-sans text-[11px] text-cb-faint">
            No projects yet — create one, or (in demo) the illustrative scenario appears here.
          </p>
        )}
        {projects.map((p) => (
          <Card key={p.id} className="flex flex-wrap items-center gap-3">
            <button className="text-left" onClick={() => onOpen(p.id)}>
              <div className="flex items-center gap-2">
                <span className="font-cb-sans text-[12px] font-semibold text-cb-ink-text hover:text-cb-brass-text">
                  {p.name}
                </span>
                {/* Provenance and status are labels, not judgements — neutral panel, except a
                    closed project, which is a completed state and reads as ok. */}
                {p.provenance === "demo" && (
                  <Pill className="bg-cb-panel text-cb-muted">Illustrative</Pill>
                )}
                {p.status === "closed" && (
                  <Pill className="bg-cb-ok-tint text-cb-ok-dark">Closed</Pill>
                )}
              </div>
              <div className="mt-0.5 font-cb-mono text-[10px] text-cb-faint">
                {[p.contract_ref, p.trade].filter(Boolean).join(" · ")}
              </div>
            </button>
            <div className="ml-auto flex items-center gap-1.5">
              <Chip className="bg-cb-panel text-cb-muted">{`${p.tender_item_count} tender`}</Chip>
              <Chip className="bg-cb-panel text-cb-muted">{`${p.actual_item_count} actual`}</Chip>
              {/* A variance record is Layer-1 arithmetic written at a human gate — a register
                  fact, so navy. Never brass: no model wrote one of these. */}
              <Chip className="bg-cb-info-fill text-cb-navy">{`${p.variance_count} variance`}</Chip>
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
    <label className="cb-press inline-flex cursor-pointer items-center rounded-cb-btn border border-cb-border-strong bg-white px-3 py-2 font-cb-sans text-[11px] font-medium text-cb-ink-text hover:bg-cb-panel">
      {label}
      <input
        type="file"
        className="hidden"
        onChange={(e) => {
          const fs = Array.from(e.target.files ?? []);
          if (fs.length) onPick(fs);
          e.target.value = "";
        }}
      />
    </label>
  );
}

function MatchRow({
  pair,
  onConfirm,
  confirmed,
}: {
  pair: MatchPair;
  onConfirm: () => void;
  confirmed: boolean;
}) {
  return (
    <div className="flex flex-wrap items-center gap-3 border-b border-cb-divider px-3 py-2 last:border-0">
      <div className="min-w-0 flex-1">
        <SectionLabel>Tender</SectionLabel>
        <div className="truncate font-cb-sans text-[11.5px] text-cb-body">
          {pair.tender ? `${pair.tender.item_ref} — ${pair.tender.description}` : "— (arrived unpriced)"}
        </div>
      </div>
      <div className="min-w-0 flex-1">
        <SectionLabel>Actual</SectionLabel>
        <div className="truncate font-cb-sans text-[11.5px] text-cb-body">
          {pair.actual ? `${pair.actual.item_ref || "(coarse)"} — ${pair.actual.description}` : "— (omitted at tender)"}
        </div>
      </div>
      <TierBadge tier={pair.tier} />
      {pair.similarity !== null && pair.tier === 2 && (
        <span className="font-cb-mono text-[10px] text-cb-faint">
          {Math.round(pair.similarity * 100)}%
        </span>
      )}
      {/* The gate. Confirming is the human's act, so it is ink — and once passed it is ok,
          because it happened, not disabled-grey, which would say it could not be done. */}
      <button
        type="button"
        disabled={confirmed}
        onClick={onConfirm}
        className={cx(
          SMALL_BTN,
          confirmed
            ? "cursor-default border-cb-ok bg-cb-ok-tint text-cb-ok-dark"
            : "border-cb-ink bg-cb-ink text-white",
        )}
      >
        {confirmed ? "Confirmed" : "Confirm"}
      </button>
    </div>
  );
}

function pairKey(p: MatchPair): string {
  return `${p.tender?.id ?? "x"}-${p.actual?.id ?? "x"}`;
}

function toConfirm(p: MatchPair): MatchConfirm {
  return { tender_item_id: p.tender?.id ?? null, actual_item_id: p.actual?.id ?? null, match_tier: p.tier };
}

// The reason cell: the EOS-sourced candidate — a model PROPOSAL, so brass and marked CLAUDE —
// with its narrative snippet and a one-click confirm, over the override dropdown. The human
// always writes — confirming or overriding routes through the same reason POST (the sole
// writer). A confirmed reason turns green; the proposal never does.
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
        <div className="rounded-cb-card border border-cb-brass-line bg-cb-brass-tint px-2 py-1.5">
          <div className="flex items-center gap-1.5">
            <AuthorBadge author="model" />
            <span className="font-cb-sans text-[10.5px] font-semibold text-cb-brass-text">
              EOS · {label(candidate.reason_code)}
            </span>
            {confirmed ? (
              <Pill className="bg-cb-ok-tint text-cb-ok-dark">Confirmed</Pill>
            ) : (
              <button
                className={cx(SMALL_BTN, "ml-auto border-cb-ink bg-cb-ink text-white")}
                onClick={() => onSet(candidate.reason_code, candidate.snippet)}
              >
                Confirm
              </button>
            )}
          </div>
          {/* The quoted sentence from the field report — serif, because it is the argument
              rather than the interface, and italic because it is somebody else's words. */}
          {candidate.snippet && (
            <p className="mt-1 font-cb-serif text-[11px] italic leading-snug text-cb-brass-text">
              “{candidate.snippet}”
            </p>
          )}
        </div>
      )}
      <select
        className={cx(
          "w-full rounded-cb-btn border bg-white px-2 py-1 font-cb-sans text-[10.5px]",
          // Untagged is a warning — this line has no recorded reason yet. Amber is a hairline
          // and text, never a fill.
          record.reason_code
            ? "border-cb-border text-cb-ink-text"
            : "border-cb-brass-line text-cb-amber",
        )}
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
          <option key={c.code} value={c.code}>
            {c.label}
          </option>
        ))}
      </select>
    </div>
  );
}

// The per-project EOS field report — the narrative account the reason candidates are drawn
// from. Claude reads it; the human confirms each reason. Illustrative until a partner archive
// exists. Includes a paste-the-narrative attach affordance (the live path).
function EosPanel({ eos, onAttach }: { eos: ProjectEOS | null; onAttach: (narrative: string) => void }) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  return (
    <Card>
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <h3 className="font-cb-sans text-[12px] font-semibold text-cb-ink-text">EOS field report</h3>
        {/* Atlas's `LayerBadge layer="L2"` here, kept as its literal copy rather than as cb's
            `AuthorBadge author="model"`. The two look alike and mean opposite things: the badge
            claims the model WROTE this, and this narrative is a human field report the user
            pasted. What Atlas was marking is where Layer 2 OPERATES — it reads the narrative
            below. Brass still, because the reading is the model's; the wording carries the rest.
            `AuthorBadge` is correct at its other use, on the reason candidate the model proposes. */}
        <Chip className="bg-cb-brass-tint text-cb-brass-text">LAYER 2 · CLAUDE</Chip>
        {eos?.provenance === "demo" && <Pill className="bg-cb-panel text-cb-muted">Illustrative</Pill>}
        {eos?.has_images && <Pill className="bg-cb-panel text-cb-muted">has site photos</Pill>}
        <Button
          variant="outline"
          className="ml-auto"
          onClick={() => {
            setText(eos?.narrative ?? "");
            setOpen(true);
          }}
        >
          {eos ? "Update narrative" : "Attach narrative"}
        </Button>
      </div>
      {eos ? (
        <>
          {eos.summary && (
            <p className="font-cb-serif text-[12px] leading-relaxed text-cb-ink-text">{eos.summary}</p>
          )}
          <p className="mt-2 font-cb-serif text-[11px] leading-relaxed text-cb-body">{eos.narrative}</p>
          <p className="mt-2 font-cb-sans text-[10px] leading-[1.5] text-cb-faint">
            Claude (Layer 2) reads the narrative and proposes a reason per variance line below; a
            person confirms it. The recorded reason is always the human's — never written by Claude.
          </p>
        </>
      ) : (
        <p className="font-cb-sans text-[11px] leading-[1.5] text-cb-faint">
          No EOS narrative attached. Paste the field account and a reason candidate is proposed —
          with its supporting sentence — for each variance line; a person confirms every reason.
        </p>
      )}
      <Modal open={open} onClose={() => setOpen(false)} title="EOS narrative">
        <p className="mb-2 font-cb-sans text-[10.5px] leading-[1.5] text-cb-muted">
          Paste the End-of-Site field account — the narrative of what happened on site. It supplies
          the reason behind each variance, never a number.
        </p>
        <textarea
          className="h-48 w-full rounded-cb-btn border border-cb-border bg-cb-warm px-2.5 py-1.5 font-cb-serif text-[11.5px] leading-[1.5] text-cb-ink-text placeholder:font-cb-sans placeholder:text-cb-faint"
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="On site, the rig stood idle while utility diversions were completed…"
        />
        <div className="mt-3 flex justify-end gap-2">
          <Button variant="ghost" onClick={() => setOpen(false)}>
            Cancel
          </Button>
          <Button
            variant="brass"
            disabled={!text.trim()}
            onClick={() => {
              onAttach(text.trim());
              setOpen(false);
            }}
          >
            Save narrative
          </Button>
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
  onError,
}: {
  project: BenchmarkProject;
  reasonCodes: ReasonCode[];
  onBack: () => void;
  onChanged: () => void;
  onError: (message: string) => void;
}) {
  const [matches, setMatches] = useState<MatchProposal | null>(null);
  const [variance, setVariance] = useState<VarianceRecord[]>([]);
  const [confirmedKeys, setConfirmedKeys] = useState<Set<string>>(new Set());
  const [eos, setEos] = useState<ProjectEOS | null>(null);
  const [suggestions, setSuggestions] = useState<Record<number, ReasonCandidate>>({});
  const [detail, setDetail] = useState<VarianceRecord | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Kept inline as well as raised to the shell: a refusal belongs next to the control that
  // caused it, and the backend's own sentence names what refused and why.
  const fail = (message: string) => {
    setError(message);
    onError(message);
  };

  const id = project.id;
  const loadMatches = () =>
    api.manage.benchmarkMatches(id).then(setMatches).catch((e) => fail(String(e.message ?? e)));
  const loadVariance = () =>
    api.manage.benchmarkVariance(id).then(setVariance).catch((e) => fail(String(e.message ?? e)));
  const loadEos = () => api.manage.benchmarkEos(id).then(setEos).catch(() => {});
  const loadSuggestions = () =>
    api.manage
      .reasonSuggestions(id)
      .then((s) =>
        setSuggestions(
          Object.fromEntries(
            s.candidates.filter((c) => c.record_id != null).map((c) => [c.record_id as number, c]),
          ),
        ),
      )
      .catch(() => {});
  useEffect(() => {
    loadMatches();
    loadVariance();
    loadEos();
    loadSuggestions(); /* eslint-disable-next-line */
  }, [id]);

  const upload = (path: string, files: File[]) => {
    setBusy(true);
    setError(null);
    api.manage
      .uploadBenchmarkFile(path, files)
      .then(() => {
        loadMatches();
        loadVariance();
        loadSuggestions();
        onChanged();
      })
      .catch((e: unknown) => fail(e instanceof Error ? e.message : String(e)))
      .finally(() => setBusy(false));
  };

  const confirm = (pairs: MatchPair[]) => {
    setBusy(true);
    setError(null);
    api.manage
      .confirmMatches(id, pairs.map(toConfirm))
      .then((recs) => {
        setVariance(recs);
        setConfirmedKeys((cur) => {
          const next = new Set(cur);
          pairs.forEach((p) => next.add(pairKey(p)));
          return next;
        });
        loadSuggestions(); // new variance records -> refresh the EOS reason candidates
        onChanged();
      })
      .catch((e: unknown) => fail(e instanceof Error ? e.message : String(e)))
      .finally(() => setBusy(false));
  };

  const setReason = (recordId: number, code: string, note: string) => {
    if (!code) return;
    api.manage
      .setVarianceReason(id, recordId, { reason_code: code, note })
      .then((rec) => setVariance((cur) => cur.map((r) => (r.id === rec.id ? rec : r))))
      .catch((e: unknown) => fail(e instanceof Error ? e.message : String(e)));
  };

  const attachEos = (narrative: string) => {
    setError(null);
    api.manage
      .attachEos(id, narrative)
      .then(() => {
        loadEos();
        loadSuggestions();
      })
      .catch((e: unknown) => fail(e instanceof Error ? e.message : String(e)));
  };

  const allPairs = matches ? [...matches.tier1, ...matches.tier2, ...matches.tier3] : [];

  return (
    <div className="space-y-5">
      <div className="flex items-center gap-3">
        <Button variant="ghost" onClick={onBack}>
          ← Projects
        </Button>
        <h2 className="font-cb-serif text-[16px] font-semibold text-cb-ink-text">{project.name}</h2>
        {project.provenance === "demo" && (
          <Pill className="bg-cb-panel text-cb-muted">Illustrative</Pill>
        )}
      </div>
      {error && <ErrorNote message={error} onDismiss={() => setError(null)} />}

      <Card className="flex flex-wrap items-center gap-3">
        <h3 className="font-cb-sans text-[12px] font-semibold text-cb-ink-text">Documents</h3>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <UploadButton
            label="Upload priced tender (xlsx)"
            onPick={(f) => upload(`/benchmark/${id}/tender-upload`, f)}
          />
          <a
            className="cb-press inline-flex items-center rounded-cb-btn border border-cb-border-strong bg-white px-3 py-2 font-cb-sans text-[11px] font-medium text-cb-ink-text hover:bg-cb-panel"
            href={api.manage.actualsTemplateUrl(id)}
            target="_blank"
            rel="noreferrer"
          >
            Download actuals template
          </a>
          <UploadButton
            label="Upload actuals (xlsx)"
            onPick={(f) => upload(`/benchmark/${id}/actuals-upload`, f)}
          />
        </div>
      </Card>

      <Card flush>
        <div className="flex items-center justify-between border-b border-cb-divider px-4 py-2.5">
          <h3 className="font-cb-sans text-[12px] font-semibold text-cb-ink-text">Match review</h3>
          <div className="flex items-center gap-2">
            {matches && matches.tier1.length > 0 && (
              <Button variant="outline" disabled={busy} onClick={() => confirm(matches.tier1)}>
                {/* The source's `loading` Button spun while the confirm was in flight; cb's Button
                    has no loading prop, so the spinner is placed by hand rather than dropped. */}
                <span className="inline-flex items-center gap-2">
                  {busy && <Spinner />}
                  Confirm all Tier 1 ({matches.tier1.length})
                </span>
              </Button>
            )}
            <Button variant="ghost" onClick={loadMatches}>
              Refresh
            </Button>
          </div>
        </div>
        {allPairs.length === 0 && (
          <p className="px-4 py-3 font-cb-sans text-[11px] text-cb-faint">
            Upload a tender and actuals to propose matches.
          </p>
        )}
        {allPairs.map((p) => (
          <MatchRow
            key={pairKey(p)}
            pair={p}
            confirmed={confirmedKeys.has(pairKey(p))}
            onConfirm={() => confirm([p])}
          />
        ))}
      </Card>

      <EosPanel eos={eos} onAttach={attachEos} />

      <Card flush>
        <div className="border-b border-cb-divider px-4 py-2.5">
          <h3 className="font-cb-sans text-[12px] font-semibold text-cb-ink-text">Variance table</h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left">
            <thead>
              <tr className="border-b border-cb-divider">
                {["Item", "Tender → Actual rate", "Rate Δ", "Amount Δ", "qty / rate driven", "Reason"].map(
                  (h) => (
                    <th
                      key={h}
                      className="px-3 py-2 font-cb-mono text-[8.5px] font-semibold tracking-cb-chip text-cb-faint"
                    >
                      {h}
                    </th>
                  ),
                )}
              </tr>
            </thead>
            <tbody>
              {variance.length === 0 && (
                <tr>
                  <td className="px-3 py-3 font-cb-sans text-[11px] text-cb-faint" colSpan={6}>
                    No variance records yet — confirm matches above.
                  </td>
                </tr>
              )}
              {variance.map((r) => (
                <tr key={r.id} className="cb-row border-b border-cb-divider last:border-0">
                  <td className="px-3 py-2">
                    <button
                      type="button"
                      onClick={() => setDetail(r)}
                      title="Open the variance record"
                      className="text-left font-cb-mono text-[11px] font-semibold text-cb-ink-text hover:text-cb-brass-text focus:outline-none focus-visible:ring-2 focus-visible:ring-cb-brass"
                    >
                      {r.item_ref || "(coarse)"}
                    </button>
                    <div className="font-cb-mono text-[9.5px] text-cb-faint">
                      {r.granularity !== "item" ? r.granularity : `T${r.match_tier}`}
                    </div>
                  </td>
                  <td className="px-3 py-2 font-cb-mono text-[11px] text-cb-body">
                    {fmt(r.tender_rate)} → {fmt(r.actual_rate)}
                  </td>
                  <td className="px-3 py-2">
                    <DeltaTag value={r.rate_delta} />
                  </td>
                  <td className="px-3 py-2">
                    <DeltaTag value={r.amount_delta} />
                  </td>
                  <td className="px-3 py-2 font-cb-mono text-[10px] text-cb-muted">
                    {fmt(r.amount_delta_qty)} / {fmt(r.amount_delta_rate)}
                  </td>
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

      <VarianceDrawer record={detail} reasonCodes={reasonCodes} onClose={() => setDetail(null)} />
    </div>
  );
}

// The variance record: the full rate-primary picture for one line — tender vs outturn, the
// qty-driven / rate-driven decomposition, the confirmed reason, and provenance. Navy accent:
// everything in here is Layer-1 arithmetic and a human-confirmed reason. Nothing in this
// drawer was written by a model, and it must not look as though it were.
function VarianceDrawer({
  record,
  reasonCodes,
  onClose,
}: {
  record: VarianceRecord | null;
  reasonCodes: ReasonCode[];
  onClose: () => void;
}) {
  const r = record;
  const reasonLabel = (code: string) => reasonCodes.find((c) => c.code === code)?.label ?? code;
  return (
    <Drawer
      open={r != null}
      onClose={onClose}
      eyebrow="Variance record"
      accent="bg-cb-navy"
      title={r ? r.item_ref || "(coarse line)" : ""}
      subtitle={
        r && (
          <span className="font-cb-mono">
            {r.granularity} granularity{r.match_tier != null ? ` · match tier ${r.match_tier}` : ""}
          </span>
        )
      }
      footer="Variance math is Layer 1 and every record is written only by the human confirm gate — Claude (Layer 2) reads, never a number or a reason."
    >
      {r && (
        <div className="space-y-3">
          <div>
            <SectionLabel className="mb-1.5">Tender vs outturn</SectionLabel>
            <div className="grid grid-cols-2 gap-2">
              <div className="rounded-cb-card border border-cb-border bg-cb-panel px-4 py-3">
                <SectionLabel>Tender rate</SectionLabel>
                <div className="mt-0.5 font-cb-mono text-[15px] font-semibold text-cb-body">
                  {fmt(r.tender_rate)}
                </div>
              </div>
              <div className="rounded-cb-card border border-cb-border bg-cb-panel px-4 py-3">
                <SectionLabel>Actual rate</SectionLabel>
                <div className="mt-0.5 font-cb-mono text-[15px] font-semibold text-cb-ink-text">
                  {fmt(r.actual_rate)}
                </div>
              </div>
            </div>
            <div className="mt-1.5 flex flex-wrap items-center gap-2">
              <DeltaTag value={r.rate_delta} label="rate" />
              {r.rate_delta_pct != null && (
                <span className="font-cb-mono text-[10px] text-cb-faint">{fmt(r.rate_delta_pct)}%</span>
              )}
            </div>
          </div>

          <div className="space-y-1.5">
            <Collapse title="Quantities & amounts" defaultOpen>
              <table className="w-full">
                <tbody>
                  {[
                    ["Quantity", r.tender_qty, r.actual_qty],
                    ["Amount", r.tender_amount, r.actual_amount],
                  ].map(([label, t, a]) => (
                    <tr key={String(label)} className="border-b border-cb-divider last:border-0">
                      <td className="py-1.5 font-cb-sans text-[10.5px] text-cb-faint">{label}</td>
                      <td className="py-1.5 text-right font-cb-mono text-[11px] text-cb-body">
                        {fmt(t as number | null)}
                      </td>
                      <td className="py-1.5 text-center font-cb-mono text-[10px] text-cb-faint">→</td>
                      <td className="py-1.5 text-right font-cb-mono text-[11px] text-cb-ink-text">
                        {fmt(a as number | null)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {r.amount_delta != null && (
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  <DeltaTag value={r.amount_delta} label="amount" />
                  {r.amount_delta_qty != null && r.amount_delta_rate != null && (
                    <span className="font-cb-mono text-[10px] text-cb-faint">
                      qty-driven {fmt(r.amount_delta_qty)} + rate-driven {fmt(r.amount_delta_rate)}
                    </span>
                  )}
                </div>
              )}
            </Collapse>

            <Collapse title="Reason" defaultOpen={!!r.reason_code}>
              {r.reason_code ? (
                // A recorded reason. Green, because a person wrote it — the one thing that
                // separates it from the brass proposal in the table.
                <div className="font-cb-sans text-[11px] leading-relaxed text-cb-body">
                  <span className="font-semibold text-cb-ok-dark">{reasonLabel(r.reason_code)}</span>
                  {r.reason_note && (
                    <p className="mt-1 font-cb-serif italic text-cb-body">“{r.reason_note}”</p>
                  )}
                </div>
              ) : (
                <p className="font-cb-sans text-[11px] text-cb-faint">
                  Not yet tagged — set the reason from the table (a human writes it).
                </p>
              )}
            </Collapse>
          </div>

          <Docket
            label="Provenance"
            code={
              <span className="text-[12px]">
                {r.source}
                {r.tagged_by ? ` · tagged by ${r.tagged_by}` : ""}
                {r.confirmed_at ? ` · confirmed ${r.confirmed_at.slice(0, 10)}` : ""}
              </span>
            }
          />
        </div>
      )}
    </Drawer>
  );
}

// ---------------------------------------------------------------------------
export function Benchmarks({ onError }: { onError: (message: string) => void }) {
  const [projects, setProjects] = useState<BenchmarkProject[]>([]);
  const [summary, setSummary] = useState<BenchmarkSummary | null>(null);
  const [reasonCodes, setReasonCodes] = useState<ReasonCode[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  const fail = (message: string) => {
    setError(message);
    onError(message);
  };

  const loadList = () => {
    api.manage
      .benchmarkProjects()
      .then(setProjects)
      .catch((e: unknown) => fail(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoaded(true));
    api.manage.benchmarkSummary().then(setSummary).catch(() => {});
  };
  useEffect(() => {
    loadList();
    api.manage.reasonCodes().then(setReasonCodes).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const selectedProject = projects.find((p) => p.id === selected) ?? null;

  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto min-w-0 max-w-[1040px] space-y-4 p-[18px]">
        {error && <ErrorNote message={error} onDismiss={() => setError(null)} />}
        {selected != null && selectedProject ? (
          <ProjectDetail
            project={selectedProject}
            reasonCodes={reasonCodes}
            onBack={() => {
              setSelected(null);
              loadList();
            }}
            onChanged={loadList}
            onError={onError}
          />
        ) : !loaded ? (
          <Card>
            <LoadingDots label="Loading projects" />
          </Card>
        ) : (
          <ProjectList
            projects={projects}
            summary={summary}
            onOpen={(id) => setSelected(id)}
            onCreate={(name, trade, contractRef) =>
              api.manage
                .createBenchmarkProject({ name, trade, contract_ref: contractRef })
                .then(() => loadList())
                .catch((e: unknown) => fail(e instanceof Error ? e.message : String(e)))
            }
          />
        )}
      </div>
    </div>
  );
}
