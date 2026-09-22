"use client";

/**
 * Proxy registry. Credentials are write-only: the API returns host and port
 * back, never the username or password.
 */

import { useState } from "react";
import { ApiError, linkedinApi, type ProxyRecord } from "@/lib/api";

export function ProxyPanel({
  workspaceId,
  proxies,
  onChanged,
}: {
  workspaceId: string;
  proxies: ProxyRecord[];
  onChanged: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({
    label: "",
    provider: "manual",
    scheme: "http",
    host: "",
    port: "",
    username: "",
    password: "",
    country: "",
    sticky_session_id: "",
  });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  function update(field: keyof typeof form) {
    return (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
      setForm((prev) => ({ ...prev, [field]: e.target.value }));
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await linkedinApi.createProxy(workspaceId, {
        label: form.label || undefined,
        provider: form.provider,
        scheme: form.scheme,
        host: form.host,
        port: Number(form.port),
        username: form.username || undefined,
        password: form.password || undefined,
        country: form.country.toUpperCase() || undefined,
        sticky_session_id: form.sticky_session_id || undefined,
      });
      setForm({ ...form, host: "", port: "", username: "", password: "", label: "" });
      setOpen(false);
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save the proxy");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card">
      <div className="mb-3 flex items-start justify-between gap-4">
        <div>
          <h2 className="font-medium text-slate-900">Proxies</h2>
          <p className="mt-1 text-sm text-slate-500">
            One residential IP per LinkedIn account, in the same country as the profile. Two
            accounts sharing an IP is the pattern LinkedIn clusters on.
          </p>
        </div>
        <button className="btn-ghost shrink-0" onClick={() => setOpen((v) => !v)}>
          {open ? "Cancel" : "Add proxy"}
        </button>
      </div>

      {open && (
        <form onSubmit={submit} className="mb-4 grid gap-3 rounded-md border border-slate-200 bg-slate-50 p-3 sm:grid-cols-2">
          <div>
            <label className="label" htmlFor="p-label">
              Label
            </label>
            <input id="p-label" className="input" value={form.label} onChange={update("label")} />
          </div>
          <div>
            <label className="label" htmlFor="p-provider">
              Provider
            </label>
            <input
              id="p-provider"
              className="input"
              value={form.provider}
              onChange={update("provider")}
              placeholder="brightdata / iproyal / oxylabs"
            />
          </div>
          <div className="grid grid-cols-3 gap-2 sm:col-span-2">
            <div>
              <label className="label" htmlFor="p-scheme">
                Scheme
              </label>
              <select id="p-scheme" className="input" value={form.scheme} onChange={update("scheme")}>
                <option value="http">http</option>
                <option value="https">https</option>
                <option value="socks5">socks5</option>
                <option value="socks5h">socks5h</option>
              </select>
            </div>
            <div>
              <label className="label" htmlFor="p-host">
                Host
              </label>
              <input id="p-host" className="input" value={form.host} onChange={update("host")} required />
            </div>
            <div>
              <label className="label" htmlFor="p-port">
                Port
              </label>
              <input
                id="p-port"
                type="number"
                className="input"
                value={form.port}
                onChange={update("port")}
                required
              />
            </div>
          </div>
          <div>
            <label className="label" htmlFor="p-user">
              Username
            </label>
            <input id="p-user" className="input" value={form.username} onChange={update("username")} />
          </div>
          <div>
            <label className="label" htmlFor="p-pass">
              Password
            </label>
            <input
              id="p-pass"
              type="password"
              className="input"
              value={form.password}
              onChange={update("password")}
            />
          </div>
          <div>
            <label className="label" htmlFor="p-country">
              Country (ISO-2)
            </label>
            <input
              id="p-country"
              className="input"
              maxLength={2}
              value={form.country}
              onChange={update("country")}
              placeholder="IN"
            />
          </div>
          <div>
            <label className="label" htmlFor="p-sticky">
              Sticky session id
            </label>
            <input
              id="p-sticky"
              className="input"
              value={form.sticky_session_id}
              onChange={update("sticky_session_id")}
              placeholder="optional, pins the exit IP"
            />
          </div>

          {error && (
            <p role="alert" className="text-sm text-state-bad sm:col-span-2">
              {error}
            </p>
          )}
          <div className="sm:col-span-2">
            <button type="submit" className="btn-primary" disabled={busy}>
              {busy ? "Saving…" : "Save proxy"}
            </button>
          </div>
        </form>
      )}

      {proxies.length === 0 ? (
        <p className="text-sm text-slate-500">
          None registered. Accounts will run over this server&apos;s IP until you add one.
        </p>
      ) : (
        <ul className="divide-y divide-slate-200">
          {proxies.map((proxy) => (
            <li key={proxy.id} className="flex flex-wrap items-center gap-3 py-2.5">
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm text-slate-800">
                  {proxy.label}{" "}
                  <span className="font-mono text-xs text-slate-500">{proxy.public_url}</span>
                </p>
                <p className="text-xs text-slate-500">
                  {proxy.provider}
                  {proxy.country && ` · ${proxy.country}`}
                  {proxy.assigned_account_id ? " · bound to an account" : " · available"}
                </p>
              </div>
              {!proxy.assigned_account_id && (
                <button
                  className="btn-ghost"
                  onClick={() =>
                    void linkedinApi.removeProxy(workspaceId, proxy.id).then(onChanged)
                  }
                >
                  Delete
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
