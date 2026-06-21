import type { ChangeEvent } from "react";
import type { DemoCaseSummary, ScopePackages } from "../types";
import { Pill, StepHeading, StepNav } from "../components";
import { Button, Card, cx } from "../ui";
import { tradeLabel } from "../format";

export function StepIngest({
  demoMode,
  demoCases,
  caseId,
  files,
  scope,
  onPickDemo,
  onAddFiles,
  onRemoveFile,
  onRunIngest,
  onContinue,
  loading,
}: {
  demoMode: boolean;
  demoCases: DemoCaseSummary[];
  caseId: string | null;
  files: File[];
  scope: ScopePackages | null;
  onPickDemo: (id: string) => void;
  onAddFiles: (files: File[]) => void;
  onRemoveFile: (i: number) => void;
  onRunIngest: () => void;
  onContinue: () => void;
  loading: boolean;
}) {
  function onFileInput(e: ChangeEvent<HTMLInputElement>) {
    const picked = Array.from(e.target.files ?? []);
    if (picked.length) onAddFiles(picked);
    e.target.value = "";
  }

  const blockedInDemo = demoMode && !caseId;
  const canIngest = !blockedInDemo && (!!caseId || files.length > 0);

  return (
    <div className="space-y-6">
      <StepHeading
        title="Ingest the tender"
        lead="Choose a demo tender or upload the four documents (Method of Measurement, Particular Specification, Tender Addendum, Schedule of Rates). Claude reads them and splits the work into one package per trade; the rules engine validates each trade against the taxonomy."
      />

      <Card className="p-5">
        <label className="mb-2 block text-sm font-semibold text-ink">Choose a scenario</label>
        <p className="mb-3 text-xs text-ink-faint">
          {demoMode
            ? "Demo mode is offline — each scenario runs the whole pipeline against the seeded database and reproduces identically."
            : "Prepared scenarios — handy to see the flow end to end."}
        </p>
        <div className="grid gap-2 sm:grid-cols-3">
          {demoCases.map((c) => (
            <button
              key={c.id}
              type="button"
              onClick={() => onPickDemo(c.id)}
              className={cx(
                "flex flex-col rounded-lg border px-3 py-3 text-left transition-colors",
                caseId === c.id ? "border-brand bg-brand-bg" : "border-line bg-card hover:bg-line-soft",
              )}
            >
              <span className={cx("text-sm font-semibold", caseId === c.id ? "text-brand" : "text-ink")}>{c.name}</span>
              <span className="mt-1 text-xs leading-relaxed text-ink-soft">{c.blurb}</span>
              <span className="mt-2 text-[11px] uppercase tracking-wide text-ink-faint">{tradeLabel(c.hero_trade)}</span>
            </button>
          ))}
          {demoCases.length === 0 && (
            <span className="text-sm text-ink-faint">No scenarios — is the backend running on :8000?</span>
          )}
        </div>
      </Card>

      <Card className="p-5">
        <span className="mb-2 block text-sm font-semibold text-ink">
          Or upload the tender documents <span className="font-normal text-ink-faint">(live extraction)</span>
        </span>
        <label className="flex cursor-pointer items-center justify-center rounded-lg border border-dashed border-line bg-paper/50 px-4 py-5 text-sm text-ink-soft hover:border-brand hover:text-brand">
          <input type="file" multiple accept="application/pdf,image/*" className="sr-only" onChange={onFileInput} />
          Choose files — the four tender documents (PDF, JPEG, PNG)
        </label>
        {files.length > 0 && (
          <ul className="mt-3 space-y-1.5">
            {files.map((f, i) => (
              <li key={`${f.name}-${i}`} className="flex items-center justify-between rounded-md border border-line-soft bg-paper/50 px-3 py-1.5 text-sm">
                <span className="truncate text-ink">{f.name}</span>
                <button type="button" onClick={() => onRemoveFile(i)} className="ml-3 shrink-0 text-xs font-medium text-ink-faint hover:text-bad">
                  Remove
                </button>
              </li>
            ))}
          </ul>
        )}
        {demoMode && files.length > 0 && (
          <p className="mt-2 text-xs text-warn">Demo mode is offline — uploads are accepted but the seeded tender is returned. Turn DEMO_MODE off for live extraction.</p>
        )}
      </Card>

      {blockedInDemo && (
        <p className="text-sm text-warn">Pick a demo tender above to continue — live extraction is off in demo mode.</p>
      )}

      <div className="flex justify-end">
        <Button onClick={onRunIngest} loading={loading && !scope} disabled={!canIngest}>
          Split the tender →
        </Button>
      </div>

      {scope && (
        <Card className="overflow-hidden">
          <div className="flex items-center justify-between border-b border-line-soft px-4 py-2.5">
            <h2 className="text-sm font-semibold text-ink">{scope.project_name}</h2>
            <Pill tone="brand">{scope.packages.length} trades</Pill>
          </div>
          <ul className="divide-y divide-line-soft">
            {scope.packages.map((pkg) => (
              <li key={pkg.trade} className="px-4 py-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-semibold text-ink">{tradeLabel(pkg.trade)}</span>
                  <Pill>{pkg.sor_items.length} SoR items</Pill>
                  {pkg.source_refs.map((ref) => (
                    <span key={ref} className="tabular text-xs text-ink-faint">{ref}</span>
                  ))}
                </div>
                <p className="mt-1 text-sm text-ink-soft">{pkg.scope_summary}</p>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {scope && <StepNav onNext={onContinue} nextLabel="Shortlist subcontractors →" loading={loading} />}
    </div>
  );
}
