"""Tiered item matcher for the benchmark spine (Phase B1d, §5c).

Match a project's tender_items to its actual_items so the human can confirm each pair:

* **Tier 1 — exact ``item_ref``.** Deterministic; the primary retrieval (HK SoR codes
  recur across a series). First-wins.
* **Tier 2 — embedding similarity** on description (``deterministic_embedding``, cosine ≥
  threshold) for lines whose refs did not match. Offline and deterministic in DEMO — this
  reuses the same runtime embedder ``db.store`` uses, never ``build_embeddings`` (which
  loads torch). Greedy best-first; below threshold the line is left unmatched.
* **Tier 3 — unmatched**, both directions: a tender line with no actual (omission
  candidate) and an actual line with no tender (arrived-unpriced). Coarse actuals
  (section/project granularity) are surfaced here too — they carry their own granularity.

The matcher only proposes; the confirm gate is the sole writer of variance records.
"""

from __future__ import annotations

from typing import Optional

from db.embeddings import deterministic_embedding

# Cosine acceptance threshold for Tier 2. Chosen conservative: the deterministic hashed
# bag-of-words embedder scores strong lexical overlap high, so 0.72 accepts clear
# description matches (e.g. "Rotary drilling in rock" ~ "Rotary drilling, rock") while
# leaving genuinely different lines to Tier 3 rather than forcing a low-confidence pair.
DEFAULT_TIER2_THRESHOLD = 0.72


def _cosine(a: list[float], b: list[float]) -> float:
    """Dot product — both vectors are already L2-normalised by ``deterministic_embedding``."""
    return sum(x * y for x, y in zip(a, b))


def _embed_text(item: dict) -> str:
    return (item.get("description") or "").strip() or (item.get("item_ref") or "")


def match(
    tender_items: list[dict], actual_items: list[dict], *, threshold: float = DEFAULT_TIER2_THRESHOLD,
) -> list[dict]:
    """Return proposed pairs, each ``{tier, tender, actual, similarity}`` (tender/actual are
    the row dicts or ``None``). Order: Tier 1, then Tier 2, then Tier 3 (omissions,
    arrived-unpriced, coarse)."""
    coarse = [a for a in actual_items if a.get("granularity", "item") != "item"]
    item_actuals = [a for a in actual_items if a.get("granularity", "item") == "item"]

    pairs: list[dict] = []
    used_actual: set = set()
    matched_tender: set = set()

    # -- Tier 1: exact item_ref -------------------------------------------------------
    by_ref: dict[str, list[dict]] = {}
    for a in item_actuals:
        by_ref.setdefault((a.get("item_ref") or "").strip(), []).append(a)
    for t in tender_items:
        ref = (t.get("item_ref") or "").strip()
        if not ref:
            continue
        cands = [a for a in by_ref.get(ref, []) if a["id"] not in used_actual]
        if cands:
            a = cands[0]
            used_actual.add(a["id"])
            matched_tender.add(t["id"])
            pairs.append({"tier": 1, "tender": t, "actual": a, "similarity": 1.0})

    # -- Tier 2: embedding similarity on the remainder --------------------------------
    rem_tender = [t for t in tender_items if t["id"] not in matched_tender]
    rem_actual = [a for a in item_actuals if a["id"] not in used_actual]
    if rem_tender and rem_actual:
        t_vecs = {t["id"]: deterministic_embedding(_embed_text(t)) for t in rem_tender}
        a_vecs = {a["id"]: deterministic_embedding(_embed_text(a)) for a in rem_actual}
        scored: list[tuple[float, dict, dict]] = []
        for t in rem_tender:
            for a in rem_actual:
                s = _cosine(t_vecs[t["id"]], a_vecs[a["id"]])
                if s >= threshold:
                    scored.append((s, t, a))
        # Greedy best-first; a tender/actual is used at most once. Tie-break by ids for
        # determinism.
        scored.sort(key=lambda x: (-x[0], x[1]["id"], x[2]["id"]))
        for s, t, a in scored:
            if t["id"] in matched_tender or a["id"] in used_actual:
                continue
            matched_tender.add(t["id"])
            used_actual.add(a["id"])
            pairs.append({"tier": 2, "tender": t, "actual": a, "similarity": round(s, 4)})

    # -- Tier 3: unmatched, both directions + coarse actuals --------------------------
    for t in tender_items:
        if t["id"] not in matched_tender:
            pairs.append({"tier": 3, "tender": t, "actual": None, "similarity": None})  # omission candidate
    for a in item_actuals:
        if a["id"] not in used_actual:
            pairs.append({"tier": 3, "tender": None, "actual": a, "similarity": None})  # arrived-unpriced
    for a in coarse:
        pairs.append({"tier": 3, "tender": None, "actual": a, "similarity": None})      # section/project total
    return pairs


# ---------------------------------------------------------------------------
# Deterministic reason pre-suggestion (a hint — the human still sets the code).
# Offline; no model. A live LLM refinement may be wired later behind text routing.
# ---------------------------------------------------------------------------
def suggest_reason(record: dict) -> Optional[str]:
    """A deterministic reason-code hint from the shape of a variance record. Never written
    without the human's confirmation (§5d)."""
    desc = ((record.get("item_ref") or "") + " " + (record.get("reason_note") or "")).lower()
    # Tier-3 shapes first.
    if record.get("tender_item_id") and not record.get("actual_item_id"):
        return "omission_at_tender"          # priced but no actual -> item not required / omitted
    if record.get("actual_item_id") and not record.get("tender_item_id"):
        return "scope_variation"             # arrived without a tender line -> instructed/extra
    if "standing" in desc:
        return "standing_time"
    dq, dr = record.get("amount_delta_qty"), record.get("amount_delta_rate")
    if dq is not None and dr is not None:
        # Attribute to the dominant driver.
        if abs(dq) > abs(dr) * 1.5:
            return "quantity_remeasure"
        if abs(dr) > abs(dq) * 1.5:
            return "rate_reprice"
    rd = record.get("rate_delta")
    if dq is None and rd is not None and abs(rd) > _threshold_rate_delta():
        return "rate_reprice"                # rate-only line moved
    return None


def _threshold_rate_delta() -> float:
    return 0.0
