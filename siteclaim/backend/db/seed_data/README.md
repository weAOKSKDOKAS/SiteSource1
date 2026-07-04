# Seed data notes

## Data-curation TODO — landscaping specialist pool

The landscape / tree-works scope of a ground-investigation tender currently maps to
`external_works`, and the screened public pool for that trade includes general civil
giants (Dragages, Leighton, Samsung C&T — main-contractor scale, not landscape
subcontractors). Live shortlisting therefore returns firms that would never price a
landscaping package.

This is a **data task, not a code task**: curate a landscaping specialist pool from the
DEVB Landscaping category — real firms, individually verified — and register them under
a dedicated trade so the taxonomy can route landscape scope to them. Do **not**
hard-filter `external_works` in code, and do **not** invent placeholder landscape firms;
the shortlist cap (`k`) bounds the noise until the curated pool lands.
