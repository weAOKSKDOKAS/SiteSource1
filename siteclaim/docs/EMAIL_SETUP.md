# Email setup — real RFQ send + the n8n inbound reply loop

Everything here is configuration; no code changes. Credentials are the operator's task
and live only in `backend/.env` (gitignored — never commit them).

## 1. Outbound — real SMTP send (Stage 03)

Real send is gated three ways (`pipeline/stage_03_dispatch/mailer.py`): it happens only
when **all** hold — `DEMO_MODE=false`, the `/dispatch` request has `dry_run=false`, and
SMTP is configured (`SMTP_HOST` + a from-address). Anything else degrades to the mock
outbox, so a misconfigured run records instead of sending.

Set in `backend/.env` (see `.env.example`):

```ini
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_STARTTLS=true
SMTP_USER=<the watched inbox>@gmail.com
SMTP_PASSWORD=<Gmail App Password>       # Google account -> Security -> 2-Step -> App passwords
SMTP_FROM=<the watched inbox>@gmail.com  # defaults to SMTP_USER when unset
```

Notes:

- **Gmail needs an App Password** (2-Step Verification enabled); the account password
  will not work over SMTP.
- **`SMTP_FROM` must be the watched inbox** — subcontractors reply to it, and the n8n
  IMAP trigger below reads that same mailbox, closing the loop.
- Recipients come from the address book (`contacts` table, `GET /contacts`), keyed by
  firm + trade. A firm with no contact is marked `send_failed`, never silently dropped.
- Every dispatched subject carries the correlation tag `[SiteSource Ref:
  <tender>.<firm>.<trade>]`, and the mapping is recorded in the workspace registry —
  this is what lets a reply resolve deterministically.

## 2. Inbound — the n8n workflow (as configured)

One linear workflow: **IMAP trigger → IF → HTTP Request.**

**Email Trigger (IMAP)** on the watched inbox:

| Setting | Value |
| --- | --- |
| Format | Resolved |
| Download Attachments | on |
| Action | Mark as Read |
| Force Reconnect | every ~10 minutes |

**IF node** — continue only when the subject contains `SiteSource Ref:` (replies keep
the dispatched subject via "Re: …"; anything else is not a tracked reply).

**HTTP Request node** — `POST {backend}/inbound-reply` as `multipart/form-data`:

| Field | Type | Value |
| --- | --- | --- |
| `files` | binary | the attachment property `attachment_0` |
| `ref` | text | the ref captured off the subject, e.g. an expression using the regex `SiteSource Ref:\s*([^\]]+)` |

The backend resolves the ref against the dispatch registry (deterministic — the AI
fallback only runs for a ref-less reply), parses the attachment (an xlsx — our own
returned SoR sheet — parses with no model call; a PDF/image goes through the vision
parse), accumulates the reply onto its tender, re-levels, and regenerates the
comparison xlsx. An unresolvable reply returns `unmatched — needs manual assignment`;
nothing is guessed.

## 3. The one-round-trip smoke

1. Seed a contact for a test firm pointing at your own address, then `/dispatch` with
   `send=true` (DEMO off, SMTP configured) — the RFQ arrives with the trade's documents
   and the generated SoR sheet attached, ref in the subject.
2. Reply to that email **keeping the subject**, attaching the SoR sheet with the Rate
   column filled (a priced reply — a blank sheet is a degenerate input and proves
   nothing).
3. Within one IMAP poll n8n posts it to `/inbound-reply`; the response is `matched`
   with the growing comparison, and `GET /leveling.xlsx` reflects the new reply.
