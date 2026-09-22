"use client";

/** Campaign list, creation wizard, and the live safety panel. */

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import clsx from "clsx";
import { ApiError, linkedinApi, type LinkedInAccount } from "@/lib/api";
import { campaignsApi, type Campaign, type CampaignStatus, type QuotaStatus, type StepInput } from "@/lib/outreach-api";
import { useSession } from "@/lib/session";
import { TabBar } from "@/components/app/TabBar";
import { ProspectsTable } from "@/components/app/ProspectsTable";
import { LeadListTable } from "@/components/app/LeadListTable";
import { TEMPLATE_HANDOFF_KEY } from "@/lib/templates";
import { CampaignWizard } from "@/components/CampaignWizard";
import { IconArrowRight, IconPlus, IconSearch, IconTracking } from "@/components/app/icons";

const PAGE_TABS = [
  { key: "campaigns", label: "Campaigns" },
  { key: "prospects", label: "Prospects" },
  { key: "leadlist", label: "Lead List" },
];

const STATUS_STYLES: Record<CampaignStatus, string> = {
  draft: "border-slate-200 bg-slate-100 text-slate-500",
  running: "border-state-ok/40 bg-state-ok/10 text-state-ok",
  paused: "border-state-warn/40 bg-state-warn/10 text-state-warn",
  completed: "border-accent/40 bg-accent/10 text-accent",
  archived: "border-slate-200 bg-slate-100 text-slate-500",
};

function pct(value: number | null): string {
  return value === null ? "—" : `${Math.round(value * 100)}%`;
}

