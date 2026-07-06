import { useState } from "react";

import { Pill } from "./components";
import { tradeLabel } from "./format";
import type { RoutePackage, RouteProposal, ScopePackages, SorItem } from "./types";
import { Button, Card, Collapse, Drawer, MonoLabel, ScanLine } from "./ui";

export const ROUTE_LABEL: Record<string, string> = { self_perform: "Self-perform", sublet: "Sublet" };

// The SoR lines behind a routing card — for a section sub-package (package_key trade:SECTION)
// just that section's items; for a whole package all of them. Drawn from the ingest scope the
// panel already holds, so the operator can expand a section and see its items (J1, J2, J3 …).
function itemsFor(p: RoutePackage, scope: ScopePackages | null | undefined): SorItem[] {
  const pkg = scope?.packages.find((x) => x.trade === p.trade);
  if (!pkg) return [];
  return p.section ? pkg.sor_items.filter((it) => (it.section ?? "") === p.section) : pkg.sor_items;
}

// A section header title is stored upper-case (DRILLING); show it in title case.
function titleCase(s: string): string {
  return s.replace(/\w\S*/g, (w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase());
}

export function SignalChips({ signals }: { signals: Record<string, number | boolean | string> }) {
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

// The per-package route decision UI, shared by the standalone Routing tab and the wizard's
// Route step: one card per package with the routing recommendation, its coverage signal, and a
// self-perform/sublet toggle the person sets. `chosen` + `onChoose` are owned by the parent
// (so the parent can build the decisions on confirm); the detail drawer is self-contained.
export function RouteDecisionPanel({
  proposal,
  chosen,
  onChoose,
  onAcceptAll,
  onConfirm,
  busy,
  confirmLabel = "Confirm routing",
  scope,
}: {
  proposal: RouteProposal;
  chosen: Record<string, string>;
  onChoose: (packageKey: string, route: string) => void;
  onAcceptAll: () => void;
  onConfirm: () => void;
  busy: boolean;
  confirmLabel?: string;
  scope?: ScopePackages | null; // the ingest scope — used to expand a section's SoR items
}) {
  const [detail, setDetail] = useState<RoutePackage | null>(null);

  return (
    <>
      <div className="relative flex items-center justify-between">
        <ScanLine active={busy} />
        <p className="text-sm text-ink-soft">
          <span className="tabular">{proposal.run_ref}</span> · {proposal.packages.length} packages
        </p>
        <div className="flex items-center gap-2">
          <Button variant="subtle" onClick={onAcceptAll}>Accept all recommended</Button>
          <Button loading={busy} onClick={onConfirm}>{confirmLabel}</Button>
        </div>
      </div>

      <div className="space-y-2">
        {proposal.packages.map((p, i) => {
          const pick = chosen[p.package_key] ?? p.recommended_route;
          const items = itemsFor(p, scope);
          const heading = p.section
            ? `${tradeLabel(p.trade)} · ${p.section_title ? titleCase(p.section_title) : `Section ${p.section}`}`
            : tradeLabel(p.trade);
          return (
            // ssStep (declared after ssRise in index.css) wins the cascade so the package
            // rows step in sequentially; the stagger comes from the per-row delay.
            <Card key={p.package_key} className="ssStep p-4" style={{ animationDelay: `${i * 45}ms` }}>
              <div className="flex flex-wrap items-start gap-3">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={() => setDetail(p)}
                      title="Open the routing record"
                      className="font-semibold text-ink hover:text-brand focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-bright"
                    >
                      {heading}
                    </button>
                    {p.section && <span className="tabular text-[11px] text-ink-faint">{p.package_key}</span>}
                    <Pill tone="ok">{`Recommended: ${ROUTE_LABEL[p.recommended_route] ?? p.recommended_route}`}</Pill>
                    {p.source === "fallback" && <Pill tone="neutral">rule-based</Pill>}
                  </div>
                  <p className="mt-1 text-sm text-ink-soft">{p.rationale}</p>
                  {p.scope_summary && <p className="mt-1 text-xs text-ink-faint">{p.scope_summary}</p>}
                  <div className="mt-2"><SignalChips signals={p.signals} /></div>
                  {items.length > 0 && (
                    <div className="mt-2">
                      <Collapse title={p.section ? `Section ${p.section} items` : "SoR items"} count={items.length}>
                        <ul className="space-y-1">
                          {items.map((it) => (
                            <li key={it.item_ref} className="flex gap-2 text-xs leading-relaxed">
                              <span className="tabular shrink-0 font-semibold text-ink">{it.item_ref}</span>
                              <span className="text-ink-soft">{it.description}</span>
                            </li>
                          ))}
                        </ul>
                      </Collapse>
                    </div>
                  )}
                </div>
                <div className="flex overflow-hidden rounded-lg border border-line">
                  {["self_perform", "sublet"].map((r) => (
                    <button
                      key={r}
                      onClick={() => onChoose(p.package_key, r)}
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

      <PackageDrawer pkg={detail} onClose={() => setDetail(null)} />
    </>
  );
}

// The routing record for one package: the tendered scope, the routing recommendation with its
// rationale and deterministic signal, and the human decision (with provenance) once made.
function PackageDrawer({ pkg, onClose }: { pkg: RoutePackage | null; onClose: () => void }) {
  return (
    <Drawer
      open={pkg != null}
      onClose={onClose}
      eyebrow="Routing record"
      tone="warn"
      title={pkg ? tradeLabel(pkg.trade) : ""}
      subtitle={pkg && <span className="tabular">{pkg.package_key}</span>}
      footer="The recommendation is advisory — the human decision (decided-by, decided-at) is the record of truth."
    >
      {pkg && (
        <div className="space-y-3">
          {pkg.scope_summary && <p className="text-xs leading-relaxed text-ink-soft">{pkg.scope_summary}</p>}

          <div>
            <Collapse title="Recommendation (advisory)" defaultOpen>
              <div className="flex flex-wrap items-center gap-1.5">
                <Pill tone="ok">{ROUTE_LABEL[pkg.recommended_route] ?? pkg.recommended_route}</Pill>
                <Pill tone="neutral">{pkg.source === "fallback" ? "rule-based" : pkg.source}</Pill>
              </div>
              {pkg.rationale && <p className="mt-1.5 text-xs leading-relaxed text-ink-soft">{pkg.rationale}</p>}
            </Collapse>

            <Collapse title="Coverage signal (Layer 1)" defaultOpen>
              <SignalChips signals={pkg.signals} />
            </Collapse>

            <Collapse title="Human decision" defaultOpen={!!pkg.chosen_route}>
              {pkg.chosen_route ? (
                <div className="text-xs leading-relaxed text-ink-soft">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <Pill tone={pkg.chosen_route === "self_perform" ? "violet" : "brand"}>
                      {ROUTE_LABEL[pkg.chosen_route] ?? pkg.chosen_route}
                    </Pill>
                    {pkg.chosen_route !== pkg.recommended_route && <Pill tone="warn">override</Pill>}
                  </div>
                  <MonoLabel className="mt-2">Decided by</MonoLabel>
                  <div className="tabular text-ink">{pkg.decided_by}{pkg.decided_at ? ` · ${pkg.decided_at.slice(0, 10)}` : ""}</div>
                </div>
              ) : (
                <p className="text-xs text-ink-faint">Not decided yet — set the toggle and confirm routing.</p>
              )}
            </Collapse>
          </div>
        </div>
      )}
    </Drawer>
  );
}
