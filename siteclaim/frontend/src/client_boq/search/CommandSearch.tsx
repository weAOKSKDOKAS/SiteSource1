// Command search (Ctrl-K / ⌘K). v1 is client-side over what is already loaded — projects,
// clients, team, criteria ids and clause areas, plus the open set's part titles. Clause-text
// search inside a part already exists in the document pane; this box gets you to the right
// tender or screen, it does not replace the measured in-part search.

import { useEffect, useMemo, useRef, useState } from "react";
import type { CriteriaResponse, PartsResponse, SetRow, TeamMember } from "../types";
import type { Surface } from "../nav/routes";
import { go } from "../nav/routes";
import { landingTab } from "../chrome";
import { cx } from "../ui";

interface Hit {
  group: string;
  title: string;
  detail: string;
  surface: Surface;
}

export function CommandSearch({
  sets,
  team,
  criteria,
  openSetId,
  parts,
  onClose,
}: {
  sets: SetRow[];
  team: TeamMember[];
  criteria: CriteriaResponse | null;
  openSetId: string | null;
  parts: PartsResponse | null;
  onClose: () => void;
}) {
  const [query, setQuery] = useState("");
  const [cursor, setCursor] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => inputRef.current?.focus(), []);

  const hits = useMemo<Hit[]>(() => {
    const q = query.trim().toLowerCase();
    if (!q) return [];
    const out: Hit[] = [];
    for (const s of sets) {
      const haystack = `${s.name} ${s.meta.client} ${s.meta.package}`.toLowerCase();
      if (haystack.includes(q))
        out.push({
          group: s.meta.archived ? "ARCHIVED" : "TENDERS",
          title: s.name,
          detail: [s.meta.client, s.meta.package].filter(Boolean).join(" · ") || `${s.parts} parts`,
          surface: { kind: "set", setId: s.set_id, tab: landingTab(s) },
        });
    }
    for (const m of team) {
      if (m.name.toLowerCase().includes(q))
        out.push({
          group: "TEAM",
          title: m.name,
          detail: m.role || "team member",
          surface: { kind: "screen", screen: "team" },
        });
    }
    for (const c of criteria?.rows ?? []) {
      if (c.id.toLowerCase().includes(q) || c.clause_area.toLowerCase().includes(q))
        out.push({
          group: "CRITERIA",
          title: `${c.id} · ${c.clause_area}`,
          detail: c.acceptable_position.slice(0, 80) || "(placeholder)",
          surface: { kind: "screen", screen: "criteria" },
        });
    }
    if (openSetId && parts) {
      for (const p of parts.parts) {
        if (p.title.toLowerCase().includes(q) || p.part_id.toLowerCase().includes(q))
          out.push({
            group: "PARTS OF THE OPEN SET",
            title: `${p.part_id} · ${p.title}`,
            detail: `pp. ${p.pages}`,
            surface: { kind: "set", setId: openSetId, tab: landingTab(sets.find((r) => r.set_id === openSetId) ?? {}) },
          });
      }
    }
    return out.slice(0, 12);
  }, [query, sets, team, criteria, openSetId, parts]);

  useEffect(() => setCursor(0), [query]);

  const pick = (hit: Hit) => {
    go(hit.surface);
    onClose();
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-cb-ink/40 p-6 pt-[12vh]"
      onClick={onClose}
    >
      <div
        className="w-full max-w-[520px] overflow-hidden rounded-cb-card border border-cb-border bg-cb-surface shadow-cb-card"
        onClick={(e) => e.stopPropagation()}
      >
        <input
          ref={inputRef}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Escape") onClose();
            else if (e.key === "ArrowDown") setCursor((c) => Math.min(c + 1, hits.length - 1));
            else if (e.key === "ArrowUp") setCursor((c) => Math.max(c - 1, 0));
            else if (e.key === "Enter" && hits[cursor]) pick(hits[cursor]);
          }}
          placeholder="Projects, clients, part titles, criterion ids…"
          className="w-full border-b border-cb-border bg-cb-warm px-4 py-3 font-cb-sans text-[13px] text-cb-ink-text placeholder:text-cb-faint focus:outline-none"
        />
        {query.trim() && (
          <div className="max-h-[45vh] overflow-y-auto py-1">
            {hits.length === 0 && (
              <div className="px-4 py-3 font-cb-sans text-[11px] text-cb-muted">
                Nothing matches. Clause text inside a part is searched from the document pane,
                where the hits are measured on the page.
              </div>
            )}
            {hits.map((hit, i) => (
              <button
                key={`${hit.group}-${hit.title}-${i}`}
                type="button"
                onClick={() => pick(hit)}
                className={cx(
                  "cb-row flex w-full items-baseline gap-3 px-4 py-2 text-left",
                  i === cursor && "bg-cb-selected",
                )}
              >
                <span className="w-[130px] flex-none font-cb-mono text-[10px] font-semibold tracking-cb-chip text-cb-faint">
                  {hit.group}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-cb-sans text-[12px] font-medium text-cb-ink-text">
                    {hit.title}
                  </span>
                  <span className="block truncate font-cb-sans text-[10px] text-cb-muted">
                    {hit.detail}
                  </span>
                </span>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
