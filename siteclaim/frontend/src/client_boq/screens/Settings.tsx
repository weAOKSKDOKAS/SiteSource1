// The AI models — who reads the documents, and who does everything else.
//
// Two settings rather than one, because reading the tender is a different job from reasoning about
// what was read, and it decides what every later stage is looking at.
//
// The screen's job is honesty about what the knobs do and do not reach: a provider that cannot take
// an image does not read a scanned page, DEMO reads nothing at all, and an empty value means the
// server environment's default rather than "off".

import { useEffect, useState } from "react";
import { api, readFailure } from "../api";
import type { CompanySettings, LLMSettingsResponse, ModeResponse } from "../types";
import { Button, SectionLabel, cx } from "../ui";

/** What each provider is, in one line. Unknown names still render — the list comes from the
 *  server, so a provider added on the backend appears here without a frontend change. */
const PROVIDER_COPY: Record<string, string> = {
  anthropic: "Claude — reads typed and scanned pages",
  openai: "ChatGPT — reads typed and scanned pages",
  deepseek: "the cheap text path — needs DEEPSEEK_API_KEY on the server",
};

function ProviderChoice({
  name,
  value,
  onChange,
  options,
  autoDetail,
  visionCapable,
}: {
  name: string;
  value: string;
  onChange: (value: string) => void;
  options: string[];
  autoDetail: string;
  visionCapable: string[];
}) {
  const choices = [
    { value: "", label: "Auto (the server environment decides)", detail: autoDetail },
    ...options.map((id) => ({
      value: id,
      label: id.charAt(0).toUpperCase() + id.slice(1),
      detail: PROVIDER_COPY[id] ?? "",
    })),
  ];
  return (
    <div className="mt-2 flex flex-col gap-1.5">
      {choices.map((opt) => (
        <label
          key={opt.value}
          className={cx(
            "cb-row flex cursor-pointer items-baseline gap-2.5 rounded-cb-card border px-3 py-2",
            value === opt.value ? "border-cb-brass bg-cb-selected" : "border-cb-border bg-cb-page",
          )}
        >
          <input
            type="radio"
            name={name}
            checked={value === opt.value}
            onChange={() => onChange(opt.value)}
            className="translate-y-[1px] accent-[#BD9A5F]"
          />
          <span className="font-cb-sans text-[12px] font-semibold text-cb-ink-text">
            {opt.label}
          </span>
          <span className="font-cb-sans text-[10px] text-cb-muted">{opt.detail}</span>
          {opt.value && !visionCapable.includes(opt.value) && (
            <span className="ml-auto flex-none font-cb-mono text-[10px] font-semibold tracking-cb-chip text-cb-amber">
              TEXT ONLY
            </span>
          )}
        </label>
      ))}
    </div>
  );
}

