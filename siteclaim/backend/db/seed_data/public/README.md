# Public-record seed data

`real_public_records.json` is the real Hong Kong public-register scrape (provenance
`public_register`, counted in `/coverage`). `seed_public_records.json` is the
illustrative demo stub (the 16 `F-*` firms; never counted). See `db/seed.py`.

## TODO — assemble the full ground-investigation population

v2 of the taxonomy added the `ground_investigation` trade. Six **verified-real** GI
field-works firms are seeded (all `trades: ["ground_investigation"]`, provenance
`public_register`):

- Geotechnics and Concrete Engineering (H.K.) Ltd. (GCE)
- Chung Shun Boring Engineering Company Limited (Wan Kei Group)
- Castco Testing Centre Limited
- DrilTech Ground Engineering Limited (Chinney Alliance Group)
- Kin Wing Engineering Limited (Chinney Kin Wing) — the only confirmed grade so far:
  Approved Specialist List, Ground Investigation Field Work, **Group II**
- Intrafor Hong Kong Limited (VSL) — the GE/2026/14 main contractor

Only Kin Wing's grade is confirmed; the others carry `registered_grade`/`value_band`
`null` with `confidence: "medium"` pending a register lookup. **No `public_flags` are
verified for any of them, so none carries a flag.**

The full GI population is likely a few dozen firms (one firm describes itself as one of
only a handful certified). Assemble the rest — and every firm's grade and any
suspension / disciplinary flag — from the two source registers, the same way the 134
building-trade firms were assembled, **with each firm and each flag verified before it
lands**. Do not fabricate a firm, a grade, or a flag to look complete.

Source registers:

- **DEVB Specialist List — Ground Investigation Field Work** category (Group I up to
  $3.7M, Group II unlimited), managed by CEDD's Geotechnical Engineering Office.
- **Buildings Department RSC(GIFW)** — Register of Specialist Contractors, Ground
  Investigation Field Works sub-register.

Both publish firms and both carry risk signals (DEVB suspension, BD disciplinary
actions) — capture those as `public_flags` only when verified against the register.
