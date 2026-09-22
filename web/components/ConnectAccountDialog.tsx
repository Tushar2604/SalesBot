"use client";

/**
 * Connect a LinkedIn account.
 *
 * Credentials is the default on purpose: it establishes a brand-new session,
 * separate from whatever the member is doing in their own browser. Pasting a
 * `li_at` cookie instead hands over the session your everyday browser is
 * actively using — LinkedIn then sees that one session suddenly making
 * requests from a server and reasonably treats it as compromised, which is
 * what signs the member out of their own browser. Cookie import is kept as a
 * fallback for headless environments where a fresh login isn't practical.
 */

import { useState } from "react";
import { ApiError, linkedinApi, type ProxyRecord } from "@/lib/api";
import { IconChevronDown, IconChevronLeft, IconClose, IconLinkedIn } from "@/components/app/icons";
import { RemoteBrowserPanel } from "@/components/RemoteBrowserPanel";

type Mode = "cookie" | "credentials";

const COMMON_TIMEZONES = [
  "UTC",
  "Asia/Kolkata",
  "America/New_York",
  "America/Chicago",
  "America/Los_Angeles",
  "Europe/London",
  "Europe/Berlin",
  "Europe/Amsterdam",
  "Australia/Sydney",
  "Asia/Singapore",
  "Asia/Dubai",
];

function guessTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}