export function Settings({
  demoMode,
  onError,
}: {
  demoMode: boolean;
  onError: (msg: string) => void;
}) {
  const [settings, setSettings] = useState<LLMSettingsResponse | null>(null);
  const [provider, setProvider] = useState("");
  const [providerIngest, setProviderIngest] = useState("");
  const [providerDrawing, setProviderDrawing] = useState("");
  const [modelDrawing, setModelDrawing] = useState("");
  const [modelAnthropic, setModelAnthropic] = useState("");
  const [modelDeepseek, setModelDeepseek] = useState("");
  const [modelOpenai, setModelOpenai] = useState("");
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [company, setCompany] = useState<CompanySettings>({
    company_name: "", company_address: "", contact_name: "", contact_number: "",
  });
  const [companySaved, setCompanySaved] = useState(false);

  const load = async () => {
    try {
      const body = await api.settings();
      setSettings(body);
      setProvider(body.provider);
      setProviderIngest(body.provider_ingest);
      setProviderDrawing(body.provider_drawing);
      setModelDrawing(body.model_drawing);
      setModelAnthropic(body.model_anthropic);
      setModelDeepseek(body.model_deepseek);
      setModelOpenai(body.model_openai);
      setCompany(body.company);
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    }
  };
  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const save = async () => {
    setBusy(true);
    setSaved(false);
    try {
      const body = await api.saveSettings({
        provider,
        provider_ingest: providerIngest,
        provider_drawing: providerDrawing,
        model_drawing: modelDrawing,
        model_anthropic: modelAnthropic,
        model_deepseek: modelDeepseek,
        model_openai: modelOpenai,
      });
      setSettings(body);
      setSaved(true);
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const saveCompany = async () => {
    setBusy(true);
    setCompanySaved(false);
    try {
      setSettings(await api.saveCompany(company));
      setCompanySaved(true);
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  if (!settings) {
    return <div className="p-[18px] font-cb-sans text-[11px] text-cb-muted">Loading…</div>;
  }

  const field =
    "w-full rounded-cb-btn border border-cb-border bg-cb-warm px-2.5 py-1.5 font-cb-mono text-[11px] text-cb-ink-text placeholder:font-cb-sans placeholder:text-cb-faint";

  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto max-w-[640px] p-[18px]">
        <h1 className="font-cb-serif text-[20px] font-semibold text-cb-ink-text">Settings</h1>
        <p className="mt-1 font-cb-sans text-[11px] leading-[1.6] text-cb-muted">
          One setting for the whole app. Every reading stage — the split planner, the part
          interpreter, the review, the scope draft, the letters — constructs its client fresh per
          run, so a change here applies from the next run with nothing to restart.
        </p>

        <ModeSwitch onError={onError} />

        {demoMode && (
          <div className="mt-3 rounded-cb-card border border-cb-brass-line bg-cb-brass-tint px-3 py-2 font-cb-sans text-[10.5px] leading-[1.5] text-cb-brass-text">
            The backend is in DEMO — no model is called at all, whatever is set here. The setting
            is stored and takes effect when the backend runs LIVE.
          </div>
        )}

        <section className="mt-5">
          <SectionLabel>Who reads the documents</SectionLabel>
          <p className="mt-1 font-cb-sans text-[10.5px] leading-[1.55] text-cb-muted">
            The ingest pass — how the binder is cut, and what each part says. It is set separately
            because it decides what every later stage is looking at.
          </p>
          <ProviderChoice
            name="provider_ingest"
            value={providerIngest}
            onChange={setProviderIngest}
            options={settings.providers}
            autoDetail={`today that resolves to ${settings.effective.ingest_provider}`}
            visionCapable={settings.effective.vision_capable}
          />
        </section>

        <section className="mt-5">
          <SectionLabel>Who reads the drawing</SectionLabel>
          <p className="mt-1 font-cb-sans text-[10.5px] leading-[1.55] text-cb-muted">
            The station schedule off the borehole details sheet. It runs once or twice a tender and
            the map, the access cards, the rig optimiser and the check against Bill No.2 all rest
            on it — so this is the one call where the strongest model is worth its cost and its
            latency. Blank follows the ingest setting above.
          </p>
          <ProviderChoice
            name="provider_drawing"
            value={providerDrawing}
            onChange={setProviderDrawing}
            options={settings.providers}
            autoDetail={`today that resolves to ${settings.effective.drawing_provider}`}
            visionCapable={settings.effective.vision_capable}
          />
          <label className="mt-2 block">
            <span className="font-cb-sans text-[10.5px] text-cb-muted">
              A model for this read only — leave blank to use that provider&rsquo;s usual one
              ({settings.effective.model_drawing}). Naming one here changes nothing else.
            </span>
            <input
              value={modelDrawing}
              onChange={(e) => setModelDrawing(e.target.value)}
              placeholder={settings.effective.model_drawing}
              className={cx(field, "mt-1")}
            />
          </label>
        </section>

        <section className="mt-5">
          <SectionLabel>Every other stage</SectionLabel>
          <p className="mt-1 font-cb-sans text-[10.5px] leading-[1.55] text-cb-muted">
            The review, the criteria match, the scope draft, the letters.
          </p>
          <ProviderChoice
            name="provider"
            value={provider}
            onChange={setProvider}
            options={settings.providers}
            autoDetail={`today that resolves to ${settings.effective.text_provider}`}
            visionCapable={settings.effective.vision_capable}
          />
        </section>

        <section className="mt-5 grid grid-cols-3 gap-3">
          {(
            [
              ["Anthropic model", modelAnthropic, setModelAnthropic, settings.effective.model_anthropic],
              ["OpenAI model", modelOpenai, setModelOpenai, settings.effective.model_openai],
              ["DeepSeek model", modelDeepseek, setModelDeepseek, settings.effective.model_deepseek],
            ] as const
          ).map(([label, value, set, fallback]) => (
            <div key={label}>
              <SectionLabel>{label}</SectionLabel>
              <input
                value={value}
                onChange={(e) => set(e.target.value)}
                placeholder={fallback}
                className={cx(field, "mt-1.5")}
              />
              <p className="mt-1 font-cb-sans text-[10px] leading-[1.4] text-cb-faint">
                Empty = the server default ({fallback}).
              </p>
            </div>
          ))}
        </section>

        {/* The residual truth no setting can reach. */}
        <div className="mt-4 rounded-cb-card border border-cb-border bg-cb-panel px-3 py-2.5 font-cb-sans text-[10.5px] leading-[1.55] text-cb-body">
          {settings.effective.vision_provider === settings.effective.ingest_provider ? (
            <>
              <span className="font-semibold">
                Scanned pages are read by {settings.effective.ingest_provider} too.
              </span>{" "}
              One provider reads the whole binder, typed or scanned.
            </>
          ) : (
            <>
              <span className="font-semibold">
                Scanned pages go to {settings.effective.vision_provider}, not to{" "}
                {settings.effective.ingest_provider}.
              </span>{" "}
              {settings.effective.ingest_provider}'s API rejects image input, so a scanned page
              would otherwise be read as a blank one. That fallback is a fact about the provider,
              not a preference — the ones that can read a page are{" "}
              {settings.effective.vision_capable.join(" and ")}.
            </>
          )}
        </div>

        <div className="mt-4 flex items-center gap-3">
          <Button variant="brass" onClick={() => void save()} disabled={busy}>
            Save
          </Button>
          {saved && <span className="font-cb-mono text-[10px] font-semibold text-cb-ok-dark">SAVED — APPLIES FROM THE NEXT RUN</span>}
          {settings.rows.length > 0 && settings.rows[0].updated_by && (
            <span className="ml-auto font-cb-mono text-[10px] text-cb-faint" title={settings.rows[0].updated_at ?? undefined}>
              last changed · {settings.rows[0].updated_by}
            </span>
          )}
        </div>

        {/* --- the letterhead ------------------------------------------------
            Here rather than on the Offer tab because it is the same on every tender. What is NOT
            here: the client's name and the project, which come from each tender's own desk card,
            and the date, which is stamped when the letter is produced. */}
        <section className="mt-8 border-t border-cb-border pt-6">
          <h2 className="font-cb-serif text-[16px] font-semibold text-cb-ink-text">
            Company details
          </h2>
          <p className="mt-1 font-cb-sans text-[11px] leading-[1.6] text-cb-muted">
            The letterhead every offer letter goes out on. The client's name and the project come
            from the tender itself, so they are not repeated here. Anything left blank stays blank
            on the letter — a visible gap, rather than a company name nobody chose.
          </p>
          <div className="mt-3 grid grid-cols-2 gap-2.5">
            {([
              ["company_name", "Company name", "Your firm, as it should appear"],
              ["contact_name", "Contact", "Who signs it"],
              ["company_address", "Address", "One line"],
              ["contact_number", "Telephone", "+852 …"],
            ] as const).map(([key, label, placeholder]) => (
              <label key={key} className="flex flex-col gap-1">
                <SectionLabel>{label}</SectionLabel>
                <input
                  value={company[key]}
                  placeholder={placeholder}
                  onChange={(e) => setCompany({ ...company, [key]: e.target.value })}
                  className={field}
                />
              </label>
            ))}
          </div>
          <div className="mt-3 flex items-center gap-3">
            <Button variant="outline" onClick={() => void saveCompany()} disabled={busy}>
              Save company details
            </Button>
            {companySaved && (
              <span className="font-cb-mono text-[10px] font-semibold text-cb-ok-dark">SAVED</span>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Demo or live — the switch that decides whether any of this is real
//
// Deliberately not a toggle. Going live means real API spend, real outbound email and real
// tenders, so it costs a typed word and refuses outright with no key configured. Going back to
// demo is one click: offline is always safe, and a switch that is hard to reach in the safe
// direction is a switch people route around.
//
// The mode is a PROCESS setting, not a stored one. `client_boq/store.py` picks which database to
// open by asking what mode it is in, so a row in `client_boq_settings` would be circular — you
// would have to know the mode to know which database to read the mode from. The panel says the
// consequence out loud rather than letting somebody discover it after a restart.
// ---------------------------------------------------------------------------
function ModeSwitch({ onError }: { onError: (msg: string) => void }) {
  const [mode, setMode] = useState<ModeResponse | null>(null);
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api
      .mode()
      .then(setMode)
      .catch((e) => onError(readFailure(e)));
  }, [onError]);

  const switchTo = async (demo: boolean | null) => {
    setBusy(true);
    try {
      const next = await api.setMode(demo, demo === false ? confirm : "");
      setMode(next);
      setConfirm("");
      // A HARD RELOAD, not a re-render. The two modes read different DATABASE FILES, and
      // `set_id` is derived from the tender's name — so a demo tender and a live tender sharing a
      // name share an id. Every screen holding a tender is now holding one from the other file.
      window.location.reload();
    } catch (e) {
      onError(readFailure(e));
    } finally {
      setBusy(false);
    }
  };

  if (!mode) return null;

  return (
    <section
      className={cx(
        "mt-4 rounded-cb-card border px-3 py-3",
        mode.demo ? "border-cb-brass-line bg-cb-brass-tint" : "border-cb-navy-line bg-cb-panel",
      )}
    >
      <SectionLabel>{mode.demo ? "DEMO — nothing here is real" : "LIVE — this is real"}</SectionLabel>
      <p
        className={cx(
          "mt-1 font-cb-sans text-[10.5px] leading-[1.55]",
          mode.demo ? "text-cb-brass-text" : "text-cb-body",
        )}
      >
        {mode.demo
          ? "No model is called, no email can be sent, no token is spent, and these tenders are in a separate database from your real ones."
          : "Every reading stage calls a real model and spends real credit. Enquiries go to real addresses. Tenders here are your real tenders."}{" "}
        {mode.source === "operator"
          ? `Switched here, not deployed this way${
              mode.reverts_on_restart
                ? ` — a server restart returns it to ${mode.env_default ? "DEMO" : "LIVE"}.`
                : "."
            }`
          : "This is how the server was started (the DEMO_MODE variable)."}
      </p>

      {mode.demo ? (
        <div className="mt-2.5">
          {!mode.live_ready ? (
            // SAID HERE, not at the first model call — which is minutes into a job and looks like
            // the tender failing rather than the configuration being absent.
            <p className="font-cb-sans text-[10.5px] leading-[1.55] text-cb-bad-dark">
              LIVE is not available: {mode.blocked_because}
            </p>
          ) : (
            <div className="flex flex-wrap items-center gap-2">
              <input
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                placeholder="type LIVE"
                aria-label="Type LIVE to confirm going live"
                className="w-[110px] rounded-cb-btn border border-cb-border bg-cb-warm px-2 py-1 font-cb-mono text-[11px] uppercase text-cb-ink-text placeholder:font-cb-sans placeholder:normal-case placeholder:text-cb-faint"
              />
              <Button
                variant="outline"
                disabled={busy || confirm.trim().toUpperCase() !== "LIVE"}
                onClick={() => void switchTo(false)}
              >
                Go live
              </Button>
              <span className="font-cb-sans text-[10px] leading-[1.5] text-cb-muted">
                Calls {mode.providers_needed.join(" and ")}. Spends real credit.
              </span>
            </div>
          )}
        </div>
      ) : (
        <div className="mt-2.5 flex flex-wrap items-center gap-2">
          <Button variant="outline" disabled={busy} onClick={() => void switchTo(true)}>
            Switch to demo
          </Button>
          <span className="font-cb-sans text-[10px] leading-[1.5] text-cb-muted">
            Offline immediately. Your live tenders stay where they are — demo reads a different
            database.
          </span>
        </div>
      )}

      {mode.source === "operator" && (
        <button
          type="button"
          disabled={busy}
          onClick={() => void switchTo(null)}
          className="mt-2 font-cb-sans text-[10px] text-cb-muted underline underline-offset-2"
        >
          Use the server's own setting ({mode.env_default ? "DEMO" : "LIVE"}) instead
        </button>
      )}
    </section>
  );
}
