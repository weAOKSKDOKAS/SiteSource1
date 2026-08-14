// "Who are you?" — named profiles, deliberately without passwords. There is no auth anywhere in
// this app, and a password field here would be security theatre; what the picker honestly
// provides is ATTRIBUTION. Ownership, verdicts and edits carry the name picked here.

import { useState } from "react";
import { api } from "../api";
import type { TeamMember } from "../types";
import { Avatar, Button, cx } from "../ui";

export function ProfilePicker({
  team,
  currentId,
  onPicked,
  onError,
  onClose,
}: {
  team: TeamMember[];
  currentId: string;
  onPicked: (member: TeamMember) => void;
  onError: (msg: string) => void;
  /** Present only when the picker was opened deliberately (switching), not on first load. */
  onClose?: () => void;
}) {
  const [name, setName] = useState("");
  const [role, setRole] = useState("");
  const [busy, setBusy] = useState(false);
  // The picker is a full-screen overlay, so the app's own ErrorNote renders UNDERNEATH it and a
  // failed Join looked like a dead button. It has to say what went wrong where it happened —
  // this is the one screen a person cannot get past, so a silent failure here locks them out.
  const [failed, setFailed] = useState<string | null>(null);

  const add = async () => {
    if (!name.trim()) return;
    setBusy(true);
    setFailed(null);
    try {
      const { member } = await api.addTeamMember({ name: name.trim(), role: role.trim() });
      onPicked(member);
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e);
      setFailed(message);
      onError(message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-cb-ink/40 p-6">
      <div className="w-full max-w-[420px] rounded-cb-card border border-cb-border bg-cb-surface p-5 shadow-cb-card">
        <h2 className="font-cb-serif text-[18px] font-semibold text-cb-ink-text">Who are you?</h2>
        <p className="mt-1 font-cb-sans text-[11px] leading-[1.55] text-cb-muted">
          Not a login — a name. Ownership, verdicts and edits are attributed to whoever is picked
          here, so the register can honestly say who confirmed what.
        </p>

        {team.length > 0 && (
          <div className="mt-4 flex flex-col gap-1">
            {team.map((m) => (
              <button
                key={m.member_id}
                type="button"
                onClick={() => onPicked(m)}
                className={cx(
                  "cb-press flex items-center gap-2.5 rounded-cb-btn border px-3 py-2 text-left",
                  m.member_id === currentId
                    ? "border-cb-brass bg-cb-selected"
                    : "border-cb-border bg-cb-page",
                )}
              >
                <Avatar member={m} size={26} />
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-cb-sans text-[12px] font-semibold text-cb-ink-text">
                    {m.name}
                  </span>
                  {m.role && (
                    <span className="block truncate font-cb-sans text-[10px] text-cb-muted">
                      {m.role}
                    </span>
                  )}
                </span>
                {m.member_id === currentId && (
                  <span className="font-cb-mono text-[10px] font-semibold text-cb-brass-text">
                    THIS IS YOU
                  </span>
                )}
              </button>
            ))}
          </div>
        )}

        <div className="mt-4 border-t border-cb-divider pt-3">
          <div className="font-cb-mono text-[10px] font-semibold tracking-cb-label text-cb-faint">
            {team.length ? "OR ADD YOURSELF" : "ADD YOURSELF"}
          </div>
          <div className="mt-2 flex gap-2">
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") void add();
              }}
              placeholder="Full name"
              className="min-w-0 flex-1 rounded-cb-btn border border-cb-border bg-cb-warm px-2.5 py-1.5 font-cb-sans text-[12px] text-cb-ink-text placeholder:text-cb-faint"
            />
            <input
              value={role}
              onChange={(e) => setRole(e.target.value)}
              placeholder="Role (optional)"
              className="w-[120px] rounded-cb-btn border border-cb-border bg-cb-warm px-2.5 py-1.5 font-cb-sans text-[12px] text-cb-ink-text placeholder:text-cb-faint"
            />
            <Button onClick={() => void add()} disabled={busy || !name.trim()}>
              {busy ? "Joining…" : "Join"}
            </Button>
          </div>

          {failed && (
            <div className="mt-2 rounded-cb-card border border-cb-bad bg-cb-bad-tint px-2.5 py-2">
              {/* The backend's own sentence, unrewritten — a paraphrase hides which part failed. */}
              <div className="font-cb-mono text-[10px] leading-[1.5] text-cb-bad-dark">
                {failed}
              </div>
              <div className="mt-1 font-cb-sans text-[10px] leading-[1.5] text-cb-body">
                {/failed to fetch|networkerror|load failed/i.test(failed)
                  ? "The API is not answering. It usually means the backend is not running, or this page is pointed at a different port than the one it is on."
                  : "Nothing was saved. Try again, or pick an existing name above."}
              </div>
            </div>
          )}
        </div>

        {onClose && (
          <button
            type="button"
            onClick={onClose}
            className="cb-press mt-3 font-cb-sans text-[10.5px] text-cb-muted underline underline-offset-2"
          >
            Keep working as before
          </button>
        )}
      </div>
    </div>
  );
}
