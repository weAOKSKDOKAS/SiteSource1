// Site › PHOTOS — what somebody saw on the walk, read alongside the reports.
//
// The tender package says where the holes are and how deep. It does not say the track stops 200 m
// short, or that the only standing ground is somebody's vegetable plot. Those cost money, and the
// only record of them is a phone camera roll.
//
// WHAT THE MODEL PRODUCES HERE IS AN OBSERVATION, and the screen renders it as one: what is
// visible, which photograph it came from, and why it MIGHT matter. Never a class, never a cost —
// a machine looking at a hillside cannot tell you it is Class B, and if it said so it would be
// believed. The reader keeps the ones that matter, and a kept one becomes a condition on the
// Costing step, where it goes through the ordinary propose-and-confirm path. Two human decisions
// between a photograph and a number.

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { Observation, PhotoRow } from "../types";
import { Button, Card, SectionLabel, cx } from "../ui";

const TOPIC_LABEL: Record<string, string> = {
  access: "ACCESS",
  ground: "GROUND",
  obstruction: "OBSTRUCTION",
  space: "WORKING SPACE",
  hazard: "HAZARD",
  other: "OTHER",
};

export function Photos({
  setId,
  onError,
}: {
  setId: string;
  onError: (msg: string) => void;
}) {
  const [photos, setPhotos] = useState<PhotoRow[]>([]);
  const [observations, setObservations] = useState<Observation[] | null>(null);
  const [couldNotSee, setCouldNotSee] = useState("");
  const [problems, setProblems] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [kept, setKept] = useState<Set<number>>(new Set());
  const picker = useRef<HTMLInputElement | null>(null);

  const load = useCallback(async () => {
    try {
      setPhotos((await api.sitePhotos(setId)).photos);
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    }
  }, [setId, onError]);

  useEffect(() => {
    void load();
  }, [load]);

  const upload = async (files: FileList | null) => {
    if (!files?.length) return;
    setBusy(true);
    try {
      for (const file of Array.from(files)) await api.uploadSitePhoto(setId, file);
      await load();
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const read = async () => {
    setBusy(true);
    try {
      const body = await api.readSitePhotos(setId);
      setObservations(body.observations);
      setCouldNotSee(body.could_not_see);
      setProblems(body.problems);
      setKept(new Set());
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const keep = async (index: number, observation: Observation) => {
    try {
      await api.addCondition(setId, observation.as_condition ?? observation.what_i_see);
      setKept((s) => new Set(s).add(index));
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <div className="min-h-0 flex-1 overflow-y-auto p-4">
      <div className="flex items-baseline gap-3">
        <SectionLabel>SITE PHOTOGRAPHS · {photos.length}</SectionLabel>
        <input
          ref={picker}
          type="file"
          accept="image/*"
          multiple
          className="hidden"
          onChange={(e) => void upload(e.target.files)}
        />
        <Button onClick={() => picker.current?.click()} disabled={busy}>
          Add photographs
        </Button>
        {photos.length > 0 && (
          <Button variant="brass" onClick={() => void read()} disabled={busy}>
            {busy ? "Looking…" : "Read them"}
          </Button>
        )}
      </div>
      <p className="mt-1 max-w-[720px] font-cb-sans text-[10.5px] leading-[1.55] text-cb-muted">
        Read with vision alongside the station schedule and your own captions. What comes back is
        what is <strong>visible</strong>, with the photograph named — never an access class and
        never a cost. Keep the ones that matter and they become conditions on the Costing step,
        where the model proposes which input they move and you confirm.
      </p>

      {photos.length > 0 && (
        <div className="mt-3 grid gap-2 [grid-template-columns:repeat(auto-fill,minmax(150px,1fr))]">
          {photos.map((photo) => (
            <figure key={photo.photo_id} className="rounded-cb-card border border-cb-border bg-cb-page">
              <img
                src={api.sitePhotoUrl(setId, photo.photo_id)}
                alt={photo.caption || photo.filename}
                className="h-[110px] w-full rounded-t-cb-card object-cover"
              />
              <figcaption className="px-2 py-1.5">
                <div className="truncate font-cb-mono text-[10px] text-cb-ink-text">
                  {photo.filename}
                </div>
                {photo.station && (
                  <div className="font-cb-mono text-[10px] text-cb-brass-text">{photo.station}</div>
                )}
                {photo.caption && (
                  <div className="font-cb-sans text-[10px] leading-[1.4] text-cb-muted">
                    {photo.caption}
                  </div>
                )}
                <button
                  type="button"
                  onClick={async () => {
                    try {
                      await api.deleteSitePhoto(setId, photo.photo_id);
                      await load();
                    } catch (e) {
                      onError(e instanceof Error ? e.message : String(e));
                    }
                  }}
                  className="cb-press mt-0.5 font-cb-sans text-[10px] text-cb-faint underline underline-offset-2"
                >
                  remove
                </button>
              </figcaption>
            </figure>
          ))}
        </div>
      )}

      {problems.map((problem) => (
        <div
          key={problem}
          className="mt-3 rounded-cb-card border border-cb-brass-line bg-cb-brass-tint px-3 py-2 font-cb-sans text-[10.5px] leading-[1.5] text-cb-brass-text"
        >
          {problem}
        </div>
      ))}

      {observations && (
        <div className="mt-5">
          <SectionLabel>WHAT IS VISIBLE · {observations.length}</SectionLabel>
          {!observations.length && (
            <p className="mt-1 font-cb-sans text-[10.5px] text-cb-muted">
              Nothing the photographs support. An empty list is a correct answer and is better
              than a plausible one.
            </p>
          )}
          <div className="mt-2 flex flex-col gap-2">
            {observations.map((observation, index) => (
              <Card key={index} selected={kept.has(index)}>
                <div className="flex flex-wrap items-baseline gap-2">
                  <span className="rounded-cb-chip bg-cb-panel px-1.5 py-[1px] font-cb-mono text-[10px] font-semibold tracking-cb-chip text-cb-muted">
                    {TOPIC_LABEL[observation.topic] ?? observation.topic.toUpperCase()}
                  </span>
                  <span
                    className={cx(
                      "font-cb-mono text-[10px] font-semibold tracking-cb-chip",
                      observation.confidence === "low" ? "text-cb-brass-text" : "text-cb-faint",
                    )}
                  >
                    {observation.confidence.toUpperCase()} CONFIDENCE
                  </span>
                  <span className="ml-auto font-cb-mono text-[10px] text-cb-faint">
                    {observation.photo_refs.join(" · ")}
                  </span>
                </div>
                <p className="mt-1 font-cb-serif text-[12px] leading-[1.5] text-cb-ink-text">
                  {observation.what_i_see}
                </p>
                {observation.why_it_might_matter && (
                  <p className="mt-1 font-cb-sans text-[10.5px] leading-[1.5] text-cb-muted">
                    {observation.why_it_might_matter}
                  </p>
                )}
                {observation.corroboration && (
                  <p className="mt-1 font-cb-sans text-[10px] leading-[1.45] text-cb-brass-text">
                    ⌞ {observation.corroboration}
                  </p>
                )}
                <div className="mt-2 flex items-center gap-3">
                  {kept.has(index) ? (
                    <span className="font-cb-mono text-[10px] font-semibold tracking-cb-chip text-cb-ok-dark">
                      RECORDED AS A CONDITION — CONFIRM IT ON THE COSTING STEP
                    </span>
                  ) : (
                    <>
                      <Button onClick={() => void keep(index, observation)}>
                        Keep as a condition
                      </Button>
                      <span className="font-cb-sans text-[10px] text-cb-faint">
                        Recording it writes nothing. The Costing step proposes which input it
                        moves, and you confirm there.
                      </span>
                    </>
                  )}
                </div>
              </Card>
            ))}
          </div>
          {couldNotSee && (
            <p className="mt-3 max-w-[720px] rounded-cb-card border border-dashed border-cb-border-strong px-3 py-2 font-cb-sans text-[10px] leading-[1.5] text-cb-muted">
              <span className="font-cb-mono text-[10px] font-semibold tracking-cb-chip">
                WHAT THE PHOTOGRAPHS DO NOT SHOW ·{" "}
              </span>
              {couldNotSee}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
