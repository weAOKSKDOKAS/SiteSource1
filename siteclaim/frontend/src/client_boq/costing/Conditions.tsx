// Conditions — the notepad that reaches the price.
//
// The engine's knobs are the ones the engine has. Real tenders arrive with conditions it has never
// heard of: "no night work through the village section", "the client supplies the platform at
// CH2+400", "two of the holes are over water". Before this there was nowhere to put one, so it
// lived in somebody's notebook and reached the price only if they remembered on the right
// afternoon.
//
// ONE BOX, because writing a condition down and "adding a condition" are the same act. Type the
// sentence; the model proposes which existing input it moves and by how much, with its reasoning;
// you confirm, reject, or type a different number and confirm that.
//
// THE RED LINE IS VISIBLE ON THE SCREEN, not just in the backend. The proposal is rendered as a
// proposal — the number is not applied, the card says so, and the model input does not move until
// somebody presses Confirm. A condition the model could not map stays listed, unpriced, with the
// reason showing, because a condition nobody priced is exactly what loses money after award.

import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import type { ConditionRow } from "../types";
import { Button, Card, Consequence, SectionLabel, cx } from "../ui";

export function Conditions({
  setId,
  onChanged,
  onError,
}: {
  setId: string;
  /** The register and every derived figure re-read after a confirmation writes the model. */
  onChanged: () => Promise<void>;
  onError: (msg: string) => void;
}) {
  const [rows, setRows] = useState<ConditionRow[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setRows((await api.conditions(setId)).conditions);
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    }
  }, [setId, onError]);

  useEffect(() => {
    void load();
  }, [load]);

  const add = async () => {
    if (!text.trim()) return;
    setBusy(true);
    try {
      await api.addCondition(setId, text.trim());
      setText("");
      await load();
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const decide = async (id: string, status: string, value?: number) => {
    setBusy(true);
    try {
      await api.decideCondition(setId, id, status, value);
      await load();
      if (status === "confirmed") await onChanged();
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const undecided = rows.filter((r) => !r.status).length;

  return (
    <section className="mt-6">
      <SectionLabel>
        CONDITIONS ON THIS TENDER
        {rows.length > 0 && ` · ${rows.length}`}
        {undecided > 0 && (
          <span className="ml-2 text-cb-brass-text">{undecided} awaiting your decision</span>
        )}
      </SectionLabel>
      <p className="mt-1 max-w-[680px] font-cb-sans text-[10.5px] leading-[1.55] text-cb-muted">
        Anything about this job the engine has no field for. Write it in plain words; the model
        proposes which input it moves and why. <strong>Nothing is written until you confirm</strong>
        , and a condition it cannot map stays here unpriced rather than disappearing.
      </p>

      <div className="mt-2 flex items-start gap-2">
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={2}
          placeholder="e.g. No night work or Sunday work through the village section."
          className="min-h-[46px] flex-1 rounded-cb-btn border border-cb-border bg-cb-warm px-2.5 py-1.5 font-cb-sans text-[11.5px] leading-[1.5] text-cb-ink-text placeholder:text-cb-faint"
        />
        <Button variant="brass" onClick={() => void add()} disabled={busy || !text.trim()}>
          {busy ? "Reading…" : "Write it down"}
        </Button>
      </div>

      <div className="mt-2.5 flex flex-col gap-2">
        {rows.map((row) => (
          <ConditionCard
            key={row.condition_id}
            row={row}
            busy={busy}
            onDecide={(status, value) => void decide(row.condition_id, status, value)}
            onDelete={async () => {
              try {
                await api.deleteCondition(setId, row.condition_id);
                await load();
              } catch (e) {
                onError(e instanceof Error ? e.message : String(e));
              }
            }}
          />
        ))}
      </div>
    </section>
  );
}

function ConditionCard({
  row,
  busy,
  onDecide,
  onDelete,
}: {
  row: ConditionRow;
  busy: boolean;
  onDecide: (status: string, value?: number) => void;
  onDelete: () => Promise<void>;
}) {
  const [override, setOverride] = useState("");
  const mapped = Boolean(row.proposed_path) && row.proposed_value !== null;
  const numeric = override.trim() !== "" && !Number.isNaN(Number(override));

  return (
    <Card selected={!row.status && mapped}>
      <p className="font-cb-serif text-[12px] leading-[1.5] text-cb-ink-text">{row.text}</p>
      <div className="mt-1 font-cb-mono text-[10px] text-cb-faint">
        {row.created_by ? `${row.created_by} · ` : ""}
        {row.created_at?.slice(0, 10)}
        {/* The backward half of "why do we believe this?" — the discussion that concluded it.
            0 = typed straight onto the register; no link is honest there. */}
        {row.born_of_seq > 0 && (
          <span className="ml-1.5 text-cb-brass-text">
            · born of discussion #{row.born_of_seq}
          </span>
        )}
      </div>

      {mapped ? (
        <div className="mt-2 rounded-cb-chip border border-cb-brass-line bg-cb-brass-tint px-2.5 py-2">
          <div className="font-cb-mono text-[10px] font-semibold tracking-cb-chip text-cb-brass-text">
            {row.status === "confirmed" ? "APPLIED" : "PROPOSED — NOT APPLIED"}
          </div>
          <div className="mt-0.5 font-cb-mono text-[10.5px] font-semibold text-cb-ink-text">
            {row.proposed_path} → {row.proposed_value}
            {row.applied_value !== null && row.applied_value !== row.proposed_value && (
              <span className="ml-2 text-cb-brass-text">
                (you set {row.applied_value})
              </span>
            )}
          </div>
          {row.proposal_basis && (
            <p className="mt-1 font-cb-sans text-[10px] leading-[1.5] text-cb-brass-text">
              {row.proposal_basis}
            </p>
          )}
          {row.proposal_source && (
            <p className="mt-1 font-cb-mono text-[10px] leading-[1.4] text-cb-faint">
              {row.proposal_source}
            </p>
          )}
        </div>
      ) : (
        <div className="mt-2 rounded-cb-chip border border-dashed border-cb-border-strong px-2.5 py-2">
          <div className="font-cb-mono text-[10px] font-semibold tracking-cb-chip text-cb-muted">
            NOT MAPPED — AND THAT MAY BE CORRECT
          </div>
          <p className="mt-1 font-cb-sans text-[10px] leading-[1.5] text-cb-muted">
            {row.proposal_basis ||
              "No single input carries this condition. It stays here, on the record and unpriced, so it is not lost."}
          </p>
        </div>
      )}

      <div className="mt-2 flex flex-wrap items-center gap-2">
        {row.status ? (
          <>
            <span
              className={cx(
                "rounded-cb-chip px-1.5 py-[1px] font-cb-mono text-[10px] font-semibold tracking-cb-chip",
                row.status === "confirmed"
                  ? "bg-cb-ok-tint text-cb-ok-dark"
                  : "bg-cb-bad-tint text-cb-bad-dark",
              )}
            >
              {row.status.toUpperCase()}
              {row.decided_by ? ` · ${row.decided_by}` : ""}
            </span>
            <button
              type="button"
              disabled={busy}
              onClick={() => onDecide("")}
              className="cb-press font-cb-sans text-[10px] text-cb-muted underline underline-offset-2"
            >
              undo the decision
            </button>
          </>
        ) : mapped ? (
          <>
            <Button variant="brass" onClick={() => onDecide("confirmed")} disabled={busy}>
              Confirm
            </Button>
            <input
              value={override}
              onChange={(e) => setOverride(e.target.value)}
              placeholder="or your own number"
              className={cx(
                "w-[128px] rounded-cb-chip border bg-cb-warm px-2 py-1 text-right font-cb-mono text-[10px] text-cb-ink-text placeholder:text-left placeholder:font-cb-sans placeholder:text-[10px] placeholder:text-cb-faint",
                override && !numeric ? "border-cb-bad" : "border-cb-border",
              )}
            />
            {numeric && (
              <button
                type="button"
                disabled={busy}
                onClick={() => onDecide("confirmed", Number(override))}
                className="cb-press font-cb-sans text-[10px] font-semibold text-cb-brass-text underline underline-offset-2"
              >
                confirm {override} instead
              </button>
            )}
            <button
              type="button"
              disabled={busy}
              onClick={() => onDecide("rejected")}
              className="cb-press font-cb-sans text-[10px] text-cb-muted underline underline-offset-2"
            >
              Reject
            </button>
            <Consequence>
              Confirming writes {row.proposed_path} on this tender only, and every rate derived from
              it moves.
            </Consequence>
          </>
        ) : null}
        <button
          type="button"
          disabled={busy}
          title={
            row.applied_value !== null
              ? "Removing the condition does NOT revert the number it set — that is the model's now. Change it on the register."
              : "This condition has written nothing."
          }
          onClick={() => void onDelete()}
          className="cb-press ml-auto font-cb-sans text-[10px] text-cb-faint underline underline-offset-2"
        >
          remove
        </button>
      </div>
    </Card>
  );
}
