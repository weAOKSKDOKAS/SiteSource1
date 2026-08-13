"""The whole-tender ground — everything the tender knows, assembled deterministically.

One module, pure reads, no model call anywhere (plan Phase 4, layer 1). This generalises the
chat's `_ground_for`: the chat grew source families one at a time as screens appeared, and the
brain needs all of them at once — the register, the engine's figures, the site, the tender's own
memory, and now the gates, the parts, the scope of record, the bill's state, the sweep and the
open questions. The chat and the brain read the SAME assembly, so a fact one can see is never
invisible to the other.

Two rules carried from the chat's ground and enforced here for every family:

* **Absence is named, never blank.** A gate not passed, a part that could not be read, an
  unrouted sweep cost — each is a sentence in the ground, because "the model was not told" and
  "there is nothing to tell" must not look alike.
* **Labels say what a thing IS.** `discussion:` is a conversation, `condition:` carries its
  status in words, `gate:` is a state — so anything citing the ground names the KIND of authority
  it leans on, and a reader can weigh it accordingly.

The engine-derived block (`costing=`) is injected by the caller rather than computed here:
`_costing` is the router's single whole-engine path, and this module must not import the router.
``None`` is honest — a tender with no bill grounds everything else and says the bill is absent.

Truncation caps are per family, deliberately: the ground's history is a 400-page binder blowing
an 8,000-token budget (root CLAUDE.md §5), and a cap that silently ate the newest entries was
already found and fixed once (the conditions window). Every capped family keeps its NEWEST or
highest-signal entries and the cap is visible in the code beside the family it bounds.
"""

from __future__ import annotations

from typing import Optional

from client_boq import store
from client_boq.boq import access as boq_access
from client_boq.boq import ask as boq_ask

#: Every family `assemble` knows. A subagent read that wants only the legals asks for a slice by
#: name; an unknown name is a KeyError at the call site, not a silently empty ground.
FAMILIES = ("meta", "gates", "register", "summary", "parts", "scope", "site", "photos",
            "conditions", "log", "costing", "bill", "sweep", "rfis")


def assemble(conn, set_id: str, *, costing: Optional[dict] = None,
             families: Optional[set[str]] = None) -> "boq_ask.Ground":
    """Assemble what an answer — or a briefing — is allowed to rest on.

    ``families`` narrows the read (the brain's per-family subagent slices); None = everything.
    ``costing`` is the router's `_costing` output for this set, or None when there is no bill.
    """
    wanted = set(families) if families is not None else set(FAMILIES)
    unknown = wanted - set(FAMILIES)
    if unknown:
        raise KeyError(f"unknown ground families: {sorted(unknown)}")
    ground = boq_ask.Ground()

    if "meta" in wanted:
        _meta(conn, set_id, ground)
    if "register" in wanted:
        _register(conn, set_id, ground)
    if "summary" in wanted:
        _summary(conn, set_id, ground)
    if "parts" in wanted:
        _parts(conn, set_id, ground)
    if "scope" in wanted:
        _scope(conn, set_id, ground)
    if "costing" in wanted and costing is not None:
        _costing_figures(costing, ground)
    if "site" in wanted:
        _site(conn, set_id, ground)
    if "photos" in wanted:
        _photos(conn, set_id, ground)
    if "conditions" in wanted:
        _conditions(conn, set_id, ground)
    if "log" in wanted:
        _log(conn, set_id, ground)
    if "bill" in wanted:
        _bill(conn, set_id, ground)
    if "sweep" in wanted:
        _sweep(conn, set_id, ground)
    if "rfis" in wanted:
        _rfis(conn, set_id, ground)

    # THE STRUCTURAL STATE RIDES ALONG, NEVER ALONE. Gate states and the no-bill absence line are
    # true of a tender nobody has touched, so on their own they are not ground — an answer resting
    # on nothing but "nothing is approved and there is no bill" is the no-ground refusal wearing
    # sources. They are added only once some real content exists for them to qualify.
    if ground.sources:
        if "gates" in wanted:
            _gates(conn, set_id, ground)
        if "bill" in wanted and "bill" not in ground.sources:
            ground.sources["bill"] = (
                "no bill of quantities has been imported for this tender — nothing here can be "
                "priced yet, and no figure exists to quote.")
    return ground


# ---------------------------------------------------------------------------
# The families the chat already had — moved verbatim, labels unchanged
# ---------------------------------------------------------------------------
def _register(conn, set_id: str, ground: "boq_ask.Ground") -> None:
    register = store.load_register(conn, set_id)
    if register is None or not register.items:
        return
    for item in register.items[:60]:
        # THE FIELDS ARE `DepartureItem`'s — see test_ask_is_grounded_in_fields_that_exist.
        label = f"register:{item.criterion_id or item.clause or item.item}"
        said = " ".join(part for part in (
            item.clause_area,
            f"({item.category})" if item.category else "",
            item.extracted_value,
            item.rationale,
            item.proposed_position,
            f"Cited: {item.cited_text}" if item.cited_text else "",
        ) if part)
        # `status` is excluded from the emptiness test on purpose: it always has a value, so
        # including it would make a line with no substance look like ground worth citing.
        body = said or f"register line {item.item} carries no text."
        ground.sources[label] = f"{body[:1200]} Status: {item.status}."


