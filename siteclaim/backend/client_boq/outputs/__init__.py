"""OUTPUTS — the documents that leave the building.

Deterministic generators over decisions a human has already made at the gates. No new judgement
happens here: the Departure Schedule is the approved register in submittable form, and the Letter
of Qualifications is the assumptions register in submittable form.

**Every generator has two audiences, and the default is INTERNAL.** Both reference tenders state
that qualifying a tender may cause it to be disqualified:

    "Any qualification of the tender may cause the tender to be disqualified."
        -- ND/2025/04, General Conditions of Tender GCT 4, page 6
    "Any qualification of tender or of the tender documents may cause the tender to be
     disqualified."
        -- CIC (325), Conditions of Tender 4.26, page 8

So these are working documents first: your negotiating position, what to raise, what you assumed.
A submission version is produced only when explicitly asked for, and it carries the tender's own
warning at the top. The sanctioned route for a problem clause is an RFI before the query cut-off,
where an answer amends the contract for every tenderer; carrying it to submission as a
qualification is the thing the tender penalises.
"""

AUDIENCE_INTERNAL = "internal"
AUDIENCE_SUBMISSION = "submission"
AUDIENCES = (AUDIENCE_INTERNAL, AUDIENCE_SUBMISSION)
