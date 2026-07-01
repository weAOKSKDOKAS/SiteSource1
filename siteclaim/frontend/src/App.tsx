import { useEffect, useState } from "react";
import { api } from "./api";
import { Header, type Page } from "./components";
import { CiteProvider } from "./cite";
import type { Coverage } from "./types";
import { PageDatabase } from "./PageDatabase";
import { PageSourcing } from "./PageSourcing";

export default function App() {
  const [page, setPage] = useState<Page>("database");

  // Shared meta, fetched once (offline in DEMO_MODE). The 1,366-firm register is
  // NOT loaded here — PageDatabase fetches it one server-side page at a time.
  const [demoMode, setDemoMode] = useState(true);
  const [coverage, setCoverage] = useState<Coverage | null>(null);

  useEffect(() => {
    api.health().then((h) => setDemoMode(h.demo_mode)).catch(() => {});
    api.coverage().then(setCoverage).catch(() => {});
  }, []);

  // Distinct issuing registers behind the flags (from /coverage, header figure).
  const registers = coverage?.registers ?? 5;

  return (
    <CiteProvider>
      <div style={{ minHeight: "100vh", background: "radial-gradient(1100px 520px at 88% -8%, rgba(110,86,207,0.10), transparent 60%), radial-gradient(900px 480px at -5% 8%, rgba(15,181,166,0.09), transparent 55%), #EEF2F7" }}>
        <Header page={page} onNavigate={setPage} registers={registers} />
        <div style={{ display: page === "database" ? "block" : "none" }}>
          <PageDatabase active={page === "database"} coverage={coverage} registers={registers} />
        </div>
        <div style={{ display: page === "sourcing" ? "block" : "none" }}>
          <PageSourcing demoMode={demoMode} coverage={coverage} />
        </div>
      </div>
    </CiteProvider>
  );
}
