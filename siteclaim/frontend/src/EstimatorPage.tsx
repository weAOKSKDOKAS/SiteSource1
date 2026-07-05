import { useEffect, useState } from "react";

import { api } from "./api";
import { Pill, StepHeading } from "./components";
import { money, tradeLabel } from "./format";
import type {
  EstimateCheckResult,
  EstimateFinding,
  EstimateItem,
  EstimateProject,
  LetterOfOffer,
  RatePrecedent,
  RateSuggestions,
} from "./types";
import { Button, Card, ErrorBanner, LayerBadge, SectionHeader, StatCallout } from "./ui";

// ---------------------------------------------------------------------------
// Rate precedent — from the benchmark corpus (Layer 3). Suggestion only; the person prices.
// ---------------------------------------------------------------------------
function PrecedentCell({ p, corpusEmpty }: { p: RatePrecedent | undefined; corpusEmpty: boolean }) {
  if (corpusEmpty) return <span className="text-xs italic text-ink-faint">no corpus yet</span>;
  if (!p || p.tier === 0) return <span className="text-xs italic text-ink-faint">no precedent</span>;
  return (
    <div className="space-y-1">
      <div className="flex flex-wrap items-center gap-1.5">
        <Pill tone={p.tier === 1 ? "violet" : "brand"}>
          {p.tier === 1 ? "exact ref" : `~${Math.round((p.similarity || 0) * 100)}% ${p.matched_ref}`}
        </Pill>
        <span className="tabular text-xs text-ink-soft">
          {money(p.rate_median)}
          {p.sample_count > 1 ? ` · n=${p.sample_count}` : ""}
        </span>
      </div>
      {p.rate_warnings.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {p.rate_warnings.map((w, i) => (
            <Pill key={i} tone="warn">{`over-ran on rate: ${w.reason_code}`}</Pill>
          ))}
        </div>
      )}
    </div>
  );
}

// An inline numeric editor — the person prices/quantifies; commits on blur.
function NumCell({ value, onCommit }: { value: number | null; onCommit: (v: number | null) => void }) {
  const [text, setText] = useState(value === null || value === undefined ? "" : String(value));
  useEffect(() => setText(value === null || value === undefined ? "" : String(value)), [value]);
  return (
    <input
      className="tabular w-20 rounded border border-line px-1.5 py-1 text-right text-xs focus:border-brand focus:outline-none"
      value={text}
      inputMode="decimal"
      onChange={(e) => setText(e.target.value)}
      onBlur={() => {
        const t = text.trim();
        const next = t === "" ? null : Number(t);
        if (next !== null && Number.isNaN(next)) { setText(value === null ? "" : String(value)); return; }
        if (next !== value) onCommit(next);
      }}
    />
  );
}

// ---------------------------------------------------------------------------
// Findings + letter panels
// ---------------------------------------------------------------------------
function FindingsPanel({ result }: { result: EstimateCheckResult }) {
  const tone = (f: EstimateFinding) => (f.severity === "warning" ? "warn" : "neutral");
  return (
    <Card className="p-4">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <h3 className="text-sm font-semibold text-ink">Error &amp; omission check</h3>
        <LayerBadge layer="L1" />
        <span className="text-xs text-ink-faint">
          {result.findings.length} finding(s) · rubric {result.rubric_size === 0 ? "empty (no archive yet)" : result.rubric_size}
        </span>
      </div>
      {result.findings.length === 0 ? (
        <p className="text-sm text-ink-faint">No issues flagged.</p>
      ) : (
        <ul className="space-y-1.5">
          {result.findings.map((f, i) => (
            <li key={i} className="flex flex-wrap items-center gap-2 text-sm">
              <Pill tone={tone(f)}>{f.kind.replace(/_/g, " ")}</Pill>
              {f.item_ref && <span className="tabular text-xs text-ink-faint">{f.item_ref}</span>}
              <span className="text-ink-soft">{f.message}</span>
            </li>
          ))}
        </ul>
      )}
      <p className="mt-2 text-xs text-ink-faint">The check reports; it never edits or prices. You act on the findings.</p>
    </Card>
  );
}

