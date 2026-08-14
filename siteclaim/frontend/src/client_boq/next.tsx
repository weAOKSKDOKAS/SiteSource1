// The one line every screen answers "what now?" with.
//
// THE RULE THIS IMPLEMENTS, from the walkthrough (F5): the strip tells you where you are; nothing
// told you what to do. This line is the estimator's DEFAULT PATH — the first incomplete step of
// the tender, as a sentence, with the way there attached. It is advice, never enforcement:
//
//  * It is computed from the SAME data the step chips read, so it cannot disagree with them —
//    two surfaces deriving one state was this app's repeated defect, and this line must not
//    add a third voice.
//  * The button only NAVIGATES. Every consequential click — approve, close, confirm, submit —
//    stays on the screen that owns it, behind its own stated consequence. Easier never means
//    automatic.
//  * It never turns the app into a wizard: the estimator can go anywhere; this is the obvious
//    default for the moment they look up and ask "what now?".

import type { SetData } from "./App";
import type { TabId } from "./chrome";

export interface NextAction {
  /** The sentence after "Next:" — plain, one clause, an estimator's words. */
  sentence: string;
  /** Where the action lives. Null when nothing is waiting on the person. */
  tab: TabId | null;
  /** The button's label — "Open Register". Null renders no button (already there, or terminal). */
  go: string | null;
}

/** The first incomplete step of the tender's default path. Deliberately a plain chain of ifs in
 *  pipeline order — the same order the strip prints — so a reader can check it against the strip
 *  top to bottom. */
/** What to say when the read this branch depends on did not come back.
 *
 * A `null` means two things — the step has not run, or the read failed — and every branch below
 * reads one. Saying "run the review" about a register that could not be READ invites an expensive
 * re-run of work that may already be done; saying "decide bid or no-bid" invites re-deciding a
 * decision already taken. So a branch whose evidence is missing answers with the honest thing and
 * offers no button: there is nowhere useful to send somebody until the server answers.
 */
function unknown(data: SetData, key: string, what: string): NextAction | null {
  const failure = data.failures[key];
  if (!failure) return null;
  return {
    sentence: `${what} could not be read (${failure}), so what is waiting on you is not known. ` +
              `Reload before acting — this is a gap in what was read, not a step that has not run.`,
    tab: null, go: null,
  };
}

