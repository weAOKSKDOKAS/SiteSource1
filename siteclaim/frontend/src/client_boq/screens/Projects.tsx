// Projects — the unified dashboard: one tender run, carried across both tracks. Ported from
// ProjectsPage; behaviour, wording and every decision it encodes are unchanged, palette only.
//
// THE INVARIANT THIS SCREEN EXISTS TO PROTECT: A PACKAGE NOBODY HAS ROUTED MUST NOT LOOK ROUTED.
// `track` is derived from `chosen_route` and nothing else, so "undecided" is a real recorded
// state — nobody has decided yet — and not a value that failed to arrive. The screen therefore
// says the word "undecided" out loud, in neutral grey, and never lends an undecided package
// either track's colour. The Decision column shows the absence as an absence; it is never filled
// in with the recommendation. A recommendation is what the analysis proposed; a decision is what
// a person chose, and letting the first stand in for the second is the single thing this screen
// must not do.
//
// THE COLOUR PORT, since it is the substance of this file: Atlas gives the two tracks two peer
// hues — violet for self-perform, brand blue for sublet. cb assigns colour by AUTHORSHIP rather
// than by category, and cb's blue is already spoken for ("an uncovered clause"), so neither hue
// survives a swap. A routing decision is a fact already recorded against the run, so both tracks
// are navy here and are told apart by fill versus outline. Nothing on this screen is brass: the
// model proposes a route, it does not choose one, and no number below was written by a model.

import { useEffect, useState } from "react";

import { api } from "../api";
import type { ProjectDashboard, ProjectSummary } from "../types";
import {
  Button,
  Card,
  Chip,
  ErrorNote,
  LoadingDots,
  Pill,
  SectionHeader,
  SectionLabel,
  StatCallout,
  cx,
} from "../ui";

// Local copies of two `src/format.ts` helpers — client_boq imports no procurement file, and the
// four lines are cheaper than the coupling. `money` keeps the source's behaviour exactly: an
// absent total is an em dash, never a confident HK$0, and cents survive.
function tradeLabel(trade: string): string {
  const [base, section] = trade.split(":");
  const label = base.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  return section ? `${label} · Section ${section}` : label;
}

function money(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return "HK$" + n.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

/** Which track a package took. Navy in both directions: a chosen route is a recorded fact, not a
 *  proposal — fill for self-perform, outline for sublet, because cb has one factual colour and
 *  two peer tracks to tell apart. Undecided borrows neither. */
function TrackBadge({ track, chosen }: { track: string; chosen: string | null }) {
  if (track === "left") {
    return <Pill className="bg-cb-info-fill text-cb-navy">Self-perform → Estimator</Pill>;
  }
  if (track === "right") {
    return <Pill className="border border-cb-navy text-cb-navy">Sublet → Sourcing</Pill>;
  }
  // `chosen ?? "undecided"` is the source's wording, kept literally: a chosen route the backend
  // does not map onto a track still reads as undecided here rather than being quietly promoted
  // into one. Panel grey says "no judgement has been recorded", which is the truth.
  return <Pill className="bg-cb-panel text-cb-muted">{chosen ?? "undecided"}</Pill>;
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
          {/* Reached / not reached is read off the payload deterministically, so a lit stage is
              navy. An unlit one is panel grey — "not yet", never a failure. */}
          <span
            className={cx(
              "rounded-cb-pill px-2.5 py-1 font-cb-sans text-[10px] font-semibold",
              s.on ? "bg-cb-info-fill text-cb-navy" : "bg-cb-panel text-cb-faint",
            )}
          >
            {s.label}
          </span>
          {i < stages.length - 1 && (
            <span className="text-cb-faint" aria-hidden>
              →
            </span>
          )}
        </span>
      ))}
    </div>
  );
}