function LetterPanel({ letter }: { letter: LetterOfOffer }) {
  const List = ({ title, items }: { title: string; items: string[] }) =>
    items.length ? (
      <div>
        <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-ink-faint">{title}</div>
        <ul className="list-disc space-y-0.5 pl-5 text-sm text-ink-soft">
          {items.map((x, i) => <li key={i}>{x}</li>)}
        </ul>
      </div>
    ) : null;
  return (
    <Card className="p-4">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <h3 className="text-sm font-semibold text-ink">Letter of offer</h3>
        <LayerBadge layer="L2" />
        <Pill tone="warn">draft — you own the final letter</Pill>
      </div>
      <div className="font-display text-base font-semibold text-ink">{letter.subject}</div>
      <p className="mt-1 whitespace-pre-line text-sm text-ink-soft">{letter.body}</p>
      <div className="mt-3 grid gap-3 sm:grid-cols-3">
        <List title="Inclusions" items={letter.inclusions} />
        <List title="Exclusions" items={letter.exclusions} />
        <List title="Assumptions" items={letter.assumptions} />
      </div>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Estimate detail
// ---------------------------------------------------------------------------
function EstimateDetail({ project, onBack, onChanged }: { project: EstimateProject; onBack: () => void; onChanged: () => void }) {
  const id = project.id;
  const [items, setItems] = useState<EstimateItem[]>([]);
  const [rates, setRates] = useState<RateSuggestions | null>(null);
  const [check, setCheck] = useState<EstimateCheckResult | null>(null);
  const [letter, setLetter] = useState<LetterOfOffer | null>(null);
  const [scope, setScope] = useState(project.scope_of_works);
  const [newRef, setNewRef] = useState("");
  const [newDesc, setNewDesc] = useState("");
  const [newUnit, setNewUnit] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = (p: Promise<unknown>) => {
    setBusy(true); setError(null);
    p.then(() => { loadItems(); loadRates(); onChanged(); })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setBusy(false));
  };
  const loadItems = () => api.estimateItems(id).then(setItems).catch(() => {});
  const loadRates = () => api.estimateRateSuggestions(id).then(setRates).catch(() => {});
  useEffect(() => { loadItems(); loadRates(); setScope(project.scope_of_works); /* eslint-disable-next-line */ }, [id]);

  const rateFor = (itemId: number): RatePrecedent | undefined => rates?.suggestions.find((s) => s.item_id === itemId);
  const priceItem = (itemId: number, field: "qty" | "rate", v: number | null) => run(api.patchEstimateItem(id, itemId, { [field]: v }));
  const removeItem = (itemId: number) => run(api.deleteEstimateItem(id, itemId));
  const addItem = () => {
    if (!newRef.trim()) return;
    run(api.addEstimateItems(id, [{ item_ref: newRef.trim(), description: newDesc.trim(), unit: newUnit.trim() }]));
    setNewRef(""); setNewDesc(""); setNewUnit("");
  };
  const saveScope = () => run(api.patchEstimate(id, { scope_of_works: scope }));
  const draft = () => run(api.draftEstimate(id).then((r) => setScope(r.estimate.scope_of_works)));
  const doCheck = () => { setBusy(true); setError(null); api.checkEstimate(id).then(setCheck).catch((e: unknown) => setError(e instanceof Error ? e.message : String(e))).finally(() => setBusy(false)); };
  const doLetter = () => { setBusy(true); setError(null); api.estimateLetter(id).then(setLetter).catch((e: unknown) => setError(e instanceof Error ? e.message : String(e))).finally(() => setBusy(false)); };

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-3">
        <Button variant="subtle" onClick={onBack}>← Estimates</Button>
        <h2 className="font-display text-base font-semibold text-ink">{project.name}</h2>
        {project.trade && <Pill tone="violet">{tradeLabel(project.trade)}</Pill>}
        <Pill tone={project.status === "draft" ? "neutral" : "ok"}>{project.status}</Pill>
      </div>
      {error && <ErrorBanner message={error} />}

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatCallout label="Lines" value={project.item_count} />
        <StatCallout label="Priced" value={`${project.priced_item_count}/${project.item_count}`} />
        <StatCallout label="Total" value={money(project.total)} tone="brand" hint="computable amounts only" />
        <StatCallout label="Rate corpus" value={rates ? (rates.corpus_empty ? "empty" : rates.corpus_size) : "—"} tone="violet" />
      </div>

      <Card className="p-4">
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <h3 className="text-sm font-semibold text-ink">Scope of works</h3>
          <LayerBadge layer="L2" />
          <Button variant="ghost" className="ml-auto" loading={busy} onClick={draft}>Draft with AI</Button>
        </div>
        <textarea
          className="h-24 w-full rounded-lg border border-line px-2 py-1.5 text-sm"
          value={scope}
          onChange={(e) => setScope(e.target.value)}
        />
        <div className="mt-2 flex justify-end">
          <Button variant="subtle" onClick={saveScope} disabled={scope === project.scope_of_works}>Save scope</Button>
        </div>
      </Card>

      <Card className="p-0">
        <div className="flex items-center justify-between border-b border-line-soft px-4 py-2.5">
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-semibold text-ink">Priced schedule</h3>
            <span className="text-xs text-ink-faint">you price every line</span>
          </div>
          <span className="inline-flex items-center gap-1 text-xs text-ink-faint"><LayerBadge layer="L3" /> rate precedent</span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-line-soft text-left text-xs text-ink-faint">
                <th className="px-3 py-2">Item</th>
                <th className="px-3 py-2 text-right">Qty</th>
                <th className="px-3 py-2 text-right">Rate</th>
                <th className="px-3 py-2 text-right">Amount</th>
                <th className="px-3 py-2">Rate precedent</th>
                <th className="px-3 py-2"></th>
              </tr>
            </thead>
            <tbody>
              {items.length === 0 && (
                <tr><td className="px-3 py-3 text-ink-faint" colSpan={6}>No lines yet — draft with AI or add a line below.</td></tr>
              )}
              {items.map((it) => (
                <tr key={it.id} className="border-b border-line-soft last:border-0 align-top">
                  <td className="px-3 py-2">
                    <div className="tabular font-medium text-ink">{it.item_ref}</div>
                    <div className="text-xs text-ink-faint">{it.description}{it.unit ? ` · ${it.unit}` : ""}</div>
                  </td>
                  <td className="px-3 py-2 text-right"><NumCell value={it.qty} onCommit={(v) => priceItem(it.id, "qty", v)} /></td>
                  <td className="px-3 py-2 text-right"><NumCell value={it.rate} onCommit={(v) => priceItem(it.id, "rate", v)} /></td>
                  <td className="tabular px-3 py-2 text-right text-ink-soft">{money(it.amount)}</td>
                  <td className="px-3 py-2"><PrecedentCell p={rateFor(it.id)} corpusEmpty={rates?.corpus_empty ?? true} /></td>
                  <td className="px-3 py-2 text-right">
                    <button className="text-xs text-ink-faint hover:text-bad" onClick={() => removeItem(it.id)} aria-label="Delete line">✕</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="flex flex-wrap items-end gap-2 border-t border-line-soft px-3 py-2.5">
          <input className="w-24 rounded border border-line px-2 py-1 text-xs" placeholder="item ref" value={newRef} onChange={(e) => setNewRef(e.target.value)} />
          <input className="w-48 rounded border border-line px-2 py-1 text-xs" placeholder="description" value={newDesc} onChange={(e) => setNewDesc(e.target.value)} />
          <input className="w-16 rounded border border-line px-2 py-1 text-xs" placeholder="unit" value={newUnit} onChange={(e) => setNewUnit(e.target.value)} />
          <Button variant="ghost" disabled={!newRef.trim()} onClick={addItem}>Add line</Button>
        </div>
      </Card>

      <div className="flex flex-wrap gap-2">
        <Button loading={busy} onClick={doCheck}>Check estimate</Button>
        <Button variant="ghost" loading={busy} onClick={doLetter}>Draft letter of offer</Button>
      </div>

      {check && <FindingsPanel result={check} />}
      {letter && <LetterPanel letter={letter} />}
    </div>
  );
}

// ---------------------------------------------------------------------------
function EstimateList({ projects, onOpen, onCreate }: {
  projects: EstimateProject[];
  onOpen: (id: number) => void;
  onCreate: (name: string, trade: string) => void;
}) {
  const [name, setName] = useState("");
  const [trade, setTrade] = useState("ground_investigation");
  return (
    <div className="space-y-5">
      <StepHeading
        title="Estimator — self-perform"
        lead="Build our own priced tender for a self-perform package: draft the scope and skeleton, price against corpus precedent, check for omissions, and draft a letter of offer. You price every line and own the offer."
      />

      <Card className="p-4">
        <h3 className="mb-2 text-sm font-semibold text-ink">New estimate</h3>
        <div className="flex flex-wrap items-end gap-2">
          <label className="text-xs text-ink-soft">
            Name
            <input className="mt-1 block w-56 rounded-lg border border-line px-2 py-1.5 text-sm" value={name} onChange={(e) => setName(e.target.value)} placeholder="GI Term Contract 2026" />
          </label>
          <label className="text-xs text-ink-soft">
            Trade
            <input className="mt-1 block w-44 rounded-lg border border-line px-2 py-1.5 text-sm" value={trade} onChange={(e) => setTrade(e.target.value)} />
          </label>
          <Button disabled={!name.trim()} onClick={() => { onCreate(name.trim(), trade.trim()); setName(""); }}>Create</Button>
        </div>
      </Card>

      <div className="space-y-2">
        {projects.length === 0 && <p className="text-sm text-ink-faint">No estimates yet — create one, or route a package to self-perform from the Routing screen.</p>}
        {projects.map((p) => (
          <Card key={p.id} className="flex flex-wrap items-center gap-3 p-4">
            <button className="text-left" onClick={() => onOpen(p.id)}>
              <div className="flex items-center gap-2">
                <span className="text-sm font-semibold text-ink hover:text-brand">{p.name}</span>
                {p.source === "routing" && <Pill tone="brand">routed</Pill>}
                <Pill tone={p.status === "draft" ? "neutral" : "ok"}>{p.status}</Pill>
              </div>
              <div className="text-xs text-ink-faint">{[p.contract_ref, tradeLabel(p.trade)].filter(Boolean).join(" · ")}</div>
            </button>
            <div className="ml-auto flex items-center gap-1.5">
              <Pill tone="neutral">{`${p.priced_item_count}/${p.item_count} priced`}</Pill>
              <Pill tone="brand">{money(p.total)}</Pill>
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
}

export function EstimatorPage() {
  const [projects, setProjects] = useState<EstimateProject[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = () => api.estimateProjects().then(setProjects).catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  useEffect(() => { load(); }, []);

  const selectedProject = projects.find((p) => p.id === selected) ?? null;

  return (
    <div className="min-w-0 space-y-4">
      <SectionHeader
        title="Estimator"
        lead="The left track — our own priced tender. The AI drafts, suggests precedent, and checks; the human prices every line and owns the offer."
        right={<LayerBadge layer="L4" />}
      />
      {error && <ErrorBanner message={error} />}
      {selected != null && selectedProject ? (
        <EstimateDetail project={selectedProject} onBack={() => { setSelected(null); load(); }} onChanged={load} />
      ) : (
        <EstimateList
          projects={projects}
          onOpen={(id) => setSelected(id)}
          onCreate={(name, trade) => api.createEstimate({ name, trade }).then(() => load()).catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))}
        />
      )}
    </div>
  );
}