export function nextFor(data: SetData): NextAction {
  const hasParts = Boolean(data.parts?.count);

  if (!data.gates.manifest) {
    return {
      sentence: "check the proposed split against the binder, then approve the manifest.",
      tab: "documents", go: "Open Documents",
    };
  }
  const parts = unknown(data, "parts", "this tender's parts");
  if (parts) return parts;
  if (!hasParts) {
    return {
      sentence: "the manifest is approved — split the binder into parts.",
      tab: "documents", go: "Open Documents",
    };
  }
  const register = unknown(data, "register", "the review register");
  if (register) return register;
  if (!data.register) {
    return {
      sentence: "run the review — it reads each part against the criteria library.",
      tab: "register", go: "Open Register",
    };
  }
  if (!data.gates.review) {
    return {
      sentence: "give the findings their verdicts, then close the register.",
      tab: "register", go: "Open Register",
    };
  }
  const bid = unknown(data, "bid", "the bid decision");
  if (bid) return bid;
  if (!data.bidVerdict) {
    return {
      sentence: "decide bid or no-bid — the first real decision, now the terms are read.",
      tab: "bid", go: "Open Bid",
    };
  }
  if (data.bidVerdict === "no_bid") {
    return {
      sentence: "this tender is recorded NO BID. Nothing more is waiting; re-decide on the Bid " +
                "tab if that changes.",
      tab: null, go: null,
    };
  }
  const scope = unknown(data, "scope", "the scope");
  if (scope) return scope;
  if (!data.scope) {
    return {
      sentence: "draft the scope — it reads the confirmed positions back out of the register.",
      tab: "scope", go: "Open Scope",
    };
  }
  if (!data.gates.scope) {
    return {
      sentence: "approve the scope to unlock pricing.",
      tab: "scope", go: "Open Scope",
    };
  }
  const route = unknown(data, "decisions", "the routing decisions")
    ?? unknown(data, "proposal", "the routing proposal");
  if (route) return route;
  if (!data.route.hasDecisions) {
    return {
      sentence: data.route.hasProposal
        ? "decide who builds each package — the routing is proposed, the decision is yours."
        : "propose the routing — who builds each package is the next decision.",
      tab: "route", go: "Open Route",
    };
  }
  // The take-off, before the price rests on it. This line never mentioned Site at all, and would
  // route an estimator straight past it to "build the price" — past the only independent check
  // there is on the client's own soil and rock metres, and past the only screen where a hole is
  // given its class. Advice, like every other line here: Site has no gate, and this adds none.
  const site = unknown(data, "site", "the take-off");
  if (site) return site;
  if (!data.site?.stations.length) {
    return {
      sentence: "read in the take-off — the drawing's soil and rock metres are the only check " +
                "there is on the client's quantities.",
      tab: "site", go: "Open Site",
    };
  }
  // EITHER engine counts as priced. `hasEstimate` reads `client_boq_estimates`, which only the
  // retired resource-schedule engine writes — so a tender priced the normal way (import the
  // client's bill, settle the rates) stuck on this branch forever. And because the branch names
  // "price" while you are standing on Price, the `here` check below suppressed the button: the
  // line degraded to "You are on the right tab" with no way onward, Offer's chip read WAITS ON THE
  // PRICE, and Offer's only button pointed back at Price. Two screens pointing at each other.
  if (!data.hasEstimate && !data.hasBill) {
    return {
      sentence: "build the price. Sourcing runs beside it for the sublet packages.",
      tab: "price", go: "Open Price",
    };
  }
  // The offer letter is assembled by the retired engine and cannot yet read a costing bill. Say
  // that, rather than sending the estimator to a screen whose only button sends them back.
  if (!data.hasEstimate && data.hasBill) {
    return {
      sentence: "the bill is priced. The offer letter is still assembled by the earlier estimate " +
                "engine and cannot read a costing bill yet — download the workbook from Price, " +
                "or run the estimate if this tender needs a letter.",
      tab: null, go: null,
    };
  }
  // A FAILED READ IS NOT A TENDER AWAITING APPROVAL. `data.submission` is null for both, and
  // reading the second as the first would send an estimator to approve something that may already
  // be approved — or, worse, submitted.
  const submission = unknown(data, "submission", "this tender's approval state");
  if (submission) return submission;
  if (data.submission?.approval?.verdict !== "approve") {
    return {
      sentence: "the price is built — read the offer and approve it.",
      tab: "offer", go: "Open Offer",
    };
  }
  if (!data.submission?.submission) {
    return {
      sentence: "approved — record the submission once the tender has gone out.",
      tab: "offer", go: "Open Offer",
    };
  }
  const closeout = unknown(data, "closeout", "the closeout record");
  if (closeout) return closeout;
  const outcome = data.closeout?.outcome;
  if (!outcome || outcome.status === "submitted") {
    return {
      sentence: "submitted — record the outcome when the client answers.",
      tab: "closeout", go: "Open Closeout",
    };
  }
  return {
    sentence: `closed out as ${outcome.status.toUpperCase()}. Nothing is waiting on you.`,
    tab: null, go: null,
  };
}

/** The line itself: under the step strip, above the tab body, on every tender screen. */
export function NextLine({
  data,
  current,
  onGo,
}: {
  data: SetData;
  current: TabId;
  onGo: (tab: TabId) => void;
}) {
  const next = nextFor(data);
  const here = next.tab === current;
  return (
    <div
      aria-label="Next action"
      className="flex flex-none items-center gap-2.5 border-b border-cb-border bg-cb-surface px-[18px] py-[7px]"
    >
      <span className="flex-none font-cb-mono text-[10px] font-semibold tracking-cb-label text-cb-faint">
        NEXT
      </span>
      <span className="min-w-0 truncate font-cb-sans text-[11.5px] text-cb-body" title={next.sentence}>
        {next.sentence}
        {here && next.tab && (
          <span className="text-cb-muted"> You are on the right tab.</span>
        )}
      </span>
      {next.tab && next.go && !here && (
        <button
          type="button"
          onClick={() => onGo(next.tab as TabId)}
          className="cb-press ml-auto flex-none rounded-cb-btn border border-cb-brass-line bg-cb-brass-tint px-2.5 py-[3px] font-cb-sans text-[10.5px] font-semibold text-cb-brass-text"
        >
          {next.go} →
        </button>
      )}
    </div>
  );
}
