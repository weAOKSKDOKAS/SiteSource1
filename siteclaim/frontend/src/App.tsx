import { useEffect, useState } from "react";
import { api } from "./api";
import { Header, type Page } from "./components";
import type { Coverage, DemoCaseSummary } from "./types";
import { cx } from "./ui";
import { PageDatabase } from "./PageDatabase";
import { PageSourcing } from "./PageSourcing";

export default function App() {
  // Two pages behind a top nav; the Database asset is the landing page.
  const [page, setPage] = useState<Page>("database");

  // Shared meta, fetched once and passed to both pages (offline in DEMO_MODE).
  const [demoMode, setDemoMode] = useState(true);
  const [coverage, setCoverage] = useState<Coverage | null>(null);
  const [demoCases, setDemoCases] = useState<DemoCaseSummary[]>([]);

  useEffect(() => {
    api.health().then((h) => setDemoMode(h.demo_mode)).catch(() => {});
    api.coverage().then(setCoverage).catch(() => {});
    api.demoCases().then(setDemoCases).catch(() => {});
  }, []);

  // Both pages stay mounted (toggled with `hidden`) so wizard progress survives a
  // trip to the Database page and back.
  return (
    <div className="min-h-screen">
      <Header demoMode={demoMode} page={page} onNavigate={setPage} />
      <div className={cx(page !== "database" && "hidden")}>
        <PageDatabase coverage={coverage} />
      </div>
      <div className={cx(page !== "sourcing" && "hidden")}>
        <PageSourcing demoMode={demoMode} demoCases={demoCases} coverage={coverage} />
      </div>
    </div>
  );
}
