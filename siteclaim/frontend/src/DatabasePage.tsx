import { useEffect, useState } from "react";

import { api } from "./api";
import { Pill } from "./components";
import type { Coverage } from "./types";
import { Card, ErrorBanner, LayerBadge, SectionHeader, StatCallout } from "./ui";

// The proprietary database (Layer 3) — the screened public-register pool. Counts are the
// real-provenance scrape only; illustrative demo firms are excluded from these figures.
export function DatabasePage() {
  const [cov, setCov] = useState<Coverage | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.coverage().then(setCov).catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  return (
    <div className="min-w-0 space-y-5">
      <SectionHeader
        title="Proprietary database"
        lead="Fused public records and private closeout reports — the grounding corpus applied at the moment of a decision."
        right={<LayerBadge layer="L3" />}
      />
      {error && <ErrorBanner message={error} />}

      {cov && (
        <>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <StatCallout label="Firms (public register)" value={cov.total_firms} tone="violet" />
            <StatCallout label="Carrying a public flag" value={cov.flagged_firms} tone="violet" />
            <StatCallout label="Distinct trades" value={cov.trades.length} tone="violet" />
            <StatCallout label="Flag types" value={Object.keys(cov.flags_by_type).length} tone="violet" />
          </div>

          <Card className="p-4">
            <div className="mb-2 flex flex-wrap items-baseline gap-2">
              <h3 className="text-sm font-semibold text-ink">Flags by type</h3>
              <span className="text-xs text-ink-faint">
                official registers cross-checked — every stored flag carries its issuing source and reference
              </span>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {Object.entries(cov.flags_by_type).map(([k, n]) => (
                <span key={k} title={`${n} verified public record(s) of this type across the screened pool`} className="cursor-help">
                  <Pill tone="neutral">{`${k.replace(/_/g, " ")} · ${n}`}</Pill>
                </span>
              ))}
            </div>
          </Card>

          <p className="text-xs text-ink-faint">
            Counts reflect the real <span className="tabular">{cov.provenance}</span> scrape only. Illustrative demo
            firms are present-but-excluded here and absent in the live profile; partner-archive firms never enter these
            figures. The register/overlay composition is shown as-is — no rounded headline figure is claimed.
          </p>
        </>
      )}
    </div>
  );
}
