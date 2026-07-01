# Stage 03 — Dispatch (Layer 4 gate, Layer 2 email, mock outbox / real SMTP)

## Inputs
- `ShortlistSet` and `approvals` (`dict[trade, list[firm_id]]`) — the human gate.
- Optionally (live path): the `TenderPackage` and a `Workspace`, for real attachments.

## Process
For each approved firm, assemble a `DispatchBundle`: `bundle_doc_refs` lists only
that firm's trade documents (labels), and Layer 2 composes a professional,
trade-specific `email_subject`/`email_body`. Status moves drafted -> approved.

Phase A adds routed real files (`attachments.py`): `attachments` carries the general
documents (whole), this trade's specific documents (whole), and a generated per-trade
SoR sheet labelled an excerpt. Whole-file routing only — no page is sliced out of a
combined legal PDF.

Transport: `mailer.send_bundles` sends real email via stdlib SMTP, but only off
DEMO_MODE, off `dry_run`, and with `SMTP_HOST` set; otherwise it records to the mock
outbox (`db/outbox.py`) exactly as before. **Nothing touches the network in
DEMO_MODE.** A firm with no address-book contact is marked `send_failed`.

## Outputs
- `DispatchSet` — the per-firm bundles: `sent_mock` (mock/dry), `sent` (real SMTP),
  or `send_failed` (no contact).
