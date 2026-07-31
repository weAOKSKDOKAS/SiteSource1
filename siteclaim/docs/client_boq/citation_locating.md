# Citation locating — how a cited quotation is proved against the document

**Built 2026-07-30 (backlog T7).** This note records what was measured before building, why the
design has three outcomes instead of two, and what it does not cover.

Code: `client_boq/ingest/pdfops.py` (`locate`, `has_text_layer`, `_variants`, `_search_fragments`)
and `client_boq/review/s08_citation_verify.py` (`locate_citations`).
API: `GET /client-boq/review/{set_id}/citations`.

---

## 1. The problem

A register line cites a clause and quotes its wording. Two things could be wrong with that, and
they are not the same thing:

- the clause or the quotation might not exist in the parse — **`verify_citations` already caught
  this**, by index lookup, since the module was built;
- the quotation might not exist **in the document**, or might sit on a different page from the one
  recorded. Nothing checked this. `ClauseItem.page` was supplied by the model and never verified.

That mattered for two reasons. A viewer that deep-links "show me this clause" would land on a page
the model guessed. And a paraphrase — same meaning, different words — passes the parse guard
happily, because the parse is itself what the model produced.

## 2. What was measured first

Rather than assume how often PDF text search fails on text that is genuinely present, it was
measured against the real tenders in this workspace.

**Single-line quotations, lifted verbatim from the page and searched for again:**

| Documents | Quotations tested | Found by exact search |
|---|---|---|
| ND GCT, ND SCT, ND NTT, CIC CT, CIC COE, CIC CSR | 1,769 | **1,769 (100%)** |

**Characters that commonly defeat a search:**

| Document | Pages | Ligatures | Soft hyphens | NBSP | Curly quotes | En/em dashes |
|---|---|---|---|---|---|---|
| ND GCT | 16 | 0 | 0 | 0 | 81 | 3 |
| ND SCT | 10 | 0 | 0 | 0 | 27 | 0 |
| ND NTT | 12 | 0 | 0 | 0 | 46 | 7 |
| CIC CT | 12 | 0 | 0 | 32 | 31 | 16 |
| CIC COE | 25 | 0 | 0 | 122 | 44 | 0 |
| CIC CSR | 10 | 0 | 0 | 0 | 1 | 2 |

Two conclusions, and both corrected an assumption:

1. **Ligatures and soft hyphens are a non-issue here** — zero across 85 pages. The worry that
   `fi`-ligatures would generate false alarms was misplaced for these documents.
2. **Curly punctuation is the real hazard.** It is everywhere, and it defeated a live search
   during verification: a quotation retyped with a straight apostrophe (`CIC's`) does not match a
   typeset one (`CIC’s`). They are visually identical and different characters.

A second probe on multi-line quotations initially suggested a 48% failure rate. That figure was
wrong and is recorded here so nobody repeats it: the test built its "quotations" by gluing three
consecutive rendered lines, which on a contents page produces text that was never a sentence
(`"One tender only for holding companies… Admission, promotion and confirmation t"`). PyMuPDF's
`search_for` handles a genuinely line-wrapped clause and returns one rectangle per wrapped
segment. **The measurement was the test's fault, not the library's.**

## 3. The design

### Three outcomes, not two

A failed search has two very different causes, and lumping them together is what turns a warning
into noise people learn to ignore.

| Verdict | Meaning | Effect on the register |
|---|---|---|
| `located` | Found. The page is **measured**, and rectangles are returned. | The measured page overwrites the claimed one. |
| `unverifiable` | The part could not be searched — image-only, no text layer, or the clause maps to no held part. | **Nothing.** Blaming the citation for the document's shortcoming would be wrong. |
| `not_located` | The part is searchable, other citations in it *were* found, and this one still is not. | Marked `citation_failed`. |

Two parts of the reference 325 tender (`01-inv`, `10-gcc`) are image-only scans. Under a two-way
design every citation in them would be flagged as untrustworthy, which is false and would train
the user to dismiss the flag.

### Corroboration before accusation

The rule that makes `not_located` trustworthy: **a citation is only called wrong when at least one
other citation from the same part was located.** That proves the text layer, the page range and
the parse all correspond for that document, so a remaining miss is about the quotation.

Without it, any mismatch between parse and file — a re-split, the wrong upload, or an offline
fixture whose parse has no relationship to the bytes — would condemn every citation at once. The
whole-part fallback is `unverifiable` with the note "the parse and the file may not correspond".

### The search ladder

`pdfops.locate` tries, in order, stopping at the first hit:

1. the whole quotation, whitespace-collapsed;
2. each of its sentences, longest first;
3. a long leading run (60% of it), for a quotation whose tail wandered into another column.

Each is tried in **three typographic variants**: as given, fully curly, and fully flattened.

Anything below 45 characters is refused outright. A short fragment matches by accident, and a
citation confirmed by accident is worse than one left unconfirmed.

### Coordinates

Rectangles come back as **fractions of page width and height**, not points, so a viewer can
overlay them at any zoom or render DPI without knowing what scale the page was rasterised at.
Page numbers are offset into the **source document's** numbering: a part cut from page 17 of a
binder reports page 17, not its own page 1.

## 4. Verified against the real tender

Against the CIC (325) Conditions of Tender, part `02_CT` (binder pages 5-16):

- Three real clauses, quoted verbatim: all located, on binder page 12, with rectangles.
- The same three, paraphrased: all three correctly **not** found.
- A quotation with an invented trailing sentence: still located, reported as a `fragment` match.
- Both image-only parts (`01_INV`, `10_GCC`): correctly reported as having no text layer.

## 5. What this does not do

- **It does not render pages.** There is no page-image endpoint, so a side-by-side viewer cannot
  yet display the highlight. That is deliberate: eager versus lazy rendering, DPI and thumbnail
  sizing are decided by the layout, and the frontend design is not settled.
- **It does not OCR.** A scanned part stays `unverifiable`; it is not read in order to search it.
- **The hard document classes are unmeasured.** Everything tested is single-column, born-digital
  text. The multi-column Particular Specification files (which `doc_index.py` already needs
  column-aware word-box scanning for), the BQ's table structures, and OCR'd pages are the cases
  most likely to produce a false `not_located`, and none of them has been measured. The
  corroboration rule limits the damage — a part where nothing matches degrades to `unverifiable`
  rather than accusing everything — but a part where *some* clauses match and the column-broken
  ones do not would produce false accusations. If that shows up in use, the fix is to lower the
  fragment floor for parts known to be multi-column, not to weaken the verdict.
- **It does not re-run automatically.** Locations are computed during the review and on demand via
  the endpoint. A re-split or an addendum does not recompute them until the review runs again.