def _costing_figures(costing: dict, ground: "boq_ask.Ground") -> None:
    programme = costing["programme"]
    ground.figures.update({
        "rock_fraction": f"rock fraction of the works: {programme.rock_fraction:.1%}",
        "work_days": f"work-days at P50: {programme.work_days:,.0f}",
        "rigs_required": f"rigs required: {programme.rigs_required}",
        "standing_hours": f"standing time: {programme.standing_hours:,.0f} hours",
        "total": f"the priced bill total: {costing['priced'].total:,.2f}",
    })
    ground.sources["programme"] = (
        f"Derived from the bill: {programme.work_days:,.0f} work-days at P50 over "
        f"{programme.rigs_required} rig(s); band "
        f"{programme.band.label if programme.band else 'none selected'}.")
    balance = costing.get("conservation")
    if balance is not None:
        ground.sources["conservation"] = balance.headline()[:600]


def _site(conn, set_id: str, ground: "boq_ask.Ground") -> None:
    schedule, _meta_row = store.load_station_schedule(conn, set_id)
    if schedule is None or not schedule.stations:
        return
    board = boq_access.board(
        schedule, set_id=set_id,
        classes={n: (r.get("access_class") or "")
                 for n, r in store.load_station_classes(conn, set_id).items()},
        road_points=store.load_road_points(conn, set_id))
    for item in board.clusters[:20]:
        ground.sources[f"location:{item.label}"] = (
            f"{item.holes} hole(s) at {item.lat:.5f}, {item.lon:.5f}, spread "
            f"{item.spread_m:,.0f} m; {item.undecided} still unclassed. "
            + " ".join(item.notes))


def _photos(conn, set_id: str, ground: "boq_ask.Ground") -> None:
    for photo in store.load_site_photos(conn, set_id)[:40]:
        if photo["caption"] or photo["station"]:
            ground.sources[f"photo:{photo['filename']}"] = (
                f"{photo['caption']}"
                + (f" (station {photo['station']})" if photo["station"] else ""))


def _conditions(conn, set_id: str, ground: "boq_ask.Ground") -> None:
    # NEWEST 40, matching the log's newest-12 window — `load_conditions` is oldest-first.
    for row in store.load_conditions(conn, set_id)[-40:]:
        status = {"confirmed": "CONFIRMED by " + (row.get("decided_by") or "someone"),
                  "rejected": "REJECTED — do not rely on it"}.get(
                      row.get("status") or "", "recorded, not yet decided")
        ground.sources[f"condition:{row['condition_id']}"] = (
            f"{row['text'][:400]} [{status}]"
            + (f" (born of discussion #{row['born_of_seq']})" if row.get("born_of_seq") else ""))


def _log(conn, set_id: str, ground: "boq_ask.Ground") -> None:
    for entry in store.load_site_log(conn, set_id, limit=12):
        body = entry["answer"] or entry["cannot_answer"]
        ground.sources[f"discussion:{entry['seq']}"] = (
            f"{entry['asked_by'] or 'someone'} asked: {entry['question'][:300]} — the grounded "
            f"answer was: {body[:600]}"
            + (f" It suggested recording: {entry['proposes'][:200]}" if entry["proposes"] else ""))


# ---------------------------------------------------------------------------
# The families the brain adds
# ---------------------------------------------------------------------------
def _meta(conn, set_id: str, ground: "boq_ask.Ground") -> None:
    row = store.load_set(conn, set_id)
    meta = store.load_set_meta(conn, set_id)
    if row is None and not any(meta.get(k) for k in ("client", "package", "close_date")):
        return
    close = meta.get("close_date") or ""
    ground.sources["tender"] = (
        f"{(row or {}).get('name') or set_id}"
        + (f" — client: {meta['client']}" if meta.get("client") else "")
        + (f"; package: {meta['package']}" if meta.get("package") else "")
        + (f"; closes {close} ({meta.get('close_date_status') or 'reading'})" if close else
           "; no close date is known yet"))


def _gates(conn, set_id: str, ground: "boq_ask.Ground") -> None:
    """The gate STATES, as facts. A gate is a person's act; reporting one open is not an
    instruction to close it — which is exactly why the brain may only propose the screen."""
    states = (
        ("gate:manifest", store.manifest_is_approved(conn, set_id),
         "the split manifest", "nothing can be split or reviewed by parts until it is"),
        ("gate:review", store.review_is_approved(conn, set_id),
         "the departure register", "the estimate's scope cannot start until it is"),
        ("gate:scope", store.scope_is_approved(conn, set_id),
         "the estimate scope", "the estimate cannot run until it is"),
    )
    for label, approved, what, consequence in states:
        ground.sources[label] = (
            f"{what} is {'APPROVED' if approved else 'NOT yet approved'}"
            + ("" if approved else f" — {consequence}") + ".")


