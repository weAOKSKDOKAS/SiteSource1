import { useEffect, useState } from "react";

import { api } from "./api";
import { Pill } from "./components";
import { money, tradeLabel } from "./format";
import type { ProjectDashboard, ProjectSummary } from "./types";
import { Card, ErrorBanner, SectionHeader, StatCallout, cx } from "./ui";

function TrackBadge({ track, chosen }: { track: string; chosen: string | null }) {
  if (track === "left") return <Pill tone="violet">Self-perform → Estimator</Pill>;
  if (track === "right") return <Pill tone="brand">Sublet → Sourcing</Pill>;
  return <Pill tone="neutral">{chosen ?? "undecided"}</Pill>;
}

// The lifecycle strip — where the project sits: analysed → routed → (left estimating /
// right sourcing) → benchmarked. A stage lights up once its state is reached.
function Lifecycle({ dash }: { dash: ProjectDashboard }) {
  const routed = dash.packages.some((p) => p.chosen_route);
  const left = dash.estimates.length > 0;
  const awarded = dash.estimates.some((e) => e.status === "awarded");
  const right = dash.packages.some((p) => p.track === "right");
  const benchmarked = dash.benchmark_project_id != null;
  const stages: { label: string; on: boolean }[] = [
    { label: "Analysed", on: true },
    { label: "Routed", on: routed },
    { label: right ? "Sourcing" : "Left track", on: left || right },
    { label: awarded ? "Awarded" : "Estimating", on: left },
    { label: "Benchmarked", on: benchmarked },
  ];
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {stages.map((s, i) => (
        <span key={i} className="flex items-center gap-1.5">
          <span
            className={cx(
              "rounded-full px-2.5 py-1 text-xs font-semibold",
              s.on ? "bg-brand-bg text-brand" : "bg-line-soft text-ink-faint",
            )}
          >
            {s.label}
          </span>
          {i < stages.length - 1 && <span className="text-ink-faint">→</span>}
        </span>
      ))}
    </div>
  );
}

function DashboardView({ dash, onBack }: { dash: ProjectDashboard; onBack: () => void }) {
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-3">
        <button className="text-sm font-semibold text-ink-soft hover:text-ink" onClick={onBack}>← Projects</button>
        <h2 className="font-display text-base font-semibold text-ink">{dash.name || dash.run_ref}</h2>
        <span className="tabular text-xs text-ink-faint">{dash.run_ref}</span>
        {dash.provenance === "demo" && <Pill tone="neutral">Illustrative</Pill>}
      </div>

      <Card className="p-4">
        <div className="mb-2 text-xs font-semibold uppercase tracking-eyebrow text-ink-faint">Lifecycle</div>
        <Lifecycle dash={dash} />
      </Card>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatCallout label="Packages" value={dash.packages.length} />
        <StatCallout label="Self-perform" value={dash.packages.filter((p) => p.track === "left").length} tone="violet" />
        <StatCallout label="Sublet" value={dash.packages.filter((p) => p.track === "right").length} tone="brand" />
        <StatCallout label="Benchmarked" value={dash.benchmark_project_id != null ? `#${dash.benchmark_project_id}` : "—"} tone="ok" />
      </div>

      <Card className="p-0">
        <div className="border-b border-line-soft px-4 py-2.5">
          <h3 className="text-sm font-semibold text-ink">Packages</h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-line-soft text-left text-xs text-ink-faint">
                <th className="px-3 py-2">Trade</th>
                <th className="px-3 py-2">Recommended</th>
                <th className="px-3 py-2">Decision</th>
                <th className="px-3 py-2">Track</th>
              </tr>
            </thead>
            <tbody>
              {dash.packages.length === 0 && (
                <tr><td className="px-3 py-3 text-ink-faint" colSpan={4}>No routing analysed for this run yet.</td></tr>
              )}
              {dash.packages.map((p) => (
                <tr key={p.package_key} className="border-b border-line-soft last:border-0">
                  <td className="px-3 py-2">
                    <div className="font-medium text-ink">{tradeLabel(p.trade || p.package_key)}</div>
                    {p.scope_summary && <div className="text-xs text-ink-faint">{p.scope_summary}</div>}
                  </td>
                  <td className="px-3 py-2 text-ink-soft">{p.recommended_route.replace(/_/g, " ") || "—"}</td>
                  <td className="px-3 py-2 text-ink-soft">{p.chosen_route ? p.chosen_route.replace(/_/g, " ") : <span className="text-ink-faint">undecided</span>}</td>
                  <td className="px-3 py-2"><TrackBadge track={p.track} chosen={p.chosen_route} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      {dash.estimates.length > 0 && (
        <Card className="p-0">
          <div className="border-b border-line-soft px-4 py-2.5">
            <h3 className="text-sm font-semibold text-ink">Left track — estimates</h3>
          </div>
          <div className="divide-y divide-line-soft">
            {dash.estimates.map((e) => (
              <div key={e.id} className="flex flex-wrap items-center gap-3 px-4 py-2.5">
                <span className="text-sm font-medium text-ink">{e.name}</span>
                <Pill tone="violet">{tradeLabel(e.trade)}</Pill>
                <Pill tone={e.status === "draft" ? "neutral" : "ok"}>{e.status}</Pill>
                <div className="ml-auto flex items-center gap-1.5">
                  <Pill tone="neutral">{`${e.priced_item_count}/${e.item_count} priced`}</Pill>
                  <Pill tone="brand">{money(e.total)}</Pill>
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}

function ProjectsList({ projects, onOpen }: { projects: ProjectSummary[]; onOpen: (runRef: string) => void }) {
  return (
    <div className="space-y-2">
      {projects.length === 0 && (
        <Card className="p-4">
          <p className="text-sm text-ink-faint">No projects yet — analyse a tender in Routing and it appears here, carrying its packages across the tracks.</p>
        </Card>
      )}
      {projects.map((p) => (
        <Card key={p.run_ref} className="flex flex-wrap items-center gap-3 p-4">
          <button className="text-left" onClick={() => onOpen(p.run_ref)}>
            <div className="flex items-center gap-2">
              <span className="text-sm font-semibold text-ink hover:text-brand">{p.name || p.run_ref}</span>
              {p.provenance === "demo" && <Pill tone="neutral">Illustrative</Pill>}
              {p.benchmark_project_id != null && <Pill tone="ok">Benchmarked</Pill>}
            </div>
            <div className="tabular text-xs text-ink-faint">{p.run_ref}</div>
          </button>
          <div className="ml-auto flex flex-wrap items-center gap-1.5">
            <Pill tone="neutral">{`${p.package_count} package(s)`}</Pill>
            <Pill tone="violet">{`${p.self_perform_count} self-perform`}</Pill>
            <Pill tone="brand">{`${p.sublet_count} sublet`}</Pill>
          </div>
        </Card>
      ))}
    </div>
  );
}

export function ProjectsPage() {
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [dash, setDash] = useState<ProjectDashboard | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = () => api.projects().then(setProjects).catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  useEffect(() => { load(); }, []);

  const open = (runRef: string) =>
    api.projectDashboard(runRef).then(setDash).catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));

  return (
    <div className="min-w-0 space-y-4">
      <SectionHeader
        title="Projects"
        lead="One tender, carried across the tracks. Each analysed run shows its packages, the routing decision per package, the left-track estimates, and where it sits in the lifecycle."
      />
      {error && <ErrorBanner message={error} />}
      {dash ? <DashboardView dash={dash} onBack={() => { setDash(null); load(); }} /> : <ProjectsList projects={projects} onOpen={open} />}
    </div>
  );
}