export function ConnectAccountDialog({
  workspaceId,
  proxies,
  onClose,
  onConnected,
}: {
  workspaceId: string;
  proxies: ProxyRecord[];
  onClose: () => void;
  onConnected: () => void;
}) {
  const [mode, setMode] = useState<Mode>("credentials");
  const [label, setLabel] = useState("");
  const [liAt, setLiAt] = useState("");
  const [jsessionid, setJsessionid] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [timezone, setTimezone] = useState(guessTimezone());
  const [proxyId, setProxyId] = useState<string>("");
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [remoteBrowserOpen, setRemoteBrowserOpen] = useState(false);

  const available = proxies.filter((p) => p.assigned_account_id === null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      if (mode === "cookie") {
        await linkedinApi.connectWithCookie(workspaceId, {
          label,
          li_at: liAt,
          jsessionid: jsessionid || undefined,
          timezone,
          proxy_id: proxyId || null,
        });
        onConnected();
      } else {
        setRemoteBrowserOpen(true);
        return;
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not start the connection");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-slate-900/40" onClick={onClose}>
      <div
        className="flex h-full w-full max-w-xl flex-col overflow-y-auto bg-white shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-4 border-b border-slate-200 px-6 py-5">
          <button onClick={onClose} aria-label="Close" className="text-slate-400 hover:text-ink-950">
            <IconClose className="h-5 w-5" />
          </button>
          <h2 className="font-display text-lg font-extrabold tracking-tight text-ink-950">Add Account</h2>
        </div>

        <div className="flex items-center gap-6 border-b border-slate-200 px-6 py-4 text-[13px] font-semibold">
          <span className="flex items-center gap-2 text-slate-400">
            <span className="h-2 w-2 rounded-full bg-slate-300" />
            Select Account Type
          </span>
          <span className="flex items-center gap-2 text-brand-600">
            <span className="h-2 w-2 rounded-full bg-brand-600" />
            Account Details
          </span>
        </div>

        <div className="flex-1 px-6 py-6">
          <button
            type="button"
            onClick={onClose}
            className="mb-5 flex items-center gap-1 text-[13.5px] font-semibold text-slate-500 hover:text-ink-950"
          >
            <IconChevronLeft className="h-4 w-4" />
            Back
          </button>

          <p className="mb-5 text-sm text-slate-500">
            The sign-in happens on a worker, through this account&apos;s assigned connection, so
            the session is created on the IP it will keep using.
          </p>

          <div className="mb-5 flex gap-2 rounded-lg border border-slate-200 bg-slate-50 p-1">
            <button
              type="button"
              onClick={() => setMode("credentials")}
              className={`flex-1 rounded-md px-3 py-2 text-[13px] font-semibold transition-colors ${
                mode === "credentials" ? "bg-white text-ink-950 shadow-sm" : "text-slate-500 hover:text-ink-950"
              }`}
            >
              Email &amp; password{" "}
              <span className="text-[10.5px] font-bold text-emerald-600">Recommended</span>
            </button>
            <button
              type="button"
              onClick={() => setMode("cookie")}
              className={`flex-1 rounded-md px-3 py-2 text-[13px] font-semibold transition-colors ${
                mode === "cookie" ? "bg-white text-ink-950 shadow-sm" : "text-slate-500 hover:text-ink-950"
              }`}
            >
              Session cookie
            </button>
          </div>

          {mode === "credentials" && (
            <p className="mb-5 rounded-lg border border-state-ok/30 bg-state-ok/5 p-3 text-xs text-slate-600">
              This starts a fresh LinkedIn session, separate from whatever you&apos;re signed into
              in your own browser — it never touches your everyday session, so using it doesn&apos;t
              put your normal LinkedIn usage at risk.
            </p>
          )}
          {mode === "cookie" && (
            <p className="mb-5 rounded-lg border border-state-warn/30 bg-state-warn/5 p-3 text-xs text-state-warn">
              This reuses the session your browser is actively using right now. Only use this for
              an account you don&apos;t mind logging out of everywhere else, or on a headless
              server where a fresh login isn&apos;t practical — never for your everyday account.
            </p>
          )}

          <form onSubmit={submit} className="space-y-5">
            {mode === "cookie" ? (
              <>
                <div>
                  <label className="label" htmlFor="li_at">
                    LinkedIn session cookie (li_at)
                  </label>
                  <textarea
                    id="li_at"
                    className="input h-20 font-mono text-xs"
                    value={liAt}
                    onChange={(e) => setLiAt(e.target.value)}
                    placeholder="AQEDAT…"
                    required
                  />
                </div>
                <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs text-slate-500">
                  <p className="mb-1.5 font-semibold text-slate-600">Where to find this</p>
                  <ol className="list-decimal space-y-1 pl-4">
                    <li>Open linkedin.com while signed in.</li>
                    <li>
                      Open DevTools (F12) → Application → Cookies →{" "}
                      <code>https://www.linkedin.com</code>
                    </li>
                    <li>
                      Copy the value of <code>li_at</code>. Optionally copy <code>JSESSIONID</code> too.
                    </li>
                  </ol>
                </div>
              </>
            ) : (
              <>
                <div>
                  <label className="label" htmlFor="li-email">
                    LinkedIn Email ID
                  </label>
                  <input
                    id="li-email"
                    type="email"
                    className="input"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="Your LinkedIn login email ID"
                    required
                  />
                </div>
                <div>
                  <label className="label" htmlFor="li-password">
                    LinkedIn password
                  </label>
                  <input
                    id="li-password"
                    type="password"
                    className="input"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    required
                  />
                  <p className="mt-1.5 text-xs text-slate-500">
                    Encrypted in transit to the worker and never stored. LinkedIn will usually ask
                    for a verification code, which you enter on the next screen.
                  </p>
                </div>
              </>
            )}

            <label className="flex items-center gap-2.5 text-[13.5px] font-medium text-slate-700">
              <input type="checkbox" defaultChecked className="h-4 w-4 rounded border-slate-300 text-brand-600" />
              Bill existing subscription
            </label>

            <div>
              <button
                type="button"
                onClick={() => setAdvancedOpen((v) => !v)}
                className="flex items-center gap-1.5 text-[13.5px] font-semibold text-slate-600 hover:text-ink-950"
              >
                <IconChevronDown className={`h-4 w-4 transition-transform ${advancedOpen ? "rotate-180" : ""}`} />
                Advanced options
              </button>

              {advancedOpen && (
                <div className="mt-4 space-y-4 rounded-lg border border-slate-200 bg-slate-50 p-4">
                  <div>
                    <label className="label" htmlFor="label">
                      Label (optional)
                    </label>
                    <input
                      id="label"
                      className="input"
                      value={label}
                      onChange={(e) => setLabel(e.target.value)}
                      placeholder="e.g. Tushar — founder profile"
                    />
                  </div>

                  {mode === "cookie" && (
                    <div>
                      <label className="label" htmlFor="jsessionid">
                        JSESSIONID (optional)
                      </label>
                      <input
                        id="jsessionid"
                        className="input font-mono text-xs"
                        value={jsessionid}
                        onChange={(e) => setJsessionid(e.target.value)}
                        placeholder="ajax:1234567890"
                      />
                    </div>
                  )}

                  <div className="grid gap-4 sm:grid-cols-2">
                    <div>
                      <label className="label" htmlFor="tz">
                        Account timezone
                      </label>
                      <select
                        id="tz"
                        className="input"
                        value={timezone}
                        onChange={(e) => setTimezone(e.target.value)}
                      >
                        {[timezone, ...COMMON_TIMEZONES.filter((t) => t !== timezone)].map((tz) => (
                          <option key={tz} value={tz}>
                            {tz}
                          </option>
                        ))}
                      </select>
                      <p className="mt-1.5 text-xs text-slate-500">Working hours are measured here.</p>
                    </div>

                    <div>
                      <label className="label" htmlFor="proxy">
                        Proxy
                      </label>
                      <select
                        id="proxy"
                        className="input"
                        value={proxyId}
                        onChange={(e) => setProxyId(e.target.value)}
                      >
                        <option value="">No proxy (direct)</option>
                        {available.map((p) => (
                          <option key={p.id} value={p.id}>
                            {p.label} {p.country ? `· ${p.country}` : ""}
                          </option>
                        ))}
                      </select>
                      {!proxyId && (
                        <p className="mt-1.5 text-xs text-state-warn">
                          Direct means this server&apos;s IP, shared by every account here. Fine for
                          testing, not for real outreach.
                        </p>
                      )}
                    </div>
                  </div>
                </div>
              )}
            </div>

            <div>
              <button
                type="button"
                onClick={() => setRemoteBrowserOpen(true)}
                className="flex w-fit items-center gap-2 rounded-lg border border-slate-200 px-4 py-2.5 text-[13px] font-semibold text-slate-600 hover:border-slate-300 hover:text-ink-950"
              >
                <IconLinkedIn className="h-4 w-4" />
                Sign in with browser
              </button>
              <p className="mt-1.5 text-xs text-slate-500">
                Recommended if the form above gets blocked — opens a real, visible browser you
                drive yourself, so you can solve any verification LinkedIn shows live.
              </p>
            </div>

            {error && (
              <p role="alert" className="text-sm text-state-bad">
                {error}
              </p>
            )}

            <div className="flex justify-end gap-3 border-t border-slate-200 pt-5">
              <button type="button" onClick={onClose} className="btn-ghost">
                Cancel
              </button>
              <button type="submit" className="btn-primary" disabled={busy}>
                {busy ? "Starting…" : "Connect"}
              </button>
            </div>
          </form>
        </div>
      </div>

      {remoteBrowserOpen && (
        <RemoteBrowserPanel
          workspaceId={workspaceId}
          label={label}
          timezone={timezone}
          proxyId={proxyId}
          onClose={() => setRemoteBrowserOpen(false)}
          onConnected={() => {
            setRemoteBrowserOpen(false);
            onConnected();
          }}
        />
      )}
    </div>
  );
}
