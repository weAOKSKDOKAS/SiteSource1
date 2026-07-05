import { useEffect, useState } from "react";

import { api } from "./api";
import { Pill } from "./components";
import { tradeLabel } from "./format";
import { RouteDecisionPanel } from "./RouteDecisionPanel";
import type { DemoCaseSummary, RouteDecision, RouteDecisionResult, RouteProposal, ScopePackages } from "./types";
import { Button, Card, ErrorBanner, LayerBadge, SectionHeader } from "./ui";

export function RoutingPage() {
  const [cases, setCases] = useState<DemoCaseSummary[]>([]);
  const [scope, setScope] = useState<ScopePackages | null>(null);
  const [proposal, setProposal] = useState<RouteProposal | null>(null);
  const [chosen, setChosen] = useState<Record<string, string>>({});
  const [result, setResult] = useState<RouteDecisionResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.demoCases().then(setCases).catch(() => {});
  }, []);

  const analyzeCase = (caseId: string) => {
    setBusy(true);
    setError(null);
    setResult(null);
    api
      .demoCase(caseId)
      .then((c) => api.ingest(c.tender))
      .then((s: ScopePackages) => {
        setScope(s); // kept so confirm can auto-seed the self-perform estimates (P4b)
        return api.routeAnalyze(s);
      })
      .then((p) => {
        setProposal(p);
        setChosen(Object.fromEntries(p.packages.map((pkg) => [pkg.package_key, pkg.recommended_route])));
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setBusy(false));
  };

  const confirm = () => {
    if (!proposal) return;
    setBusy(true);
    setError(null);
    const decisions: RouteDecision[] = proposal.packages.map((p) => ({
      package_key: p.package_key,
      chosen_route: chosen[p.package_key] ?? p.recommended_route,
    }));
    api
      .routeConfirm(proposal.run_ref, decisions, "operator", scope)
      .then(setResult)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setBusy(false));
  };

  const acceptAll = () =>
    proposal && setChosen(Object.fromEntries(proposal.packages.map((p) => [p.package_key, p.recommended_route])));

  return (
    <div className="min-w-0 space-y-5">
      <SectionHeader
        title="Routing gate"
        lead="After the tender splits into packages, the AI recommends self-perform vs sublet per package. A person decides — the recommendation is advisory."
        right={<LayerBadge layer="L4" />}
      />
      {error && <ErrorBanner message={error} />}

      <Card className="flex flex-wrap items-center gap-2 p-4">
        <span className="text-sm font-medium text-ink-soft">Analyse a tender:</span>
        {cases.map((c) => (
          <Button key={c.id} variant="ghost" loading={busy} onClick={() => analyzeCase(c.id)}>
            {c.name}
          </Button>
        ))}
      </Card>

      {proposal && (
        <RouteDecisionPanel
          proposal={proposal}
          chosen={chosen}
          onChoose={(key, route) => setChosen((cur) => ({ ...cur, [key]: route }))}
          onAcceptAll={acceptAll}
          onConfirm={confirm}
          busy={busy}
        />
      )}

      {result && (
        <Card className="p-4">
          <h3 className="mb-2 font-display text-base font-semibold text-ink">Routed</h3>
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-ink-faint">Sublet → Sourcing (right track)</div>
              {result.sublet_packages.length ? (
                <div className="flex flex-wrap gap-1.5">{result.sublet_packages.map((k) => <Pill key={k} tone="brand">{tradeLabel(k)}</Pill>)}</div>
              ) : <p className="text-sm text-ink-faint">none</p>}
            </div>
            <div>
              <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-ink-faint">Self-perform → Estimator (left track)</div>
              {result.self_perform_packages.length ? (
                <div className="flex flex-wrap gap-1.5">{result.self_perform_packages.map((k) => <Pill key={k} tone="violet">{tradeLabel(k)}</Pill>)}</div>
              ) : <p className="text-sm text-ink-faint">none</p>}
            </div>
          </div>
          <p className="mt-3 text-xs text-ink-faint">
            The decision is the record of truth (decided by {result.packages[0]?.decided_by || "operator"}). Sublet packages
            continue to the shortlist;{" "}
            {Object.keys(result.estimate_ids).length > 0
              ? `${Object.keys(result.estimate_ids).length} self-perform estimate(s) have opened in the Estimator tab.`
              : "self-perform packages open in the Estimator tab."}
          </p>
        </Card>
      )}
    </div>
  );
}