def _summary(conn, set_id: str, ground: "boq_ask.Ground") -> None:
    summary = store.load_summary(conn, set_id)
    if summary is None or not summary.summary:
        return
    extras = []
    if summary.obligations:
        extras.append(f"Obligations: {'; '.join(summary.obligations[:6])}")
    if summary.clarifications:
        extras.append(f"To clarify: {'; '.join(summary.clarifications[:6])}")
    ground.sources["summary"] = f"{summary.summary[:800]} " + " ".join(extras)


def _parts(conn, set_id: str, ground: "boq_ask.Ground") -> None:
    for spec, _path, context in store.load_parts(conn, set_id)[:40]:
        if not context.readable:
            # An unread part in the ground reads as unread — a briefing that leans on it would
            # be leaning on pages nobody has seen, and saying so is the defence.
            ground.sources[f"part:{spec.part_id}"] = (
                f"{spec.title or spec.part_id} ({spec.category}) — NOT READABLE: these pages "
                f"carry no usable text and have not been read. Nothing can be claimed from them.")
            continue
        body = context.summary or "(no summary was written for this part)"
        ground.sources[f"part:{spec.part_id}"] = (
            f"{spec.title or spec.part_id} ({spec.category}, pages {spec.start}–{spec.end}): "
            f"{body[:400]}"
            + (f" Flags: {'; '.join(context.commercial_flags[:4])}"
               if context.commercial_flags else ""))


def _scope(conn, set_id: str, ground: "boq_ask.Ground") -> None:
    items = store.load_scope_items(conn, set_id)
    if not items:
        return
    fallbacks = [i for i in items if i.is_fallback and not i.accepted]
    if fallbacks:
        ground.sources["scope:fallbacks"] = (
            f"{len(fallbacks)} scope line(s) are machine fallbacks NOBODY HAS ACCEPTED — each is "
            f"a guess sitting where a decision should be, and the freeze gate counts them: "
            + "; ".join(f"{i.item_id} ({i.title[:60]})" for i in fallbacks[:8]))
    for item in items[:30]:
        ground.sources[f"scope:{item.item_id}"] = (
            f"[{item.section}] {item.title[:80]}: {item.text[:300]} "
            f"(badge {item.badge}"
            + (", UNACCEPTED FALLBACK" if item.is_fallback and not item.accepted else "") + ")")


def _bill(conn, set_id: str, ground: "boq_ask.Ground") -> None:
    bill = store.load_bill(conn, set_id, None)
    if bill is None:
        # The ABSENCE line is added by `assemble`'s structural block, and only once some real
        # content exists — "there is no bill" is true of a tender nobody has touched, and on its
        # own it is not ground.
        return
    rates = store.load_bill_rates(conn, set_id, bill.rev)
    pending = store.bill_review_pending(conn, set_id, bill.rev)
    leaf = [i for i in bill.items if not i.is_parent]
    ground.sources["bill"] = (
        f"revision {bill.rev}: {len(leaf)} priceable item(s); {len(rates)} carry a stored rate "
        f"or build-up; {len(pending)} carried rate(s) have not been looked at since the last "
        f"revision" + (f" ({', '.join(p['full_ref'] for p in pending[:6])})" if pending else "")
        + ".")


def _sweep(conn, set_id: str, ground: "boq_ask.Ground") -> None:
    bill = store.load_bill(conn, set_id, None)
    if bill is None:
        return
    sweep = store.load_sweep(conn, set_id, bill.rev)
    if not sweep.costs:
        return
    undecided = [c for c in sweep.costs if not c.route]
    routed = [c for c in sweep.costs if c.route]
    ground.sources["sweep"] = (
        f"{len(sweep.costs)} cost(s) with no bill item. "
        + (f"{len(undecided)} UNROUTED — the app's only hard stop; each is a promise to do that "
           f"work for nothing until somebody routes it: "
           + "; ".join(f"{c.label} ({c.amount:,.0f})" for c in undecided[:6]) + ". "
           if undecided else "All routed. ")
        + (f"Routed: " + "; ".join(
            f"{c.label} → {c.route}" + (f" onto {c.target_ref}" if c.target_ref else "")
            for c in routed[:8]) if routed else ""))


def _rfis(conn, set_id: str, ground: "boq_ask.Ground") -> None:
    rfis = store.load_rfis(conn, set_id)
    for rfi in rfis[:20]:
        answered = f"ANSWERED ({rfi.answered_by}): {rfi.answer[:200]}" if rfi.answer else (
            f"status {rfi.status} — no answer yet")
        ground.sources[f"rfi:{rfi.rfi_id}"] = f"{rfi.question[:300]} [{answered}]"
