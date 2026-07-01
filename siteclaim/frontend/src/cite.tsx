import { createContext, useCallback, useContext, useState, type ReactNode } from "react";
import type { Citation } from "./types";
import { registerFor } from "./theme";

// Any citation button anywhere opens the shared evidence drawer through this context.
interface CiteCtx {
  open: (c: Citation) => void;
  close: () => void;
}
const Ctx = createContext<CiteCtx>({ open: () => {}, close: () => {} });
export const useCite = () => useContext(Ctx);

export function CiteProvider({ children }: { children: ReactNode }) {
  const [cite, setCite] = useState<Citation | null>(null);
  const open = useCallback((c: Citation) => setCite(c), []);
  const close = useCallback(() => setCite(null), []);
  return (
    <Ctx.Provider value={{ open, close }}>
      {children}
      <EvidenceDrawer cite={cite} onClose={close} />
    </Ctx.Provider>
  );
}

// The signature government-record drawer (ported from the v2 design).
function EvidenceDrawer({ cite, onClose }: { cite: Citation | null; onClose: () => void }) {
  const reg = registerFor(cite?.source);
  const isUrl = !!cite?.reference && /^https?:\/\//.test(cite.reference);
  const verifyUrl = isUrl ? cite!.reference! : reg.home;
  const docket = cite?.reference || "On the public register";

  return (
    <div style={{ position: "fixed", inset: 0, zIndex: 80, pointerEvents: cite ? "auto" : "none" }}>
      <div
        onClick={onClose}
        style={{ position: "absolute", inset: 0, background: "rgba(15,27,45,0.45)", backdropFilter: "blur(2px)", opacity: cite ? 1 : 0, transition: "opacity .28s" }}
      />
      <aside
        className="ssx"
        style={{
          position: "absolute", top: 0, right: 0, height: "100%", width: 432, maxWidth: "92vw",
          background: "#fff", boxShadow: "-30px 0 60px -30px rgba(15,27,45,0.5)",
          transform: cite ? "translateX(0)" : "translateX(105%)", transition: "transform .34s cubic-bezier(.3,.8,.25,1)",
          overflowY: "auto",
        }}
      >
        {cite && (
          <>
            <div style={{ height: 7, background: reg.color }} />
            <div style={{ padding: "22px 24px" }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 20 }}>
                <div style={{ display: "inline-flex", alignItems: "center", gap: 9, fontFamily: "'Spline Sans Mono',monospace", fontSize: 10.5, fontWeight: 600, letterSpacing: "0.12em", textTransform: "uppercase", color: reg.color }}>
                  <span style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", width: 24, height: 24, borderRadius: 7, background: reg.color, color: "#fff", fontSize: 11 }}>§</span>
                  Government record
                </div>
                <button type="button" onClick={onClose} style={{ border: "none", background: "#EEF2F7", width: 30, height: 30, borderRadius: 9, cursor: "pointer", color: "#46566b", fontSize: 15 }}>✕</button>
              </div>

              <div style={{ fontFamily: "'Spline Sans Mono',monospace", fontSize: 11, letterSpacing: "0.06em", textTransform: "uppercase", color: "#8a98ab" }}>Issuing register</div>
              <div style={{ fontFamily: "'Bricolage Grotesque',sans-serif", fontSize: 22, fontWeight: 700, color: "#0F1B2D", marginTop: 3 }}>{reg.name}</div>

              <div style={{ marginTop: 20, padding: 16, borderRadius: 13, background: "#f6f9fc", border: "1px solid #e7edf4" }}>
                <div style={{ fontFamily: "'Spline Sans Mono',monospace", fontSize: 10.5, letterSpacing: "0.06em", textTransform: "uppercase", color: "#8a98ab", marginBottom: 6 }}>Reference / docket</div>
                <div style={{ fontFamily: "'Spline Sans Mono',monospace", fontSize: 15, fontWeight: 600, color: reg.color, wordBreak: "break-all" }}>{docket}</div>
              </div>

              <div style={{ marginTop: 18 }}>
                <div style={{ fontFamily: "'Spline Sans Mono',monospace", fontSize: 10.5, letterSpacing: "0.06em", textTransform: "uppercase", color: "#8a98ab", marginBottom: 7 }}>Record summary</div>
                <p style={{ margin: 0, fontSize: 13.5, lineHeight: 1.62, color: "#1d2c40" }}>{cite.detail}</p>
              </div>

              <div style={{ display: "flex", gap: 10, marginTop: 18 }}>
                <div style={{ flex: 1, padding: "12px 14px", borderRadius: 11, background: "#f6f9fc", border: "1px solid #e7edf4" }}>
                  <div style={{ fontFamily: "'Spline Sans Mono',monospace", fontSize: 9.5, letterSpacing: "0.06em", textTransform: "uppercase", color: "#8a98ab" }}>Issuing body</div>
                  <div style={{ fontSize: 13, fontWeight: 600, color: reg.color, marginTop: 3 }}>{reg.short}</div>
                </div>
                <div style={{ flex: 1, padding: "12px 14px", borderRadius: 11, background: "#f6f9fc", border: "1px solid #e7edf4" }}>
                  <div style={{ fontFamily: "'Spline Sans Mono',monospace", fontSize: 9.5, letterSpacing: "0.06em", textTransform: "uppercase", color: "#8a98ab" }}>Last checked</div>
                  <div style={{ fontSize: 13, fontWeight: 600, color: "#0F1B2D", marginTop: 3 }}>{cite.date || "live"}</div>
                </div>
              </div>

              <a href={verifyUrl} target="_blank" rel="noreferrer noopener" style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 9, marginTop: 20, textDecoration: "none", background: reg.color, color: "#fff", borderRadius: 12, padding: 13, fontSize: 13.5, fontWeight: 600 }}>Verify at source ↗</a>
              <p style={{ margin: "12px 0 0", fontSize: 11.5, lineHeight: 1.55, color: "#8a98ab", textAlign: "center" }}>SiteSource asserts nothing without a citable public record. This drawer is that record.</p>
            </div>
          </>
        )}
      </aside>
    </div>
  );
}
