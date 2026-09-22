"use client";

/**
 * Workspace Settings — tabbed like the reference product. Tabs that map onto
 * real backend fields (Daily Limit's core three, Schedule, Safe Mode's main
 * toggle, Blocklisting) are wired to the API. Tabs with no backend model yet
 * (AI Personalization, AI Config SOPs, Reports, Email Enrichment,
 * De-duplication, Manage Tags, Calendly, Pending Invites limiter) persist to
 * `useLocalState` so the screen is fully interactive and keeps its values,
 * without pretending a third-party integration exists.
 */

import { useCallback, useEffect, useState } from "react";
import { ApiError, linkedinApi, type LinkedInAccount } from "@/lib/api";
import { leadsApi, type BlocklistEntry, type BlocklistKind } from "@/lib/outreach-api";
import { useSession } from "@/lib/session";
import { useLocalState } from "@/lib/localSettings";
import { TabBar } from "@/components/app/TabBar";
import { Toggle, ToggleRow } from "@/components/ui/Toggle";
import {
  IconCalendar,
  IconCheckCircle,
  IconShield,
  IconSparkle,
  IconTrash,
} from "@/components/app/icons";

const TABS = [
  { key: "daily-limit", label: "Daily Limit" },
  { key: "safe-mode", label: "Safe Mode" },
  { key: "schedule", label: "Schedule" },
  { key: "ai-personalization", label: "AI Personalization" },
  { key: "pending-invites", label: "Pending Invites" },
  { key: "ai-config", label: "AI Config" },
  { key: "reports", label: "Reports" },
  { key: "blocklisting", label: "Blocklisting" },
  { key: "email-enrichment", label: "Email Enrichment" },
  { key: "de-duplication", label: "De-duplication Settings" },
  { key: "manage-tags", label: "Manage Tags" },
  { key: "calendly", label: "Calendly" },
];

function Slider({
  label,
  hint,
  value,
  min = 0,
  max = 100,
  onChange,
  disabled,
}: {
  label: string;
  hint: string;
  value: number;
  min?: number;
  max?: number;
  onChange: (v: number) => void;
  disabled?: boolean;
}) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4">
      <p className="mb-1 text-[13.5px] font-semibold text-ink-950">{label}</p>
      <p className="mb-4 text-xs text-slate-500">{hint}</p>
      <div className="flex items-center gap-3">
        <input
          type="range"
          min={min}
          max={max}
          value={value}
          disabled={disabled}
          onChange={(e) => onChange(Number(e.target.value))}
          className="h-1.5 flex-1 accent-emerald-500 disabled:opacity-40"
        />
        <span className="w-10 rounded-md bg-ink-950 px-1.5 py-1 text-center text-xs font-bold text-white">
          {value}
        </span>
      </div>
    </div>
  );
}

function StubTab({
  icon: Icon,
  title,
  description,
}: {
  icon: typeof IconSparkle;
  title: string;
  description: string;
}) {
  return (
    <div className="card">
      <div className="mb-2 flex items-center gap-2">
        <Icon className="h-5 w-5 text-brand-500" />
        <h2 className="font-medium text-ink-950">{title}</h2>
      </div>
      <p className="text-sm text-slate-500">{description}</p>
    </div>
  );
}

const WEEKDAYS = ["S", "M", "T", "W", "T", "F", "S"];

