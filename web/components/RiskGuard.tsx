"use client";

/**
 * The ban-risk pop-up.
 *
 * `useRiskGuard().guarded(call)` runs `call(false)`. When the server refuses
 * with `risk_confirmation_required`, it shows the risks and, only if the person
 * explicitly accepts, runs `call(true)`. Declining returns null and nothing is
 * saved. `confirm(risks)` shows the same dialog for a purely client-side check
 * (e.g. the moment someone clicks "ASAP").
 *
 * The safe choice is the primary button and the default; accepting is spelled
 * out so it is never an accidental click.
 */

import { createContext, useCallback, useContext, useRef, useState } from "react";
import { risksOf, type Risk } from "@/lib/api";

type Guard = {
  confirm: (risks: Risk[]) => Promise<boolean>;
  guarded: <T>(call: (acknowledgeRisk: boolean) => Promise<T>) => Promise<T | null>;
};

const RiskGuardContext = createContext<Guard | null>(null);

export function useRiskGuard(): Guard {
  const guard = useContext(RiskGuardContext);
  if (!guard) throw new Error("useRiskGuard must be used inside <RiskGuardProvider>");
  return guard;
}

export function RiskGuardProvider({ children }: { children: React.ReactNode }) {
  const [risks, setRisks] = useState<Risk[] | null>(null);
  const [understood, setUnderstood] = useState(false);
  const resolver = useRef<((accepted: boolean) => void) | null>(null);

  const confirm = useCallback((next: Risk[]) => {
    if (next.length === 0) return Promise.resolve(true);
    setUnderstood(false);
    setRisks(next);
    return new Promise<boolean>((resolve) => {
      resolver.current = resolve;
    });
  }, []);

  const guarded = useCallback(
    async <T,>(call: (acknowledgeRisk: boolean) => Promise<T>): Promise<T | null> => {
      try {
        return await call(false);
      } catch (err) {
        const found = risksOf(err);
        if (found === null) throw err;
        return (await confirm(found)) ? await call(true) : null;
      }
    },
    [confirm],
  );

  function close(accepted: boolean) {
    resolver.current?.(accepted);
    resolver.current = null;
    setRisks(null);
  }

  return (
    <RiskGuardContext.Provider value={{ confirm, guarded }}>
      {children}
      {risks && (
        <div
          className="fixed inset-0 z-[70] flex items-center justify-center bg-slate-900/60 p-4"
          role="alertdialog"
          aria-modal="true"
          aria-labelledby="risk-title"
        >
          <div className="w-full max-w-lg overflow-hidden rounded-xl bg-white shadow-2xl">
            <div className="flex items-start gap-3 border-b border-red-100 bg-red-50 px-5 py-4">
              <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-red-600 text-base font-bold text-white">
                !
              </span>
              <div>
                <h2 id="risk-title" className="text-base font-bold text-red-900">
                  This can get your LinkedIn account banned
                </h2>
                <p className="mt-0.5 text-sm text-red-800">
                  LinkedIn restricts accounts that behave like this. We recommend keeping the safe
                  setting.
                </p>
              </div>
            </div>

            <ul className="max-h-[45vh] space-y-3 overflow-y-auto px-5 py-4">
              {risks.map((risk) => (
                <li key={risk.key} className="rounded-lg border border-slate-200 p-3">
                  <p className="text-sm font-semibold text-slate-900">{risk.title}</p>
                  <p className="mt-0.5 text-sm text-slate-600">{risk.detail}</p>
                </li>
              ))}
            </ul>

            <div className="border-t border-slate-200 px-5 py-4">
              <label className="mb-4 flex items-start gap-2.5 text-sm text-slate-700">
                <input
                  type="checkbox"
                  className="mt-0.5 h-4 w-4 rounded border-slate-300"
                  checked={understood}
                  onChange={(e) => setUnderstood(e.target.checked)}
                />
                <span>
                  I understand this can get the account restricted. Proceeding adds a safety
                  warning to it; at 3 warnings it is paused automatically.
                </span>
              </label>
              <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
                <button
                  type="button"
                  className="btn-ghost text-red-700 disabled:opacity-40"
                  disabled={!understood}
                  onClick={() => close(true)}
                >
                  Proceed anyway
                </button>
                <button type="button" className="btn-primary" autoFocus onClick={() => close(false)}>
                  Keep it safe
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </RiskGuardContext.Provider>
  );
}
