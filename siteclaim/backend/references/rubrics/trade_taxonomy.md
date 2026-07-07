# Trade Taxonomy — canonical HK construction trades (v2)

The canonical list of trades a tender is split into. **Layer 1 checks the scope
split against this list** (deterministic): a returned trade must map to one of
these canonical names, or it is flagged for review. The LLM may use richer
phrasing, but every `TradeWorkPackage.trade` is normalised to a canonical key here.

| Canonical key | Label | Typical scope |
| --- | --- | --- |
| `foundation_substructure` | Foundation & substructure | Piling, pile caps, ground beams, basement |
| `ground_investigation` | Ground investigation | Boreholes, rotary drilling, sampling, in-situ & field testing (GI field works) |
| `field_testing` | Field & in-situ testing | In-situ and materials testing — soil/rock testing, loading tests, field testing (GI sub-trade) |
| `field_installations` | Field installations | GI field instrumentation — piezometers, standpipes, inclinometer installation (GI sub-trade) |
| `geophysical_survey` | Geophysical survey | Geophysical methods — borehole televiewer, GPR, resistivity, seismic survey (GI sub-trade) |
| `structural` | Structural steel | Steelwork, connections, metal decking |
| `reinforced_concrete` | Reinforced concrete | Formwork, rebar fixing, concreting |
| `electrical` | Electrical | LV distribution, containment, power & lighting |
| `mechanical_plumbing` | Mechanical & plumbing | HVAC, ductwork, pipework, drainage |
| `fire_services` | Fire services | Sprinklers, hydrants, detection & alarm |
| `joinery_fitting_out` | Joinery & fitting-out | Partitions, ceilings, doors, finishes |
| `builders_work` | Builder's work | Builder's work in connection (BWIC), making good |
| `external_works` | External works | Roads, drainage, landscaping, hardstanding |

## Normalisation notes
- Match is case-insensitive on the label or the key; near-synonyms map to the
  nearest canonical key (e.g. "E&M — electrical" → `electrical`).
- A trade with no match is **not** silently dropped — it is surfaced as an
  unmapped trade for human review.
- The taxonomy is versioned; bump the version when a key is added or renamed.
- v2 adds `ground_investigation` (GI field works — boreholes, drilling, site
  investigation). It is only justified because real GI specialist firms carry it (the
  normalizer is shared with the shortlist), so `geotechnical` / `site investigation` /
  `drilling` now resolve to it instead of falling unmapped.
- v3 promotes the three GI **specialty** sub-trades — `field_testing`,
  `field_installations`, `geophysical_survey` — to first-class canonical keys. The
  register loader already tags real firms with them, so a Ground Investigation section
  can shortlist against its own specialist pool (with `ground_investigation` as the
  parent fallback, see `rules_engine.taxonomy.parent_trade`) instead of the coarse
  parent pool. They stop falling unmapped.
