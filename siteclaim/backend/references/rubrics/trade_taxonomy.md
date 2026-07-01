# Trade & work-section taxonomy — canonical construction work packages (v2)

The canonical list of work packages a tender is split into, grouped by tender
domain. **Layer 1 normalises the scope split against this list** (deterministic):
a returned trade or work section is mapped to one of these canonical keys where a
known label or synonym matches. The LLM may use richer phrasing, but every
`TradeWorkPackage.trade` is normalised to a canonical key here where possible.

**The taxonomy is advisory, not a whitelist.** It normalises *known* labels so the
same work package reads consistently across firms and tenders — but a tender may
legitimately use a work package outside this list (a specialist discipline, an
unusual section). An unmatched work package is **not** an error and **not** dropped:
it is kept under a slugified form of the tender's own label as a valid work-package
key, and surfaced for human review.

## Building / fit-out work packages
| Canonical key | Label | Typical scope |
| --- | --- | --- |
| `foundation_substructure` | Foundation & substructure | Piling, pile caps, ground beams, basement |
| `structural` | Structural steel | Steelwork, connections, metal decking |
| `reinforced_concrete` | Reinforced concrete | Formwork, rebar fixing, concreting |
| `electrical` | Electrical | LV distribution, containment, power & lighting |
| `mechanical_plumbing` | Mechanical & plumbing | HVAC, ductwork, pipework, building drainage |
| `fire_services` | Fire services | Sprinklers, hydrants, detection & alarm |
| `joinery_fitting_out` | Joinery & fitting-out | Partitions, ceilings, doors, finishes |
| `builders_work` | Builder's work | Builder's work in connection (BWIC), making good |
| `external_works` | External works | Roads, site drainage, landscaping, hardstanding |

## Civil / ground-investigation work packages
| Canonical key | Label | Typical scope |
| --- | --- | --- |
| `ground_investigation` | Ground investigation | Contract-wide GI scope, overall site investigation |
| `drilling` | Drilling | Rotary / percussive boreholes, drillholes |
| `sampling` | Sampling | Soil / rock / water sampling, undisturbed samples |
| `field_testing` | Field testing | In-situ tests — SPT, permeability, drainage field tests |
| `field_installations` | Field installations | Piezometers, standpipes, monitoring wells |
| `instrumentation` | Instrumentation | Inclinometers, settlement markers, monitoring |
| `drainage_works` | Drainage works | Civil drainage — channels, culverts, stormwater |
| `slope_works` | Slope works | Slope stabilisation, soil nailing, shotcrete |
| `site_formation` | Site formation | Excavation, filling, earthworks, platform formation |
| `roadworks` | Roadworks | Road construction, kerbs, carriageway, footpaths |

## Normalisation notes
- Match is case-insensitive on the label or the key; near-synonyms map to the
  nearest canonical key (e.g. "E&M — electrical" → `electrical`, "drainage field
  test" → `field_testing`, "rotary drilling" → `drilling`, "piezometer
  installation" → `field_installations`).
- A building/fit-out tender splits by **trade**; a civil or ground-investigation
  tender splits by **work section**. Both are first-class — the engine never assumes
  a building tender.
- "drainage" alone is no longer forced onto `mechanical_plumbing`: civil drainage is
  its own work section (`drainage_works`); building drainage arrives inside the
  `mechanical & plumbing` trade.
- A work package with no canonical match is surfaced for review and kept under a
  slugified key — never silently dropped, never treated as a failure.
- The taxonomy is versioned; bump the version when a key is added or renamed.
