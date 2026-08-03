// A sidebar destination whose screen does not exist yet. It opens and says so — the same
// no-padlock rule as an unrun step: a locked item produces a dead end, an honest page does not.

import type { NotDesignedId } from "../nav/routes";
import { WaitingOn } from "../ui";

const COPY: Record<NotDesignedId, { title: string; body: string }> = {
  letters: {
    title: "Letter templates — no screen yet",
    body: "The offer letter and the query letter are drafted from templates on the backend today (docs/client_boq/templates/). Editing them here has not been designed; edit the template files until it is.",
  },
  positions: {
    title: "Standard positions — no screen yet",
    body: "Your house fallback positions (e.g. \"LDs capped at 10%\") live inside the criteria library's acceptable positions for now — edit them under Criteria library. A dedicated screen has not been designed.",
  },
  clients: {
    title: "Clients — no screen yet",
    body: "A tender records its client as a name on the folder card (edit it from the card). A client register with history across tenders has not been designed.",
  },
  audit: {
    title: "Audit log — no screen yet",
    body: "Every verdict, edit and gate already records who and when (that is what the actor header exists for). A screen that reads it back as one timeline has not been designed.",
  },
};

export function NotDesigned({ screen }: { screen: NotDesignedId }) {
  const copy = COPY[screen];
  return <WaitingOn title={copy.title}>{copy.body}</WaitingOn>;
}
