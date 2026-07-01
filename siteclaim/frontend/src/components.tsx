// Shared chrome for the v2 design.

export type Page = "database" | "sourcing";

export function Header({
  page,
  onNavigate,
  registers,
}: {
  page: Page;
  onNavigate: (p: Page) => void;
  registers: number;
}) {
  const tabShadow = "0 4px 12px -6px rgba(15,27,45,0.4)";
  const tab = (active: boolean) => ({
    border: "none" as const,
    background: active ? "#fff" : "transparent",
    color: active ? "#1F6FEB" : "#46566b",
    fontSize: 13.5,
    fontWeight: 600,
    padding: "7px 16px",
    borderRadius: 8,
    cursor: "pointer" as const,
    boxShadow: active ? tabShadow : "none",
    transition: "all .18s",
  });

  return (
    <header style={{ position: "sticky", top: 0, zIndex: 50, background: "rgba(238,242,247,0.82)", backdropFilter: "saturate(150%) blur(12px)", borderBottom: "1px solid rgba(15,27,45,0.08)" }}>
      <div style={{ maxWidth: 1260, margin: "0 auto", display: "flex", alignItems: "center", gap: 22, padding: "0 30px", height: 64 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 13 }}>
          <div style={{ position: "relative", display: "flex", alignItems: "center", justifyContent: "center", width: 34, height: 34, borderRadius: 10, background: "linear-gradient(150deg,#1F6FEB,#6E56CF)", boxShadow: "0 4px 12px rgba(31,111,235,0.35)" }}>
            <div style={{ width: 13, height: 13, border: "2.5px solid #fff", borderRadius: "50%" }} />
            <div style={{ position: "absolute", right: -2, bottom: -2, width: 9, height: 9, borderRadius: "50%", background: "#0FB5A6", border: "2px solid #EEF2F7" }} />
          </div>
          <span style={{ fontFamily: "'Bricolage Grotesque',sans-serif", fontSize: 20, fontWeight: 700, letterSpacing: "-0.02em", color: "#0F1B2D" }}>
            Site<span style={{ color: "#1F6FEB" }}>Source</span>
          </span>
        </div>
        <nav style={{ display: "flex", gap: 3, background: "rgba(15,27,45,0.05)", padding: 4, borderRadius: 11 }}>
          <button type="button" onClick={() => onNavigate("database")} style={tab(page === "database")}>Database</button>
          <button type="button" onClick={() => onNavigate("sourcing")} style={tab(page === "sourcing")}>Sourcing</button>
        </nav>
        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 9, fontFamily: "'Spline Sans Mono',monospace", fontSize: 11, color: "#5a6b80" }}>
          <span style={{ width: 7, height: 7, borderRadius: "50%", background: "#2EA56A", animation: "ssLive 1.8s ease-in-out infinite" }} />
          LIVE · {registers} REGISTERS SYNCED
        </div>
      </div>
    </header>
  );
}
