"use client";

/**
 * One connected LinkedIn account: identity, safety state, and the controls that
 * change it.
 *
 * The limits panel deliberately shows *why* a number is what it is
 * (`invite_limit_reason`). A cap the user cannot explain is a cap they will try
 * to work around.
 */

import { ToggleRow } from "@/components/ui/Toggle";
import { useState } from "react";
import clsx from "clsx";
import { ApiError, linkedinApi, type LinkedInAccount, type ProxyRecord } from "@/lib/api";
import { publishingApi } from "@/lib/content-api";
import { HealthBar, StatusPill } from "@/components/StatusPill";

function relative(iso: string | null): string {
  if (!iso) return "never";
  const delta = Date.now() - new Date(iso).getTime();
  const minutes = Math.round(delta / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

export function AccountCard({
  workspaceId,
  account,
  proxies = [],
  onChanged,
}: {
  workspaceId: string;
  account: LinkedInAccount;
  proxies?: ProxyRecord[];
  onChanged: () => void;
}) {
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState(false);
  const [reconnecting, setReconnecting] = useState(false);
  const [liAt, setLiAt] = useState("");
  const [invites, setInvites] = useState(account.caps.daily_invites);
  const [hours, setHours] = useState(account.caps.working_hours);
  const [weekdaysOnly, setWeekdaysOnly] = useState(account.caps.weekdays_only);
  const [testMode, setTestMode] = useState(account.test_mode);
  const [proxyId, setProxyId] = useState("");

  const assignableProxies = proxies.filter(
    (p) => !p.assigned_account_id || p.assigned_account_id === account.id,
  );

  async function run(action: () => Promise<unknown>) {
    setError(null);
    setBusy(true);
    try {
      await action();
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  const awaitingCode =
    account.status === "pending_2fa" || account.status === "pending_email_pin";
  const needsReconnect =
    account.status === "auth_lost" || account.status === "blocked" || account.status === "challenge";

  return (
    <article className="card">
      <header className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="truncate font-medium text-ink-950">{account.label || "LinkedIn account"}</h3>
            <StatusPill status={account.status} />
            {account.test_mode && <span className="badge">test mode</span>}
          </div>
          <p className="mt-1 truncate text-sm text-slate-500">
            {account.full_name || account.login_email || "identity not yet known"}
            {account.public_id && (
              <>
                {" · "}
                <a
                  href={account.profile_url}
                  target="_blank"
                  rel="noreferrer"
                  className="text-accent hover:underline"
                >
                  /in/{account.public_id}
                </a>
              </>
            )}
          </p>
          {account.headline && (
            <p className="mt-0.5 truncate text-xs text-slate-500">{account.headline}</p>
          )}
        </div>
        <HealthBar score={account.health_score} />
      </header>

      {account.warnings.length > 0 && (
        <ul className="mb-4 space-y-2">
          {account.warnings.map((warning) => (
            <li
              key={warning}
              className="rounded-md border border-state-warn/30 bg-state-warn/5 px-3 py-2 text-xs text-state-warn"
            >
              {warning}
            </li>
          ))}
        </ul>
      )}

      {needsReconnect && (
        <div className="mb-4 rounded-md border border-state-bad/40 bg-state-bad/10 p-3">
          <p className="mb-1 text-sm font-medium text-state-bad">
            Outreach from this account is paused.
          </p>
          <p className="text-xs text-state-bad">
            {account.status_detail || "LinkedIn ended this session."}
            {account.using_direct_connection &&
              " This is a common cause of a lost session: no residential proxy is assigned, so LinkedIn sees the request coming from a different network than the one that issued the session. Assign a proxy, then reconnect."}
          </p>

          {reconnecting ? (
            <form
              className="mt-3 space-y-2"
              onSubmit={(e) => {
                e.preventDefault();
                void run(async () => {
                  await linkedinApi.connectWithCookie(workspaceId, {
                    li_at: liAt,
                    timezone: account.caps.timezone,
                    account_id: account.id,
                  });
                  setLiAt("");
                  setReconnecting(false);
                });
              }}
            >
              <label className="label" htmlFor={`reconnect-liat-${account.id}`}>
                Fresh li_at cookie
              </label>
              <textarea
                id={`reconnect-liat-${account.id}`}
                className="input h-16 font-mono text-xs"
                value={liAt}
                onChange={(e) => setLiAt(e.target.value)}
                placeholder="AQEDAT…"
                required
              />
              <p className="text-[11px] text-state-bad/80">
                Re-using this account keeps its device identity frozen — reconnecting from
                scratch would draw a new one, which is itself a red flag LinkedIn watches for.
              </p>
              <div className="flex gap-2">
                <button type="submit" className="btn-primary !py-1.5 text-[13px]" disabled={busy}>
                  {busy ? "Reconnecting…" : "Reconnect"}
                </button>
                <button
                  type="button"
                  className="btn-ghost !py-1.5 text-[13px]"
                  onClick={() => setReconnecting(false)}
                >
                  Cancel
                </button>
              </div>
            </form>
          ) : (
            <button
              className="mt-2 text-[12.5px] font-semibold text-state-bad underline underline-offset-2"
              onClick={() => setReconnecting(true)}
            >
              Reconnect this account
            </button>
          )}
        </div>
      )}

      {/*
        Publishing authorization. Separate from the automation session above by
        design: that is a browser session for outreach, this is a LinkedIn OAuth
        grant for posting on the member's behalf. One does not imply the other,
        so the card reports them separately rather than showing a single
        "connected" state that would be misleading for either.
      */}
      <div
        className={clsx(
          "mb-4 rounded-md border p-3",
          account.publishing.available
            ? "border-state-ok/30 bg-state-ok/5"
            : "border-slate-200 bg-slate-50",
        )}
      >
        <div className="flex flex-wrap items-center gap-2">
          <p className="text-sm font-medium text-slate-800">Content Studio publishing</p>
          <span
            className={clsx(
              "rounded-full border px-2 py-0.5 text-[11px] font-semibold",
              account.publishing.available
                ? "border-state-ok/40 bg-state-ok/10 text-state-ok"
                : "border-slate-300 bg-white text-slate-500",
            )}
          >
            {account.publishing.available ? "Authorized" : "Not authorized"}
          </span>
        </div>
        <p className="mt-1 text-xs text-slate-600">{account.publishing.message}</p>
        {account.publishing.available && account.publishing.scopes.length > 0 && (
          <p className="mt-1 font-mono text-[11px] text-slate-400">
            {account.publishing.scopes.join(" ")}
          </p>
        )}

        <div className="mt-2.5 flex flex-wrap gap-2">
          {account.publishing.remedy === "authorize" && (
            <button
              type="button"
              disabled={busy}
              onClick={() =>
                void run(async () => {
                  const { authorize_url } = await publishingApi.authorizeUrl(
                    workspaceId,
                    account.id,
                  );
                  window.location.href = authorize_url;
                })
              }
              className="btn-primary !py-1.5 text-[13px]"
            >
              {account.publishing.code === "expired" ? "Reconnect for publishing" : "Connect for publishing"}
            </button>
          )}
          {account.publishing.available && (
            <button
              type="button"
              disabled={busy}
              onClick={() => void run(() => publishingApi.revoke(workspaceId, account.id))}
              className="btn-ghost !py-1.5 text-[13px]"
            >
              Revoke posting access
            </button>
          )}
          {account.publishing.code === "not_configured" && (
            <p className="text-[11.5px] text-slate-500">
              See docs/LINKEDIN_PUBLISHING_REQUIREMENTS.md for what an administrator needs to set up.
            </p>
          )}
        </div>
      </div>

      {awaitingCode && (
        <div className="mb-4 rounded-md border border-state-warn/40 bg-state-warn/10 p-3">
          <p className="mb-2 text-sm text-state-warn">
            {account.status_detail || "LinkedIn sent a verification code."}
          </p>
          <form
            className="flex gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              void run(() => linkedinApi.submitCode(workspaceId, account.id, code));
            }}
          >
            <input
              className="input w-32 font-mono"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              placeholder="123456"
              inputMode="numeric"
              required
            />
            <button type="submit" className="btn-primary" disabled={busy}>
              Submit code
            </button>
          </form>
        </div>
      )}

      <dl className="mb-4 grid gap-3 text-xs sm:grid-cols-2 lg:grid-cols-4">
        <div>
          <dt className="text-slate-500">Invites / day</dt>
          <dd className="mt-0.5 text-sm text-slate-800">
            {account.caps.daily_invites}
            <span className="ml-1 text-xs text-slate-500">({account.caps.invite_limit_reason})</span>
          </dd>
        </div>
        <div>
          <dt className="text-slate-500">Working hours</dt>
          <dd className="mt-0.5 text-sm text-slate-800">
            {account.caps.working_hours.start}–{account.caps.working_hours.end}{" "}
            <span className="text-xs text-slate-500">{account.caps.timezone}</span>
          </dd>
        </div>
        <div>
          <dt className="text-slate-500">Connection</dt>
          <dd className="mt-0.5 text-sm text-slate-800">
            {account.using_direct_connection ? (
              <span className="text-state-warn">direct (no proxy)</span>
            ) : (
              <>
                {account.proxy_label}
                {account.proxy_country && (
                  <span className="text-xs text-slate-500"> · {account.proxy_country}</span>
                )}
              </>
            )}
          </dd>
        </div>
        <div>
          <dt className="text-slate-500">Device</dt>
          <dd className="mt-0.5 text-sm text-slate-800">{account.device}</dd>
        </div>
      </dl>

      <p className="mb-4 text-xs text-slate-500">
        {account.within_working_hours
          ? "Inside working hours — actions may fire now."
          : `Idle: ${account.working_hours_detail}`}
        {" · "}session checked {relative(account.session_updated_at)}
        {" · "}last action {relative(account.last_action_at)}
        {account.consecutive_errors > 0 && ` · ${account.consecutive_errors} consecutive errors`}
      </p>

      {editing && (
        <form
          className="mb-4 grid gap-3 rounded-md border border-slate-200 bg-slate-50 p-3 sm:grid-cols-2"
          onSubmit={(e) => {
            e.preventDefault();
            void run(async () => {
              await linkedinApi.update(workspaceId, account.id, {
                daily_invites: invites,
                working_hours: hours,
                weekdays_only: weekdaysOnly,
                test_mode: testMode,
                ...(proxyId ? { proxy_id: proxyId } : {}),
              });
              setEditing(false);
            });
          }}
        >
          <div>
            <label className="label" htmlFor={`inv-${account.id}`}>
              Invites per day
            </label>
            <input
              id={`inv-${account.id}`}
              type="number"
              min={1}
              max={100}
              className="input"
              value={invites}
              onChange={(e) => setInvites(Number(e.target.value))}
            />
            <p className="mt-1 text-xs text-slate-500">
              The server clamps this to the warm-up curve and the safety ceiling.
            </p>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="label" htmlFor={`from-${account.id}`}>
                From
              </label>
              <input
                id={`from-${account.id}`}
                type="time"
                className="input"
                value={hours.start}
                onChange={(e) => setHours({ ...hours, start: e.target.value })}
              />
            </div>
            <div>
              <label className="label" htmlFor={`to-${account.id}`}>
                To
              </label>
              <input
                id={`to-${account.id}`}
                type="time"
                className="input"
                value={hours.end}
                onChange={(e) => setHours({ ...hours, end: e.target.value })}
              />
            </div>
          </div>
          <div className="sm:col-span-2 space-y-4 rounded-lg border border-slate-200 p-4">
            <ToggleRow
              title="Weekdays only"
              description="Only act Monday to Friday, in this account's own time zone."
              checked={weekdaysOnly}
              onChange={setWeekdaysOnly}
            />
            <div className="border-t border-slate-100 pt-4">
              <ToggleRow
                title="Safe mode (test limits)"
                description="Hard cap of a few invites and 2 messages a day. Keep it on for the first 1 to 2 weeks."
                checked={testMode}
                onChange={setTestMode}
              />
            </div>
          </div>
          <div className="sm:col-span-2">
            <label className="label" htmlFor={`proxy-${account.id}`}>
              Proxy
            </label>
            <select
              id={`proxy-${account.id}`}
              className="input"
              value={proxyId}
              onChange={(e) => setProxyId(e.target.value)}
            >
              <option value="">
                {account.using_direct_connection ? "No proxy (keep running direct)" : "Keep current proxy"}
              </option>
              {assignableProxies.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.label || p.public_url} {p.country ? `· ${p.country}` : ""}
                  {p.assigned_account_id === account.id ? " (current)" : ""}
                </option>
              ))}
            </select>
            {assignableProxies.length === 0 && (
              <p className="mt-1 text-xs text-slate-500">
                No proxies available. Add one in the Proxies section below, then come back here to
                assign it.
              </p>
            )}
          </div>
          <div className="flex gap-2 sm:col-span-2">
            <button type="submit" className="btn-primary" disabled={busy}>
              Save limits
            </button>
            <button type="button" className="btn-ghost" onClick={() => setEditing(false)}>
              Cancel
            </button>
          </div>
        </form>
      )}

      {error && (
        <p role="alert" className="mb-3 text-sm text-state-bad">
          {error}
        </p>
      )}

      <div className="flex flex-wrap gap-2">
        <button className="btn-ghost" onClick={() => setEditing((v) => !v)} disabled={busy}>
          {editing ? "Hide limits" : "Limits"}
        </button>
        {account.is_connected && (
          <button
            className="btn-ghost"
            disabled={busy}
            onClick={() => void run(() => linkedinApi.verify(workspaceId, account.id))}
          >
            Check session
          </button>
        )}
        {account.status === "active" && (
          <button
            className="btn-ghost"
            disabled={busy}
            onClick={() => void run(() => linkedinApi.setPaused(workspaceId, account.id, true))}
          >
            Pause
          </button>
        )}
        {account.status === "paused" && (
          <button
            className="btn-ghost"
            disabled={busy}
            onClick={() => void run(() => linkedinApi.setPaused(workspaceId, account.id, false))}
          >
            Resume
          </button>
        )}
        {account.is_connected && (
          <button
            className="btn-ghost"
            disabled={busy}
            onClick={() => void run(() => linkedinApi.disconnect(workspaceId, account.id))}
          >
            Disconnect
          </button>
        )}
        <button
          className="btn-danger"
          disabled={busy}
          onClick={() => {
            if (window.confirm(`Remove ${account.label || "this account"}? This cannot be undone.`)) {
              void run(() => linkedinApi.remove(workspaceId, account.id));
            }
          }}
        >
          Remove
        </button>
      </div>
    </article>
  );
}