function QuotaPanel({ quotas }: { quotas: QuotaStatus[] }) {
  if (quotas.length === 0) return null;

  return (
    <section className="card mb-6">
      <h2 className="mb-1 font-medium text-slate-900">What the safety engine allows right now</h2>
      <p className="mb-4 text-sm text-slate-500">
        A campaign that looks idle is usually being held by one of these, not broken.
      </p>
      <ul className="space-y-3">
        {quotas.map((quota) => (
          <li key={quota.linkedin_account_id} className="rounded-md border border-slate-200 bg-slate-50 p-3">
            <div className="mb-2 flex flex-wrap items-center gap-2">
              <span className="text-sm font-medium text-slate-800">{quota.label}</span>
              <span className="badge">{quota.status.replace("_", " ")}</span>
              {quota.blocked_reason ? (
                <span className="text-xs text-state-warn">{quota.blocked_reason}</span>
              ) : (
                <span className="text-xs text-state-ok">clear to send</span>
              )}
            </div>
            <div className="grid gap-2 text-xs sm:grid-cols-3">
              <div>
                <span className="text-slate-500">Invites today </span>
                <span className="text-slate-800">
                  {quota.invites_used_today}/{quota.invites_limit_today}
                </span>
                <span className="text-slate-500"> ({quota.invite_limit_reason})</span>
              </div>
              <div>
                <span className="text-slate-500">Invites this week </span>
                <span className="text-slate-800">
                  {quota.invites_used_this_week}/{quota.invites_limit_this_week}
                </span>
              </div>
              <div>
                <span className="text-slate-500">Messages today </span>
                <span className="text-slate-800">
                  {quota.messages_used_today}/{quota.messages_limit_today}
                </span>
              </div>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

function CampaignsTable({
  campaigns,
  loading,
  accounts,
}: {
  campaigns: Campaign[];
  loading: boolean;
  accounts: LinkedInAccount[];
}) {
  const [search, setSearch] = useState("");
  const filtered = campaigns.filter((c) => c.name.toLowerCase().includes(search.trim().toLowerCase()));

  return (
    <>
      <div className="mb-4 flex items-center gap-3">
        <div className="relative max-w-sm flex-1">
          <IconSearch className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search campaign by name"
            className="input pl-9"
          />
        </div>
      </div>

      <div className="overflow-hidden rounded-xl border border-slate-200 bg-white">
        <table className="w-full text-left">
          <thead>
            <tr className="border-b border-slate-200 bg-slate-50/70">
              {["Campaign name", "Source", "Campaign progress", "Performance", "Tracking"].map((h) => (
                <th key={h} className="px-4 py-3 text-[11px] font-bold uppercase tracking-wider text-slate-500">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={5} className="px-4 py-10 text-center text-sm text-slate-400">
                  Loading…
                </td>
              </tr>
            ) : filtered.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-4 py-16 text-center">
                  <p className="mb-1 text-sm font-medium text-slate-500">
                    {campaigns.length === 0 ? "No campaigns yet" : "No campaigns match your search"}
                  </p>
                  {campaigns.length === 0 && accounts.length > 0 && (
                    <p className="mb-4 text-xs text-slate-400">
                      Create one and it starts as a draft — nothing sends until you enroll leads and launch it.
                    </p>
                  )}
                </td>
              </tr>
            ) : (
              filtered.map((campaign) => {
                const enrolledPct =
                  campaign.stats.enrolled === 0
                    ? 0
                    : Math.round((campaign.stats.completed / campaign.stats.enrolled) * 100);
                return (
                  <tr key={campaign.id} className="border-b border-slate-100 last:border-0 hover:bg-slate-50/70">
                    <td className="px-4 py-3.5">
                      <Link href={`/campaigns/${campaign.id}`} className="font-semibold text-ink-950 hover:underline">
                        {campaign.name}
                      </Link>
                      <div className="mt-1 flex items-center gap-2">
                        <span className={clsx("inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium", STATUS_STYLES[campaign.status])}>
                          {campaign.status}
                        </span>
                        <span className="text-[11px] text-slate-400">{campaign.steps.length} steps</span>
                      </div>
                    </td>
                    <td className="px-4 py-3.5 text-[13px] text-slate-600">{campaign.linkedin_account_label}</td>
                    <td className="px-4 py-3.5">
                      <p className="text-[12px] text-slate-500">
                        Enrolled <span className="font-semibold text-ink-950">{campaign.stats.enrolled}</span>
                      </p>
                      <div className="mt-1 h-1.5 w-36 overflow-hidden rounded-full bg-slate-100">
                        <div className="h-full rounded-full bg-brand-500" style={{ width: `${enrolledPct}%` }} />
                      </div>
                    </td>
                    <td className="px-4 py-3.5 text-[12.5px]">
                      <p className="text-slate-600">
                        Accepted <span className="font-semibold text-emerald-600">{pct(campaign.stats.acceptance_rate)}</span>
                      </p>
                      <p className="text-slate-600">
                        Replied <span className="font-semibold text-brand-600">{pct(campaign.stats.reply_rate)}</span>
                      </p>
                    </td>
                    <td className="px-4 py-3.5">
                      <Link
                        href={`/campaigns/${campaign.id}/tracking`}
                        title="See every lead's status and history"
                        className="group inline-flex items-center gap-2 rounded-lg border border-brand-200 bg-brand-50 px-3.5 py-2 text-[13px] font-semibold text-brand-700 shadow-sm transition-colors hover:border-brand-600 hover:bg-brand-600 hover:text-white"
                      >
                        <IconTracking className="h-4 w-4" />
                        Track leads
                        <IconArrowRight className="h-3.5 w-3.5 transition-transform group-hover:translate-x-0.5" />
                      </Link>
                      <p className="mt-1 text-[11px] text-slate-400">
                        {campaign.stats.invites_sent} sent · {campaign.stats.accepted} accepted
                      </p>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </>
  );
}

export default function CampaignsPage() {
  const { workspace } = useSession();
  const workspaceId = workspace?.id ?? null;
  const searchParams = useSearchParams();
  const router = useRouter();

  const [pageTab, setPageTab] = useState("campaigns");
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [accounts, setAccounts] = useState<LinkedInAccount[]>([]);
  const [quotas, setQuotas] = useState<QuotaStatus[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [wizardOpen, setWizardOpen] = useState(false);
  const [wizardSteps, setWizardSteps] = useState<StepInput[] | undefined>(undefined);

  // `?new=1` (from Templates / Agency View) opens the wizard immediately; a
  // pending template handoff, if any, seeds its starting sequence.
  useEffect(() => {
    if (searchParams.get("new") !== "1") return;
    try {
      const raw = window.sessionStorage.getItem(TEMPLATE_HANDOFF_KEY);
      if (raw) {
        setWizardSteps(JSON.parse(raw) as StepInput[]);
        window.sessionStorage.removeItem(TEMPLATE_HANDOFF_KEY);
      }
    } catch {
      /* ignore malformed handoff */
    }
    setWizardOpen(true);
  }, [searchParams]);

  const load = useCallback(async () => {
    if (!workspaceId) return;
    try {
      const [nextCampaigns, nextAccounts, nextQuotas] = await Promise.all([
        campaignsApi.list(workspaceId),
        linkedinApi.accounts(workspaceId),
        campaignsApi.quotaStatus(workspaceId),
      ]);
      setCampaigns(nextCampaigns);
      setAccounts(nextAccounts);
      setQuotas(nextQuotas);
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load campaigns");
    } finally {
      setLoading(false);
    }
  }, [workspaceId]);

  useEffect(() => {
    void load();
  }, [load]);

  if (!workspaceId) return <p className="text-sm text-slate-500">Select a workspace.</p>;

  return (
    <div>
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <TabBar tabs={PAGE_TABS} active={pageTab} onChange={setPageTab} />
        {pageTab === "campaigns" && accounts.length > 0 && (
          <button onClick={() => setWizardOpen(true)} className="btn-primary shrink-0">
            Create Campaign
            <IconPlus className="h-4 w-4" />
          </button>
        )}
      </div>

      {error && (
        <p role="alert" className="mb-6 rounded-md border border-state-bad/40 bg-state-bad/10 px-4 py-3 text-sm text-state-bad">
          {error}
        </p>
      )}

      {pageTab === "campaigns" && accounts.length === 0 && !loading && (
        <div className="card mb-6">
          <h2 className="mb-2 font-medium text-slate-900">Connect a LinkedIn account first</h2>
          <p className="mb-4 text-sm text-slate-500">
            A campaign sends from exactly one account, so its pacing and quota are unambiguous.
          </p>
          <Link href="/accounts" className="btn-primary inline-flex">
            Go to accounts
          </Link>
        </div>
      )}

      {pageTab === "campaigns" && <QuotaPanel quotas={quotas} />}

      {pageTab === "campaigns" && (
        <CampaignsTable campaigns={campaigns} loading={loading} accounts={accounts} />
      )}
      {pageTab === "prospects" && <ProspectsTable workspaceId={workspaceId} />}
      {pageTab === "leadlist" && <LeadListTable workspaceId={workspaceId} />}

      {wizardOpen && workspaceId && (
        <CampaignWizard
          workspaceId={workspaceId}
          accounts={accounts}
          initialSteps={wizardSteps}
          onClose={() => {
            setWizardOpen(false);
            setWizardSteps(undefined);
          }}
          onCreated={(campaignId) => {
            setWizardOpen(false);
            setWizardSteps(undefined);
            void load();
            router.push(`/campaigns/${campaignId}`);
          }}
        />
      )}
    </div>
  );
}
