// Choosing which bill of quantities gets priced.
//
// The gap this closes: a folder ingest already found every workbook that reads as a bill, and
// already refused to guess which one was operative — correctly, because that is a decision. It then
// said "pick one on the Price step", and there was nowhere to pick. On the real ND/2025/04 package
// that left three perfectly good bills on disk and a costing screen that answered "no bill of
// quantities" forever.
//
// One component, two homes (Documents and Price), so neither screen owns the list and they cannot
// disagree about what was found.
//
// The app PROPOSES rather than chooses. `proposed` marks the workbook whose path carries the latest
// addendum and `why` is the sentence behind it. Which file is newest is very nearly clerical — but
// being wrong about it prices the wrong bill, which is exactly the sort of mistake nobody notices
// until the tender is out.

import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import type { BillCandidate } from "./types";
import { Button, Chip, WaitingOn, cx } from "./ui";

export function BillPicker({
  setId,
  onImported,
  onError,
  title = "Which bill should be priced?",
}: {
  setId: string;
  /** The caller reloads whatever it shows — the costing, the manifest — once a bill is in. */
  onImported: () => void | Promise<void>;
  onError: (message: string) => void;
  title?: string;
}) {
  const [candidates, setCandidates] = useState<BillCandidate[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setCandidates((await api.billCandidates(setId)).candidates);
    } catch (e: unknown) {
      setCandidates([]);
      onError(e instanceof Error ? e.message : String(e));
    }
  }, [setId, onError]);

  useEffect(() => {
    void load();
  }, [load]);

  async function importOne(candidate: BillCandidate) {
    setBusy(candidate.relative_path);
    try {
      await api.importBillFromSet(setId, candidate.relative_path);
      await load();
      await onImported();
    } catch (e: unknown) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }

  if (candidates === null) return null;
  if (!candidates.length) {
    return (
      <WaitingOn title="No bill of quantities in this upload">
        Nothing here reads as a bill — the app tries every workbook through the bill reader rather
        than trusting a filename, and none of them held priceable items. Import the client's
        workbook by hand, or check it arrived with the package.
      </WaitingOn>
    );
  }

  return (
    <div className="rounded-cb-card border border-cb-border bg-cb-page px-3 py-2.5">
      <div className="mb-1.5 font-cb-mono text-[9px] font-semibold tracking-cb-label text-cb-muted">
        {title.toUpperCase()}
      </div>
      <div className="flex flex-col gap-1">
        {candidates.map((candidate) => (
          <div
            key={candidate.relative_path}
            className={cx(
              "flex flex-wrap items-baseline gap-2 rounded-cb-chip px-1.5 py-1",
              candidate.proposed && !candidate.already_imported && "bg-cb-brass-tint",
            )}
          >
            <Chip
              className={
                candidate.already_imported
                  ? "bg-cb-ok-tint text-cb-ok-dark"
                  : "bg-cb-brass-tint text-cb-brass-text"
              }
            >
              {candidate.already_imported ? "✓ IN" : "BILL"}
            </Chip>
            <span className="min-w-0 flex-1 truncate font-cb-mono text-[9.5px] text-cb-body">
              {candidate.relative_path}
            </span>
            <span className="flex-none font-cb-mono text-[9px] text-cb-muted">
              {candidate.priceable} priceable
            </span>
            {candidate.already_imported ? (
              <span className="flex-none font-cb-mono text-[9px] text-cb-ok-dark">IMPORTED</span>
            ) : (
              <Button
                variant={candidate.proposed ? "brass" : "ghost"}
                disabled={busy !== null}
                onClick={() => void importOne(candidate)}
              >
                {busy === candidate.relative_path ? "Reading…" : "Price this bill"}
              </Button>
            )}
            {/* The reason the proposal is the proposal. Without it the mark is just an opinion the
                screen is asserting, which is the thing this product does not do. */}
            {candidate.proposed && !candidate.already_imported && (
              <span className="w-full font-cb-sans text-[9.5px] leading-[1.45] text-cb-brass-text">
                Looks like the one to price — {candidate.why}. The others are here if you disagree.
              </span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
