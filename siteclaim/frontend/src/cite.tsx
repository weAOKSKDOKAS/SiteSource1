import { createContext, useCallback, useContext, useState, type ReactNode } from "react";

import { registerFor } from "./theme";
import { Docket, Drawer, MonoLabel } from "./ui";

// A citable public record: any source chip / flag reference anywhere opens the shared
// government-record drawer through this context. The drawer asserts nothing that is not
// already a cited public record — it IS that record. Built on the shared Drawer primitive
// (Atlas), keyed to the issuing register by its source string.
export interface Citation {
  source: string | null;
  reference: string | null;
  detail: string;
  date?: string | null;
}

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

function EvidenceDrawer({ cite, onClose }: { cite: Citation | null; onClose: () => void }) {
  const reg = registerFor(cite?.source);
  const isUrl = !!cite?.reference && /^https?:\/\//.test(cite.reference);
  const verifyUrl = isUrl ? (cite as Citation).reference! : reg.home;
  const docket = cite?.reference || "On the public register";
  return (
    <Drawer
      open={cite != null}
      onClose={onClose}
      eyebrow="Government record"
      tone="violet"
      title={reg.name}
      subtitle={<span className="tabular">{reg.short}</span>}
      footer="SiteSource asserts nothing without a citable public record. This drawer is that record."
    >
      {cite && (
        <div className="space-y-3">
          <Docket label="Reference / docket" code={<span className="break-all">{docket}</span>} />
          <div>
            <MonoLabel className="mb-1">Record summary</MonoLabel>
            <p className="text-xs leading-relaxed text-ink-soft">{cite.detail}</p>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div className="rounded-xl border border-line-soft bg-paper-soft px-3 py-2.5">
              <MonoLabel>Issuing body</MonoLabel>
              <div className="mt-0.5 text-sm font-semibold text-ink">{reg.short}</div>
            </div>
            <div className="rounded-xl border border-line-soft bg-paper-soft px-3 py-2.5">
              <MonoLabel>Last checked</MonoLabel>
              <div className="mt-0.5 text-sm font-semibold text-ink">{cite.date || "live"}</div>
            </div>
          </div>
          <a
            href={verifyUrl}
            target="_blank"
            rel="noreferrer noopener"
            className="flex items-center justify-center gap-2 rounded-xl bg-brand-violet px-3 py-3 text-sm font-semibold text-white shadow-glow transition hover:brightness-110"
          >
            Verify at source ↗
          </a>
        </div>
      )}
    </Drawer>
  );
}
