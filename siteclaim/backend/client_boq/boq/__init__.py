"""BOQ — the client's bill of quantities: read it, diff it, carry rates across it, price it.

Bucket: **entirely deterministic**. There is not one model call in this package, by design. A price,
a quantity and a difference between two revisions are all things arithmetic can settle, and settling
them in code is what makes the whole package provable offline.

The design is measured from a real tender (CEDD ND/2025/04) rather than derived from principle —
see ``siteclaim/docs/client_boq/prd_boq_costing.md`` for the evidence behind every rule here. Three
facts from that package shape everything:

1. **Identity is the item reference, never the row.** Across two real addenda, 0 items were
   renumbered and 0 deleted, while 35 moved rows.
2. **The workbook does not mark what changed.** Every one of 1,239 non-empty cells in Rev 2 has no
   fill; there are no comments, no tracked changes, and Rev 2 carries no addendum footer at all. A
   diff is the only honest way to see a quantity go from 1,128 to 2,451.
3. **An item's meaning is its heading chain**, not its own cell (General Preambles 2), so a change
   to a caption is a change to every item beneath it.
"""

from __future__ import annotations
