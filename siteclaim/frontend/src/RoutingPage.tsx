import { useEffect, useState } from "react";

import { api } from "./api";
import { Pill } from "./components";
import type { DemoCaseSummary, RouteDecision, RouteDecisionResult, RouteProposal, ScopePackages } from "./types";
import { Button, Card, ErrorBanner, LayerBadge, SectionHeader } from "./ui";

const ROUTE_LABEL: Record<string, string> = { self_perform: "Self-perform", sublet: "Sublet" };

function tradeLabel(t: string): string {
  return t.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function SignalChips({ signals }: { signals: Record<string, number | boolean | string> }) {
  const chip = (label: string, key: string) =>
    signals[key] !== undefined ? <Pill key={key} tone="neutral">{`${label}: ${String(signals[key])}`}</Pill> : null;
  return (
    <div className="flex flex-wrap gap-1.5">
      {chip("register firms", "trade_firm_count")}
      {chip("assessable", "assessable_firm_count")}
      {chip("in-house", "in_house_history")}
      {signals.thin_pool ? <Pill tone="violet">thin pool</Pill> : null}
    </div>
  );
}

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
        <>
          <div className="flex items-center justify-between">
            <p className="text-sm text-ink-soft">
              <span className="tabular">{proposal.run_ref}</span> · {proposal.packages.length} packages
            </p>
            <div className="flex items-center gap-2">
              <Button variant="subtle" onClick={acceptAll}>Accept all recommended</Button>
              <Button loading={busy} onClick={confirm}>Confirm routing</Button>
            </div>
          </div>

          <div className="space-y-2">
            {proposal.packages.map((p) => {
              const pick = chosen[p.package_key] ?? p.recommended_route;
              return (
                <Card key={p.package_key} className="p-4">
                  <div className="flex flex-wrap items-start gap-3">
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="font-semibold text-ink">{tradeLabel(p.trade)}</span>
                        <Pill tone="ok">{`Recommended: ${ROUTE_LABEL[p.recommended_route] ?? p.recommended_route}`}</Pill>
                        {p.source === "fallback" && <Pill tone="neutral">rule-based</Pill>}
                      </div>
                      <p className="mt-1 text-sm text-ink-soft">{p.rationale}</p>
                      {p.scope_summary && <p className="mt-1 text-xs text-ink-faint">{p.scope_summary}</p>}
                      <div className="mt-2"><SignalChips signals={p.signals} /></div>
                    </div>
                    <div className="flex overflow-hidden rounded-lg border border-line">
                      {["self_perform", "sublet"].map((r) => (
                        <button
                          key={r}
                          onClick={() => setChosen((cur) => ({ ...cur, [p.package_key]: r }))}
                          className={
                            "px-3 py-1.5 text-sm font-semibold transition-colors " +
                            (pick === r ? "bg-brand text-white" : "bg-card text-ink-soft hover:bg-line-soft")
                          }
                        >
                          {ROUTE_LABEL[r]}
                        </button>
                      ))}
                    </div>
                  </div>
                </Card>
              );
            })}
          </div>
        </>
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
