"""RFI — the conversation with the client, between reviewing the tender and pricing it.

A tender review produces questions as well as positions: wording that is ambiguous, a scope gap,
a risk allocation nobody will accept as drafted. Those go to the issuer as numbered queries before
the query cut-off, and the answers come back as either an addendum (which amends the contract) or
a clarification letter (which expressly does not).

Two rules shape the design, both taken from the reference package rather than invented:

* **Open questions do not block pricing.** Tender Clarification No. 1 of ND/2025/04 carried 17
  questions answered in stages, and the submission deadline never moved for any of them. A queried
  register line stays open and the estimate still runs; the forcing function is the freeze gate,
  where every unanswered query must become an answer or a stated priced assumption.
* **Questions are batched, not dripped.** Real queries go out as one numbered letter per round —
  TC1 and TC2 in the reference package — so the client can answer them together.
"""
