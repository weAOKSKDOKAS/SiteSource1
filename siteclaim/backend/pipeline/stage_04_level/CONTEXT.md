# Stage 04 — Level (Layer 2 parse, Layer 1 arithmetic, Excel export)

## Inputs
- `list[BidReply]` (returned Schedules of Rates) and the `ScopePackages` basis.

## Process
Layer 2 parses each reply into line items, rates, and exclusions. Layer 1
(`rules_engine/leveling.py`, following `references/rubrics/leveling_rules.md`)
recomputes each amount as `qty x rate`, sums to `corrected_total`, records an
`ArithmeticFinding` per disagreeing line, treats a missing rate as a `scope_gap`
and a stated exclusion as a flagged non-comparable item, and never silently fills
a missing provisional sum. `normalized_total` puts every bid on the same basis.
An `openpyxl` export writes the comparison to `fixtures/out/leveling.xlsx`.

## Outputs
- `list[LevelledBid]` — corrected totals, arithmetic findings, exclusions, gaps.

## Inbound reply loop (`pipeline/reply_loop.py` + `POST /inbound-reply`)
Closes the loop so an emailed reply lands in the right tender's comparison without a
manual upload. On dispatch a stable ref `<tender>.<firm>.<trade>` is put in the email
subject (`[SiteSource Ref: ...]`) and recorded to a registry at the Workspace root. n8n
reads that ref off the reply's subject and POSTs the attachment + ref to
`/inbound-reply`, which resolves it deterministically (AI matching is only a fallback for
a ref-less reply — if it is not confident, the reply is returned `unmatched — needs
manual assignment`, never guessed). The reply is parsed (same `parse_bid_reply`),
accumulated per tender (deduped by firm), re-leveled over all of that tender's replies
with the same `level_bids` / `export_leveling_xlsx`, and the comparison xlsx regenerated.
Inbound fills the comparison only — a human still awards.

### Manual live check (not covered by the offline tests)
The offline tests drive the ref/registry/accumulate logic and the fallback via a fixture.
The full loop over a real inbox is verified by hand:

```
# manual: live reply-loop smoke (real key + SMTP + IMAP/n8n, DEMO_MODE off)
#   1. Dispatch one RFQ to a test address (POST /dispatch send=true with SMTP configured).
#      Confirm the subject carries [SiteSource Ref: <tender>.<firm>.<trade>].
#   2. Reply to that email with a sample priced Schedule of Rates attached, leaving the
#      subject (and its ref) intact.
#   3. The n8n IMAP/Gmail trigger reads the ref from the subject and POSTs the attachment
#      + ref to /inbound-reply.
#   4. Confirm the reply lands in that tender's comparison (reply_count grows; the firm
#      appears in the returned comparison and the regenerated xlsx).
# This manual run is what proves the live loop; the offline tests do NOT exercise the
# real inbox -> n8n -> parse path. Keep the two claims separate.
```