function DashboardView({ dash, onBack }: { dash: ProjectDashboard; onBack: () => void }) {
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-3">
        <Button variant="ghost" onClick={onBack}>
          ← Projects
        </Button>
        <h2 className="font-cb-serif text-[16px] font-semibold text-cb-ink-text">
          {dash.name || dash.run_ref}
        </h2>
        <span className="font-cb-mono text-[10px] text-cb-faint">{dash.run_ref}</span>
        {/* Provenance is a label, not a judgement — the run is illustrative, which the reader
            needs to know but which is not a warning about anything. */}
        {dash.provenance === "demo" && <Pill className="bg-cb-panel text-cb-muted">Illustrative</Pill>}
      </div>

      <Card>
        <SectionLabel className="mb-2">Lifecycle</SectionLabel>
        <Lifecycle dash={dash} />
      </Card>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {/* A total with no verdict attached stays the default ink; the two track counts take the
            factual navy of the badges they count; the benchmark link is a completed tie-up. */}
        <StatCallout label="Packages" value={dash.packages.length} />
        <StatCallout
          label="Self-perform"
          value={dash.packages.filter((p) => p.track === "left").length}
          accent="text-cb-navy"
        />
        <StatCallout
          label="Sublet"
          value={dash.packages.filter((p) => p.track === "right").length}
          accent="text-cb-navy"
        />
        <StatCallout
          label="Benchmarked"
          value={dash.benchmark_project_id != null ? `#${dash.benchmark_project_id}` : "—"}
          accent="text-cb-ok-dark"
        />
      </div>

      <Card flush>
        <div className="border-b border-cb-divider px-4 py-2.5">
          <h3 className="font-cb-sans text-[12px] font-semibold text-cb-ink-text">Packages</h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left">
            <thead>
              <tr className="border-b border-cb-divider">
                {["Trade", "Recommended", "Decision", "Track"].map((h) => (
                  <th
                    key={h}
                    className="px-3 py-2 font-cb-mono text-[8.5px] font-semibold tracking-cb-chip text-cb-faint"
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {dash.packages.length === 0 && (
                <tr>
                  <td className="px-3 py-3 font-cb-sans text-[11px] text-cb-faint" colSpan={4}>
                    No routing analysed for this run yet.
                  </td>
                </tr>
              )}
              {dash.packages.map((p) => (
                <tr key={p.package_key} className="cb-row border-b border-cb-divider last:border-0">
                  <td className="px-3 py-2">
                    <div className="font-cb-sans text-[12px] font-medium text-cb-ink-text">
                      {tradeLabel(p.trade || p.package_key)}
                    </div>
                    {p.scope_summary && (
                      <div className="font-cb-sans text-[10px] text-cb-faint">{p.scope_summary}</div>
                    )}
                  </td>
                  {/* Brass, where Atlas had this the same neutral as the Decision beside it.
                      `recommended_route` is drafted by the model (routing/recommend.py calls
                      complete_json); `chosen_route` is a human's. In a palette whose whole premise
                      is that authorship is visible, rendering the two identically is the meaning
                      Atlas could afford to leave to the column header and this one cannot. */}
                  <td className="px-3 py-2 font-cb-sans text-[11px] text-cb-brass-text">
                    {p.recommended_route.replace(/_/g, " ") || "—"}
                  </td>
                  {/* The decision, and its absence. An undecided package shows the word in faint
                      text — the recommendation next door is never allowed to fill this cell. */}
                  <td className="px-3 py-2 font-cb-sans text-[11px] text-cb-body">
                    {p.chosen_route ? (
                      p.chosen_route.replace(/_/g, " ")
                    ) : (
                      <span className="text-cb-faint">undecided</span>
                    )}
                  </td>
                  <td className="px-3 py-2">
                    <TrackBadge track={p.track} chosen={p.chosen_route} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      {dash.estimates.length > 0 && (
        <Card flush>
          <div className="border-b border-cb-divider px-4 py-2.5">
            <h3 className="font-cb-sans text-[12px] font-semibold text-cb-ink-text">
              Left track — estimates
            </h3>
          </div>
          <div className="divide-y divide-cb-divider">
            {dash.estimates.map((e) => (
              <div key={e.id} className="flex flex-wrap items-center gap-3 px-4 py-2.5">
                <span className="font-cb-sans text-[12px] font-medium text-cb-ink-text">{e.name}</span>
                {/* The trade is a taxonomy key carried with the estimate — register fact, navy,
                    exactly as a registered trade reads on a firm record. */}
                <Pill className="bg-cb-info-fill text-cb-navy">{tradeLabel(e.trade)}</Pill>
                {/* A draft is simply where the estimate has got to; anything past draft is a
                    state somebody signed off, so it reads as ok. */}
                <Pill
                  className={
                    e.status === "draft"
                      ? "bg-cb-panel text-cb-muted"
                      : "bg-cb-ok-tint text-cb-ok-dark"
                  }
                >
                  {e.status}
                </Pill>
                <div className="ml-auto flex items-center gap-1.5">
                  {/* A progress count carries no judgement. The total is qty × rate — arithmetic,
                      so navy and never brass; mono because it is compared digit by digit. */}
                  <Chip className="bg-cb-panel text-cb-muted">
                    {`${e.priced_item_count}/${e.item_count} priced`}
                  </Chip>
                  <Chip className="bg-cb-info-fill text-cb-navy">{money(e.total)}</Chip>
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}

function ProjectsList({
  projects,
  onOpen,
}: {
  projects: ProjectSummary[];
  onOpen: (runRef: string) => void;
}) {
  return (
    <div className="space-y-2">
      {projects.length === 0 && (
        <Card>
          <p className="font-cb-sans text-[11px] leading-[1.6] text-cb-faint">
            No projects yet — analyse a tender in Routing and it appears here, carrying its
            packages across the tracks.
          </p>
        </Card>
      )}
      {projects.map((p) => (
        <Card key={p.run_ref} className="flex flex-wrap items-center gap-3">
          <button className="text-left" onClick={() => onOpen(p.run_ref)}>
            <div className="flex items-center gap-2">
              <span className="font-cb-sans text-[12px] font-semibold text-cb-ink-text hover:text-cb-brass-text">
                {p.name || p.run_ref}
              </span>
              {p.provenance === "demo" && (
                <Pill className="bg-cb-panel text-cb-muted">Illustrative</Pill>
              )}
              {/* Tied to a completed project in the benchmark corpus — a good, finished state. */}
              {p.benchmark_project_id != null && (
                <Pill className="bg-cb-ok-tint text-cb-ok-dark">Benchmarked</Pill>
              )}
            </div>
            <div className="mt-0.5 font-cb-mono text-[10px] text-cb-faint">{p.run_ref}</div>
          </button>
          <div className="ml-auto flex flex-wrap items-center gap-1.5">
            {/* The split, in the same navy the track badges use: filled self-perform, outlined
                sublet. The bare package count is a count and takes no side. */}
            <Chip className="bg-cb-panel text-cb-muted">{`${p.package_count} package(s)`}</Chip>
            <Chip className="bg-cb-info-fill text-cb-navy">{`${p.self_perform_count} self-perform`}</Chip>
            <Chip className="border border-cb-navy text-cb-navy">{`${p.sublet_count} sublet`}</Chip>
          </div>
        </Card>
      ))}
    </div>
  );
}

export function Projects({ onError }: { onError: (message: string) => void }) {
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [dash, setDash] = useState<ProjectDashboard | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  const fail = (e: unknown) => {
    const message = e instanceof Error ? e.message : String(e);
    setError(message);
    onError(message);
  };

  const load = () =>
    api.manage
      .projects()
      .then(setProjects)
      .catch(fail)
      .finally(() => setLoaded(true));
  useEffect(() => {
    load();
    // The source mounts this once; onError is the shell's callback and is deliberately not a
    // dependency — re-fetching the list because a parent re-rendered would be new behaviour.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const open = (runRef: string) => api.manage.projectDashboard(runRef).then(setDash).catch(fail);

  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto min-w-0 max-w-[1040px] space-y-4 p-[18px]">
        <SectionHeader
          title="Projects"
          lead="One tender, carried across the tracks. Each analysed run shows its packages, the routing decision per package, the left-track estimates, and where it sits in the lifecycle."
        />
        {error && <ErrorNote message={error} />}
        {!loaded ? (
          <Card>
            <LoadingDots label="Loading projects" />
          </Card>
        ) : dash ? (
          <DashboardView
            dash={dash}
            onBack={() => {
              setDash(null);
              load();
            }}
          />
        ) : (
          <ProjectsList projects={projects} onOpen={open} />
        )}
      </div>
    </div>
  );
}
