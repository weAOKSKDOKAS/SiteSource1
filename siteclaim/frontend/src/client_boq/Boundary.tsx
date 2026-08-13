// The white screen, ended.
//
// React unmounts the ENTIRE tree when a render throws and nothing catches it — so one bad cell in
// one tile took the whole application to a blank page, with the real error visible only in a
// console nobody had open. On a tender that is indistinguishable from the app losing your work.
//
// This is the app's only error boundary and it is deliberately placed twice: once around the tab
// body, so a crash costs you that screen and not the shell (the step strip, the rail and the
// other tabs stay live and navigable), and once around the whole app as a backstop.
//
// It says what broke, in the app's own voice, and offers the two ways out that actually work:
// go back to the desk, or reload. It shows the message and the component stack because the
// person reading it is the person who can send it to whoever fixes it — a boundary that hides
// the error just moves the blank page one level down.

import { Component } from "react";
import type { ErrorInfo, ReactNode } from "react";

export class Boundary extends Component<
  { children: ReactNode; label: string; onReset?: () => void },
  { error: Error | null; stack: string }
> {
  state = { error: null as Error | null, stack: "" };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // Kept for the operator to copy, not just for a console they do not have open.
    this.setState({ error, stack: info.componentStack ?? "" });
    // Still logged: a developer with the console open should not have to read the page.
    console.error(`[${this.props.label}]`, error, info.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;
    const { error, stack } = this.state;
    return (
      <div className="min-h-0 flex-1 overflow-y-auto p-6">
        <div className="mx-auto max-w-[720px] rounded-cb-card border border-cb-bad bg-cb-bad-tint p-4">
          <div className="font-cb-mono text-[8px] font-semibold tracking-cb-chip text-cb-bad-dark">
            THIS SCREEN STOPPED — {this.props.label.toUpperCase()}
          </div>
          <p className="mt-1.5 font-cb-serif text-[13px] leading-[1.6] text-cb-ink-text">
            Something on this screen threw an error while drawing itself. Nothing you have saved is
            affected — this is the screen failing to render, not the tender changing. The rest of
            the app is still working, so you can move to another step and come back.
          </p>
          <p className="mt-2 font-cb-mono text-[10px] leading-[1.5] text-cb-bad-dark">
            {error.name}: {error.message}
          </p>
          {stack && (
            <details className="mt-2">
              <summary className="cursor-pointer font-cb-sans text-[10px] text-cb-muted">
                where it happened (send this with a bug report)
              </summary>
              <pre className="mt-1 max-h-[220px] overflow-auto whitespace-pre-wrap font-cb-mono text-[9px] leading-[1.45] text-cb-muted">
                {stack.trim()}
              </pre>
            </details>
          )}
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => {
                this.setState({ error: null, stack: "" });
                this.props.onReset?.();
              }}
              className="cb-press rounded-cb-btn bg-cb-ink px-3 py-1.5 font-cb-sans text-[11px] font-semibold text-white"
            >
              Try this screen again
            </button>
            <button
              type="button"
              onClick={() => {
                window.location.hash = "#/tender";
                this.setState({ error: null, stack: "" });
              }}
              className="cb-press rounded-cb-btn border border-cb-border bg-cb-page px-3 py-1.5 font-cb-sans text-[11px] font-medium text-cb-body"
            >
              Back to the desk
            </button>
            <button
              type="button"
              onClick={() => window.location.reload()}
              className="cb-press font-cb-sans text-[10.5px] text-cb-muted underline underline-offset-2"
            >
              reload the page
            </button>
          </div>
        </div>
      </div>
    );
  }
}
