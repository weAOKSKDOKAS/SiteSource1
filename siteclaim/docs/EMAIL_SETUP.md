# Email setup — Gmail drafts out + the backend reply poller in (no n8n)

Everything here is configuration; no code changes. Credentials are the operator's task
and live only in `backend/.env` (gitignored — never commit them).

> **Migration note.** n8n is gone: it was the transport on both directions (the
> Gmail-draft webhook outbound, the Gmail trigger inbound) and failed repeatedly —
> `ConnectionRefused` with n8n down, OAuth tokens expiring weekly in Testing mode, the
> trigger silently not firing — while requiring a second always-on process. Delete the
> two n8n workflows and remove `N8N_DRAFTS_WEBHOOK` from `backend/.env`; the backend now
> talks to the Gmail API directly on both directions.

## 1. Google OAuth — the one-time setup (both directions)

The operator's existing Google Cloud project (Gmail API already enabled) is reused:

1. **Publish the OAuth consent screen to Production** (APIs & Services → OAuth consent
   screen). This is the fix for the recurring 7-day pain: a *Testing* consent screen
   expires its refresh tokens after 7 days; a *Production* one does not.
2. Create (or reuse) an **OAuth client ID** of type **Desktop app** and put both values
   in `backend/.env`:

   ```ini
   GOOGLE_CLIENT_ID=<...>.apps.googleusercontent.com
   GOOGLE_CLIENT_SECRET=<...>
   ```

3. Run the **one-time consent flow** on the operator's machine (it opens a browser
   against the watched inbox's Google account):

   ```bash
   cd backend
   python -m pipeline.gmail_client
   ```

   This writes the token file (`GMAIL_TOKEN_PATH`, default `backend/.gmail_token.json`,
   gitignored). After this the backend refreshes the token automatically — no weekly
   re-consent. Scopes requested: `gmail.compose` (create drafts) + `gmail.readonly`
   (poll replies); the backend never sends mail by itself.

Check it: `GET /integrations/gmail` reports `connected` / `not_configured` / `error`
with the exact next step, and the dispatch gate + Level & compare show the same as a
small pill — a broken credential is visible *before* a click, not after a failed action.
Set `SITESOURCE_GMAIL_LOG=gmail_calls.jsonl` for a JSONL line per Gmail call.

## 2. Outbound — Gmail drafts (the human gate holds)

"Prepare Gmail drafts" on the dispatch gate assembles each approved firm's relevant-only
bundle (the SR section slice, PS/MM clause slices, clarifications) and creates **one
Gmail DRAFT per firm** — subject carrying the correlation tag
`[SiteSource Ref: <tender>.<firm>.<trade>]`, recipient from the address book
(`contacts` table, `GET /contacts`). Nothing is auto-sent: the operator reviews and
sends from Gmail.

Failure semantics: a Gmail problem (missing credential, expired token, API error) never
fails the dispatch — the response lists `failed: [{firm_id, reason}]` with the fix, the
enquiries stay prepared in the outbox, and drafting can simply be run again. A firm with
no contact email is reported the same way, never silently skipped.

(Real SMTP send — `SMTP_*` in `.env.example` — remains available and unchanged for the
send-directly path; the mock outbox stays the default. `SMTP_FROM` must be the watched
inbox so replies land where the poller reads.)

## 3. Inbound — the backend reply poller

With `GMAIL_POLLING_ENABLED=true` (and `DEMO_MODE=false`) the backend polls the watched
inbox every `GMAIL_POLL_SECONDS` (default 120) for replies matching
`subject:"SiteSource Ref" has:attachment newer_than:7d`, extracts the ref from the
subject, downloads the attachments, and feeds the same processing path as
`/inbound-reply`: resolve the ref against the dispatch registry (deterministic — the AI
fallback only runs for a ref-less reply), parse the attachment (an xlsx — our own
returned SoR sheet — parses with no model call; a PDF/image goes through the vision
parse), route each line to its true SoR section by item identity, accumulate the reply
onto its tender, re-level, and regenerate the comparison xlsx.

- **Idempotent**: processed Gmail message ids are persisted
  (`processed_messages.json`, next to the dispatch registry), so re-reads never
  double-process — and a backend that was **off for days catches up on the next poll**
  (the replies sit in Gmail; nothing is lost).
- **Unresolvable refs are surfaced**, never dropped: the message is recorded
  `unmatched` and counted on `/integrations/gmail`.
- The poller never crashes the app: a failure records `last_error` and retries next
  tick. `/inbound-reply` remains available as a manual/testing entry point, and the
  manual "Upload a priced return" path is untouched.

## 4. The one-round-trip smoke

1. Seed a contact for a test firm pointing at your own address, then on the dispatch
   gate **Prepare Gmail drafts** — the draft appears in Gmail with the trade's sliced
   documents and the priced-return sheet attached, ref in the subject. Send it from
   Gmail (the human gate).
2. Reply to that email **keeping the subject**, attaching the SoR sheet with the Rate
   column filled (a priced reply — a blank sheet is a degenerate input and proves
   nothing).
3. Within one poll (`GMAIL_POLL_SECONDS`) the backend picks it up; `GET
   /integrations/gmail` shows `replies_processed` incremented and `GET /leveling.xlsx`
   reflects the new reply.