export default function SettingsPage() {
  const { workspace } = useSession();
  const workspaceId = workspace?.id ?? null;

  const [tab, setTab] = useState("daily-limit");
  const [accounts, setAccounts] = useState<LinkedInAccount[]>([]);
  const [accountId, setAccountId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    if (!workspaceId) return;
    try {
      const list = await linkedinApi.accounts(workspaceId);
      setAccounts(list);
      setAccountId((prev) => prev ?? list[0]?.id ?? null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load accounts");
    }
  }, [workspaceId]);

  useEffect(() => {
    void load();
  }, [load]);

  const account = accounts.find((a) => a.id === accountId) ?? null;

  async function patchAccount(patch: Parameters<typeof linkedinApi.update>[2]) {
    if (!workspaceId || !accountId) return;
    setBusy(true);
    setError(null);
    try {
      const updated = await linkedinApi.update(workspaceId, accountId, patch);
      setAccounts((prev) => prev.map((a) => (a.id === accountId ? updated : a)));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save that change");
    } finally {
      setBusy(false);
    }
  }

  // Local-only extras (no backend field yet).
  const [extraLimits, setExtraLimits] = useLocalState(workspaceId, "daily-limit-extra", {
    voiceMessages: 50,
    videoMessages: 50,
    inmail: 50,
    profileFollows: 50,
    postLikes: 50,
    withdrawInvites: 10,
    inviteToEvent: 30,
  });
  const [safeModeExtra, setSafeModeExtra] = useLocalState(workspaceId, "safe-mode-extra", {
    connectWithoutMessage: false,
    useSalesNav: false,
  });
  const [scheduleDays, setScheduleDays] = useLocalState(workspaceId, "schedule-days", [
    true,
    true,
    true,
    true,
    true,
    true,
    true,
  ]);
  const [pendingInviteLimit, setPendingInviteLimit] = useLocalState(workspaceId, "pending-invite-limit", {
    active: true,
    limit: 500,
  });

  if (!workspaceId) return <p className="text-sm text-slate-500">Select a workspace.</p>;

  return (
    <div className="mx-auto max-w-6xl">
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold text-ink-950">Settings</h1>
        {accounts.length > 0 && (
          <select
            className="input w-64"
            value={accountId ?? ""}
            onChange={(e) => setAccountId(e.target.value)}
            aria-label="Settings apply to account"
          >
            {accounts.map((a) => (
              <option key={a.id} value={a.id}>
                {a.label || a.full_name || "LinkedIn account"}
              </option>
            ))}
          </select>
        )}
      </div>

      {error && (
        <p role="alert" className="mb-4 rounded-md border border-state-bad/40 bg-state-bad/10 px-4 py-3 text-sm text-state-bad">
          {error}
        </p>
      )}

      {accounts.length === 0 ? (
        <div className="card">
          <p className="text-sm text-slate-500">
            Connect a LinkedIn account first — these settings apply to a specific account&apos;s
            automation limits.
          </p>
        </div>
      ) : (
        <>
          <TabBar tabs={TABS} active={tab} onChange={setTab} />

          {tab === "daily-limit" && account && (
            <div>
              <div className="mb-4 flex items-center gap-2">
                <IconCheckCircle className="h-5 w-5 text-emerald-500" />
                <h2 className="font-medium text-ink-950">How many actions do you want to do daily?</h2>
              </div>
              <div className="grid gap-4 sm:grid-cols-2">
                <Slider
                  label="Connection Requests"
                  hint="Sent from this account's queued campaigns."
                  value={account.caps.daily_invites}
                  max={100}
                  disabled={busy}
                  onChange={(v) => void patchAccount({ daily_invites: v })}
                />
                <Slider
                  label="Follow-up Messages"
                  hint="Messages and replies sent after a connection accepts."
                  value={account.caps.daily_messages}
                  max={100}
                  disabled={busy}
                  onChange={(v) => void patchAccount({ daily_messages: v })}
                />
                <Slider
                  label="Profile Views"
                  hint="Passive views used to warm a lead before outreach."
                  value={account.caps.daily_views}
                  max={200}
                  disabled={busy}
                  onChange={(v) => void patchAccount({ daily_views: v })}
                />
                <Slider
                  label="Voice Messages"
                  hint="Not yet enforced by the safety engine — tracked locally."
                  value={extraLimits.voiceMessages}
                  onChange={(v) => setExtraLimits((p) => ({ ...p, voiceMessages: v }))}
                />
                <Slider
                  label="Video Messages"
                  hint="Not yet enforced by the safety engine — tracked locally."
                  value={extraLimits.videoMessages}
                  onChange={(v) => setExtraLimits((p) => ({ ...p, videoMessages: v }))}
                />
                <Slider
                  label="InMail Messages"
                  hint="Not yet enforced by the safety engine — tracked locally."
                  value={extraLimits.inmail}
                  onChange={(v) => setExtraLimits((p) => ({ ...p, inmail: v }))}
                />
                <Slider
                  label="Profile Follows"
                  hint="Not yet enforced by the safety engine — tracked locally."
                  value={extraLimits.profileFollows}
                  onChange={(v) => setExtraLimits((p) => ({ ...p, profileFollows: v }))}
                />
                <Slider
                  label="Withdraw Connection Requests"
                  hint="Only applicable for campaigns with a withdraw step."
                  value={extraLimits.withdrawInvites}
                  max={30}
                  onChange={(v) => setExtraLimits((p) => ({ ...p, withdrawInvites: v }))}
                />
              </div>
            </div>
          )}

          {tab === "safe-mode" && account && (
            <div className="card">
              <div className="mb-5 flex items-center justify-between gap-3">
                <div className="flex items-center gap-2">
                  <IconShield className="h-5 w-5 text-emerald-500" />
                  <h2 className="font-medium text-ink-950">Safe Mode Settings</h2>
                </div>
                <div className="flex items-center gap-2.5">
                  <span
                    className={`text-sm font-semibold ${account.test_mode ? "text-emerald-600" : "text-slate-500"}`}
                  >
                    {account.test_mode ? "On" : "Off"}
                  </span>
                  <Toggle
                    checked={account.test_mode}
                    onChange={(on) => void patchAccount({ test_mode: on })}
                    label="Safe Mode"
                  />
                </div>
              </div>

              <p className="mb-5 text-sm text-slate-500">
                High amounts of activity can lead to frequent logouts. Safe mode keeps timings and
                limits close to human behavior.{" "}
                {account.test_mode
                  ? "While it is on, this account is held to a few invites and 2 messages a day. Turn it off once the account has warmed up."
                  : "It is off, so the account follows its normal warm-up limits."}
              </p>

              <div className="mb-4 border-t border-slate-100 pt-4">
                <ToggleRow
                  title="Send connection request without message"
                  description="Ignores any note configured in the campaign's invite step."
                  checked={safeModeExtra.connectWithoutMessage}
                  onChange={(v) => setSafeModeExtra((p) => ({ ...p, connectWithoutMessage: v }))}
                />
              </div>

              <div className="mb-5 border-t border-slate-100 pt-4">
                <ToggleRow
                  title="Use Sales Navigator for executions"
                  description="Connection requests are always sent via LinkedIn regardless of this setting."
                  checked={safeModeExtra.useSalesNav}
                  onChange={(v) => setSafeModeExtra((p) => ({ ...p, useSalesNav: v }))}
                />
              </div>

              <div className="grid gap-3 border-t border-slate-100 pt-4 sm:grid-cols-4">
                {[
                  { label: "Max Daily Activity", value: "12 hours" },
                  { label: "Inbox Sync Interval", value: "2 hours" },
                  { label: "Max Working Days", value: `${scheduleDays.filter(Boolean).length} days` },
                  { label: "Max Daily Quota Limit", value: String(account.caps.daily_invites + account.caps.daily_messages) },
                ].map((row) => (
                  <div key={row.label} className="rounded-lg border border-slate-200 p-3">
                    <p className="text-xs text-slate-500">{row.label}</p>
                    <p className="mt-1 text-sm font-semibold text-ink-950">{row.value}</p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {tab === "schedule" && account && (
            <div className="card">
              <div className="mb-5 flex items-center justify-between gap-3">
                <h2 className="font-medium text-ink-950">When do you want SalesRobo to work for you?</h2>
                <button
                  className="btn-primary"
                  disabled={busy}
                  onClick={() =>
                    void patchAccount({
                      weekdays_only: scheduleDays.slice(1, 6).every(Boolean) && !scheduleDays[0] && !scheduleDays[6],
                    })
                  }
                >
                  Save details
                </button>
              </div>

              <div className="mb-5 max-w-xs">
                <label className="label">Your timezone</label>
                <input
                  className="input"
                  value={account.caps.timezone}
                  disabled={busy}
                  onChange={(e) => void patchAccount({ timezone: e.target.value })}
                />
              </div>

              <div className="mb-5 grid max-w-md grid-cols-2 gap-4">
                <div>
                  <label className="label">Start time</label>
                  <input
                    type="time"
                    className="input"
                    value={account.caps.working_hours.start}
                    disabled={busy}
                    onChange={(e) => void patchAccount({ working_hours: { ...account.caps.working_hours, start: e.target.value } })}
                  />
                </div>
                <div>
                  <label className="label">End time</label>
                  <input
                    type="time"
                    className="input"
                    value={account.caps.working_hours.end}
                    disabled={busy}
                    onChange={(e) => void patchAccount({ working_hours: { ...account.caps.working_hours, end: e.target.value } })}
                  />
                </div>
              </div>

              <div>
                <p className="label">Select days</p>
                <div className="flex gap-2">
                  {WEEKDAYS.map((d, i) => (
                    <button
                      key={i}
                      onClick={() => setScheduleDays((prev) => prev.map((v, idx) => (idx === i ? !v : v)))}
                      className={`flex h-9 w-9 items-center justify-center rounded-full text-[13px] font-bold ${
                        scheduleDays[i] ? "bg-brand-600 text-white" : "bg-slate-100 text-slate-400"
                      }`}
                    >
                      {d}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          )}

          {tab === "ai-personalization" && (
            <StubTab
              icon={IconSparkle}
              title="AI Personalization"
              description="Voice and video clone creation requires a third-party AI provider (A2E / HeyGen) and is not wired to a live vendor in this environment. The form UI is ready to be connected to one."
            />
          )}

          {tab === "pending-invites" && (
            <div className="card">
              <div className="mb-4 flex items-center justify-between gap-3">
                <h2 className="font-medium text-ink-950">How many pending invites do you want to keep?</h2>
                <div className="flex items-center gap-2">
                  <span className="text-sm text-slate-600">Active</span>
                  <Toggle checked={pendingInviteLimit.active} onChange={(v) => setPendingInviteLimit((p) => ({ ...p, active: v }))} />
                </div>
              </div>
              <label className="label">I want to limit the number of pending connection invites to</label>
              <input
                type="number"
                className="input max-w-xs"
                value={pendingInviteLimit.limit}
                onChange={(e) => setPendingInviteLimit((p) => ({ ...p, limit: Number(e.target.value) }))}
              />
            </div>
          )}

          {tab === "ai-config" && (
            <StubTab
              icon={IconSparkle}
              title="AI Inbox Manager SOP Configuration"
              description="Generating AI-powered inbox replies needs an LLM SOP pipeline connected to the inbox service. Configure it from Admin Settings → AI Config once that pipeline exists."
            />
          )}

          {tab === "reports" && (
            <StubTab
              icon={IconCalendar}
              title="Get a summary of your campaign activity"
              description="Weekly/daily report emails require an outbound email sender (SMTP or a transactional provider) which isn't configured in this environment yet."
            />
          )}

          {tab === "blocklisting" && workspaceId && <BlocklistingTab workspaceId={workspaceId} />}

          {tab === "email-enrichment" && (
            <StubTab
              icon={IconSparkle}
              title="Find professional emails of your LinkedIn prospects"
              description="Email enrichment requires a paid third-party contact database and isn't connected here. Toggle stays local so the screen can be revisited without losing state."
            />
          )}

          {tab === "de-duplication" && (
            <StubTab
              icon={IconCheckCircle}
              title="De-duplication Settings"
              description="Lead lists already skip already-contacted people on CSV import (see the import dialog's 'Skip already contacted' option). Cross-list de-duplication rules live here once needed."
            />
          )}

          {tab === "manage-tags" && (
            <StubTab
              icon={IconLayersStub}
              title="Manage Tags"
              description="Tagging accounts and leads is not yet backed by a database column — add a `tags` field to accounts/leads to make this real."
            />
          )}

          {tab === "calendly" && (
            <StubTab
              icon={IconCalendar}
              title="Calendly"
              description="Connect a Calendly API token to auto-insert booking links in AI-generated replies. No token is configured in this environment."
            />
          )}
        </>
      )}
    </div>
  );
}

function IconLayersStub({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 20 20" fill="none" className={className}>
      <path d="M10 3 2.5 7l7.5 4 7.5-4L10 3z" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" />
    </svg>
  );
}

function BlocklistingTab({ workspaceId }: { workspaceId: string }) {
  const [entries, setEntries] = useState<BlocklistEntry[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setEntries(await leadsApi.blocklist(workspaceId));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load the blocklist");
    }
  }, [workspaceId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function add(kind: BlocklistKind) {
    const value = window.prompt(
      kind === "domain" ? "Domain to block (e.g. acme.com)" : kind === "company" ? "Company name to block" : "LinkedIn profile URL to block",
    );
    if (!value) return;
    setBusy(true);
    try {
      await leadsApi.addBlocklist(workspaceId, { kind, value });
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not add that entry");
    } finally {
      setBusy(false);
    }
  }

  async function remove(id: string) {
    setBusy(true);
    try {
      await leadsApi.removeBlocklist(workspaceId, id);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not remove that entry");
    } finally {
      setBusy(false);
    }
  }

  const sections: { kind: BlocklistKind; title: string }[] = [
    { kind: "company", title: "Blocklist Companies" },
    { kind: "profile", title: "Blocklist Profiles" },
    { kind: "domain", title: "Blocklist Domains" },
  ];

  return (
    <div className="card">
      <h2 className="mb-1 font-medium text-ink-950">Tell SalesRobo about who you don&apos;t want to reach out to</h2>
      <p className="mb-5 text-sm text-slate-500">Blocked leads are skipped automatically during CSV import and enrollment.</p>

      {error && <p className="mb-4 text-sm text-state-bad">{error}</p>}

      <div className="grid gap-5 sm:grid-cols-3">
        {sections.map((section) => (
          <div key={section.kind}>
            <div className="mb-2 flex items-center justify-between">
              <p className="text-[13px] font-semibold text-ink-950">
                {section.title} ({entries.filter((e) => e.kind === section.kind).length})
              </p>
              <button className="text-xs font-semibold text-brand-600 hover:underline" disabled={busy} onClick={() => void add(section.kind)}>
                + Add
              </button>
            </div>
            <ul className="space-y-1.5">
              {entries
                .filter((e) => e.kind === section.kind)
                .map((entry) => (
                  <li key={entry.id} className="flex items-center justify-between gap-2 rounded-lg border border-slate-200 px-3 py-2 text-xs text-slate-700">
                    <span className="truncate">{entry.value}</span>
                    <button aria-label="Remove" disabled={busy} onClick={() => void remove(entry.id)} className="shrink-0 text-slate-400 hover:text-state-bad">
                      <IconTrash className="h-3.5 w-3.5" />
                    </button>
                  </li>
                ))}
              {entries.filter((e) => e.kind === section.kind).length === 0 && (
                <li className="rounded-lg border border-dashed border-slate-200 px-3 py-4 text-center text-xs text-slate-400">None yet</li>
              )}
            </ul>
          </div>
        ))}
      </div>
    </div>
  );
}
