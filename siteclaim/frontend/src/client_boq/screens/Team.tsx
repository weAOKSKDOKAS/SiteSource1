// Team & access — the roster of named profiles. No passwords and no permissions, and the
// screen says so: what the roster honestly provides is attribution. Members archive rather
// than delete, because their name is stamped on historical verdicts.

import { useState } from "react";
import { api } from "../api";
import type { TeamMember } from "../types";
import { Avatar, Button, SectionLabel, cx } from "../ui";

export function Team({
  team,
  currentUserId,
  onChanged,
  onError,
  onPick,
}: {
  team: TeamMember[];
  currentUserId: string;
  onChanged: () => void;
  onError: (msg: string) => void;
  onPick: (member: TeamMember) => void;
}) {
  const [name, setName] = useState("");
  const [role, setRole] = useState("");
  const [busy, setBusy] = useState(false);

  const add = async () => {
    if (!name.trim()) return;
    setBusy(true);
    try {
      await api.addTeamMember({ name: name.trim(), role: role.trim() });
      setName("");
      setRole("");
      onChanged();
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto max-w-[640px] p-[18px]">
        <h1 className="font-cb-serif text-[20px] font-semibold text-cb-ink-text">
          Team &amp; access
        </h1>
        <p className="mt-1 font-cb-sans text-[11px] leading-[1.6] text-cb-muted">
          Named profiles, deliberately without passwords — this app has no authentication, and a
          password box here would be theatre. What a profile honestly provides is attribution:
          who owns a tender, who confirmed a finding, who changed a rate. Anyone can pick any
          name; the record is only as honest as the room.
        </p>

        <section className="mt-5">
          <SectionLabel>The roster · {team.length}</SectionLabel>
          <div className="mt-2 flex flex-col gap-1.5">
            {team.map((m) => (
              <div
                key={m.member_id}
                className={cx(
                  "cb-row flex items-center gap-2.5 rounded-cb-card border px-3 py-2",
                  m.member_id === currentUserId ? "border-cb-brass bg-cb-selected" : "border-cb-border bg-cb-page",
                )}
              >
                <Avatar member={m} size={26} />
                <div className="min-w-0 flex-1">
                  <div className="truncate font-cb-sans text-[12px] font-semibold text-cb-ink-text">
                    {m.name}
                    {m.member_id === currentUserId && (
                      <span className="ml-2 font-cb-mono text-[10px] font-semibold tracking-cb-chip text-cb-brass-text">
                        THIS IS YOU
                      </span>
                    )}
                  </div>
                  <div className="truncate font-cb-sans text-[10px] text-cb-muted">
                    {m.role || "—"} · <span className="font-cb-mono text-[10px]">{m.member_id}</span>
                  </div>
                </div>
                {m.member_id !== currentUserId && (
                  <button
                    type="button"
                    onClick={() => onPick(m)}
                    className="cb-press font-cb-sans text-[10px] font-medium text-cb-brass-text underline underline-offset-2"
                  >
                    Work as
                  </button>
                )}
                <button
                  type="button"
                  title="Archives, never deletes — the name stays on every verdict it recorded."
                  onClick={async () => {
                    try {
                      await api.updateTeamMember(m.member_id, { name: m.name, archived: true });
                      onChanged();
                    } catch (e) {
                      onError(e instanceof Error ? e.message : String(e));
                    }
                  }}
                  className="cb-press font-cb-sans text-[10px] font-medium text-cb-muted underline underline-offset-2"
                >
                  Archive
                </button>
              </div>
            ))}
            {!team.length && (
              <p className="font-cb-sans text-[11px] text-cb-muted">Nobody yet — add the first name below.</p>
            )}
          </div>
        </section>

        <section className="mt-5 border-t border-cb-divider pt-4">
          <SectionLabel>Add a member</SectionLabel>
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
              className="w-[140px] rounded-cb-btn border border-cb-border bg-cb-warm px-2.5 py-1.5 font-cb-sans text-[12px] text-cb-ink-text placeholder:text-cb-faint"
            />
            <Button variant="brass" onClick={() => void add()} disabled={busy || !name.trim()}>
              Add
            </Button>
          </div>
        </section>
      </div>
    </div>
  );
}
