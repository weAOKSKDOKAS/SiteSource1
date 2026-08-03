// The AI model — one app-wide setting, applied to every client_boq stage from its next run.
// The screen's job is honesty about what the knob does and does not reach: scanned pages are
// always read by Anthropic vision regardless of the text provider, DEMO reads nothing at all,
// and an empty value means the server environment's default, not "off".

import { useEffect, useState } from "react";
import { api } from "../api";
import type { LLMSettingsResponse } from "../types";
import { Button, SectionLabel, cx } from "../ui";

export function Settings({
  demoMode,
  onError,
}: {
  demoMode: boolean;
  onError: (msg: string) => void;
}) {
  const [settings, setSettings] = useState<LLMSettingsResponse | null>(null);
  const [provider, setProvider] = useState("");
  const [modelAnthropic, setModelAnthropic] = useState("");
  const [modelDeepseek, setModelDeepseek] = useState("");
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);

  const load = async () => {
    try {
      const body = await api.settings();
      setSettings(body);
      setProvider(body.provider);
      setModelAnthropic(body.model_anthropic);
      setModelDeepseek(body.model_deepseek);
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
        model_anthropic: modelAnthropic,
        model_deepseek: modelDeepseek,
      });
      setSettings(body);
      setSaved(true);
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
        <h1 className="font-cb-serif text-[20px] font-semibold text-cb-ink-text">AI model</h1>
        <p className="mt-1 font-cb-sans text-[11px] leading-[1.6] text-cb-muted">
          One setting for the whole app. Every reading stage — the split planner, the part
          interpreter, the review, the scope draft, the letters — constructs its client fresh per
          run, so a change here applies from the next run with nothing to restart.
        </p>

        {demoMode && (
          <div className="mt-3 rounded-cb-card border border-cb-brass-line bg-cb-brass-tint px-3 py-2 font-cb-sans text-[10.5px] leading-[1.5] text-cb-brass-text">
            The backend is in DEMO — no model is called at all, whatever is set here. The setting
            is stored and takes effect when the backend runs LIVE.
          </div>
        )}

        <section className="mt-5">
          <SectionLabel>Text provider</SectionLabel>
          <div className="mt-2 flex flex-col gap-1.5">
            {[
              { value: "", label: "Auto (the server environment decides)", detail: `today that resolves to ${settings.effective.text_provider}` },
              { value: "anthropic", label: "Anthropic", detail: "Claude for every text stage" },
              { value: "deepseek", label: "DeepSeek", detail: "the cheap text path — needs DEEPSEEK_API_KEY on the server" },
            ].map((opt) => (
              <label
                key={opt.value}
                className={cx(
                  "cb-row flex cursor-pointer items-baseline gap-2.5 rounded-cb-card border px-3 py-2",
                  provider === opt.value ? "border-cb-brass bg-cb-selected" : "border-cb-border bg-cb-page",
                )}
              >
                <input
                  type="radio"
                  name="provider"
                  checked={provider === opt.value}
                  onChange={() => setProvider(opt.value)}
                  className="translate-y-[1px] accent-[#BD9A5F]"
                />
                <span className="font-cb-sans text-[12px] font-semibold text-cb-ink-text">{opt.label}</span>
                <span className="font-cb-sans text-[10px] text-cb-muted">{opt.detail}</span>
              </label>
            ))}
          </div>
        </section>

        <section className="mt-5 grid grid-cols-2 gap-3">
          <div>
            <SectionLabel>Anthropic model</SectionLabel>
            <input
              value={modelAnthropic}
              onChange={(e) => setModelAnthropic(e.target.value)}
              placeholder={settings.effective.model_anthropic}
              className={cx(field, "mt-1.5")}
            />
            <p className="mt-1 font-cb-sans text-[9.5px] leading-[1.4] text-cb-faint">
              Empty = the server default ({settings.effective.model_anthropic}).
            </p>
          </div>
          <div>
            <SectionLabel>DeepSeek model</SectionLabel>
            <input
              value={modelDeepseek}
              onChange={(e) => setModelDeepseek(e.target.value)}
              placeholder={settings.effective.model_deepseek}
              className={cx(field, "mt-1.5")}
            />
            <p className="mt-1 font-cb-sans text-[9.5px] leading-[1.4] text-cb-faint">
              Empty = the server default ({settings.effective.model_deepseek}).
            </p>
          </div>
        </section>

        {/* The residual truth the knob cannot reach. */}
        <div className="mt-4 rounded-cb-card border border-cb-border bg-cb-panel px-3 py-2.5 font-cb-sans text-[10.5px] leading-[1.55] text-cb-body">
          <span className="font-semibold">Scanned pages are always read by Anthropic vision,</span>{" "}
          whatever the text provider — DeepSeek's API rejects image input. A tender full of
          scanned drawings will use Anthropic for those pages even with DeepSeek selected above.
        </div>

        <div className="mt-4 flex items-center gap-3">
          <Button variant="brass" onClick={() => void save()} disabled={busy}>
            Save
          </Button>
          {saved && <span className="font-cb-mono text-[9px] font-semibold text-cb-ok-dark">SAVED — APPLIES FROM THE NEXT RUN</span>}
          {settings.rows.length > 0 && settings.rows[0].updated_by && (
            <span className="ml-auto font-cb-mono text-[8.5px] text-cb-faint" title={settings.rows[0].updated_at ?? undefined}>
              last changed · {settings.rows[0].updated_by}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
