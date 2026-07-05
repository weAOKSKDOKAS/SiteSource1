"""Corpus-gated rate suggestion (Phase P3c — Layer 1, deterministic, suggestion only).

For each estimate line, retrieve rate precedent from the benchmark corpus (the confirmed
``tender_items`` / ``variance_records`` archive) two ways:

* **Tier 1 — exact ``item_ref``** (deterministic; the primary retrieval — HK SoR codes recur
  across a series).
* **Tier 2 — embedding similarity** on description (``deterministic_embedding``, cosine ≥
  threshold) for lines whose ref found nothing. Offline and deterministic — the same runtime
  embedder the store and matcher use, never ``build_embeddings`` (torch).

It surfaces the historical tender-rate band plus any **rate warnings** — reason codes under
which this ref historically moved on *rate* (e.g. it over-ran on rate for ``standing_time``).
It is **corpus-gated**: when the archive holds no priced history (live, pre-archive) it returns
the honest empty state rather than fabricating a rate. Suggestion only; the person prices.
No LLM — pure retrieval.
"""

from __future__ import annotations

from db.embeddings import deterministic_embedding

DEFAULT_TIER2_THRESHOLD = 0.72  # mirrors the benchmark matcher's Tier-2 acceptance


def _cosine(a: list[float], b: list[float]) -> float:
    """Dot product — both vectors are already L2-normalised by ``deterministic_embedding``."""
    return sum(x * y for x, y in zip(a, b))


def _summarise(rows: list[dict]) -> dict:
    """The rate band + rate warnings for a set of matched corpus rows."""
    rates = sorted(r["tender_rate"] for r in rows if r["tender_rate"] is not None)
    warnings: dict[str, int] = {}
    for r in rows:
        rd = r.get("rate_delta")
        if r.get("reason_code") and rd not in (None, 0) and abs(rd) > 0:
            warnings[r["reason_code"]] = warnings.get(r["reason_code"], 0) + 1
    return {
        "sample_count": len(rows),
        "rate_low": rates[0] if rates else None,
        "rate_median": rates[len(rates) // 2] if rates else None,
        "rate_high": rates[-1] if rates else None,
        "rate_warnings": [{"reason_code": k, "count": v} for k, v in sorted(warnings.items(), key=lambda kv: -kv[1])],
    }


def _empty(item: dict) -> dict:
    return {
        "item_id": item.get("id"), "item_ref": (item.get("item_ref") or "").strip(),
        "tier": 0, "matched_ref": "", "similarity": None, "sample_count": 0,
        "rate_low": None, "rate_median": None, "rate_high": None, "rate_warnings": [],
    }


def suggest_rates(estimate_items: list[dict], corpus_rows: list[dict], *,
                  threshold: float = DEFAULT_TIER2_THRESHOLD) -> dict:
    """Return ``{corpus_empty, corpus_size, suggestions}`` — one precedent per estimate line
    (tier 1 exact ref, tier 2 similar description, tier 0 no precedent). Suggestion only."""
    by_ref: dict[str, list[dict]] = {}
    for r in corpus_rows:
        by_ref.setdefault((r["item_ref"] or "").strip(), []).append(r)

    corpus_vecs: list[tuple[dict, list[float]]] | None = None  # lazily built (Tier-2 only)
    suggestions: list[dict] = []
    for it in estimate_items:
        ref = (it.get("item_ref") or "").strip()
        exact = by_ref.get(ref) if ref else None
        if exact:
            suggestions.append({"item_id": it.get("id"), "item_ref": ref, "tier": 1, "matched_ref": ref,
                                "similarity": 1.0, **_summarise(exact)})
            continue

        desc = (it.get("description") or "").strip() or ref
        if desc and corpus_rows:
            if corpus_vecs is None:
                corpus_vecs = [(r, deterministic_embedding((r["description"] or r["item_ref"] or ""))) for r in corpus_rows]
            q = deterministic_embedding(desc)
            best: tuple[dict, float] | None = None
            for r, v in corpus_vecs:
                sc = _cosine(q, v)
                if sc >= threshold and (best is None or sc > best[1]):
                    best = (r, sc)
            if best is not None:
                mref = (best[0]["item_ref"] or "").strip()
                rows = by_ref.get(mref, [best[0]])
                suggestions.append({"item_id": it.get("id"), "item_ref": ref, "tier": 2, "matched_ref": mref,
                                    "similarity": round(best[1], 4), **_summarise(rows)})
                continue

        suggestions.append(_empty(it))

    return {"corpus_empty": len(corpus_rows) == 0, "corpus_size": len(corpus_rows), "suggestions": suggestions}
