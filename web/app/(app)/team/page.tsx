"use client";

/** Team management: members, roles, invites, and the workspace kill switch. */

import { useCallback, useEffect, useState } from "react";
import { api, ApiError, type Invite, type Member, type WorkspaceRole } from "@/lib/api";
import { hasRole, useSession } from "@/lib/session";

const ROLES: WorkspaceRole[] = ["member", "admin", "owner"];

export default function TeamPage() {
  const { workspace, role, me, refresh } = useSession();
  const workspaceId = workspace?.id ?? null;

  const [members, setMembers] = useState<Member[]>([]);
  const [invites, setInvites] = useState<Invite[]>([]);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState<WorkspaceRole>("member");
  const [lastInviteUrl, setLastInviteUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const isAdmin = hasRole(role, "admin");

  const load = useCallback(async () => {
    if (!workspaceId) return;
    try {
      setMembers(await api.members(workspaceId));
      if (isAdmin) setInvites(await api.invites(workspaceId));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load the team");
    }
  }, [workspaceId, isAdmin]);

  useEffect(() => {
    void load();
  }, [load]);

  async function run(action: () => Promise<void>) {
    setError(null);
    setBusy(true);
    try {
      await action();
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  if (!workspaceId) return <p className="text-sm text-slate-500">Select a workspace.</p>;

  return (
    <div className="mx-auto max-w-4xl">
      <h1 className="mb-8 text-2xl font-semibold text-ink-950">Team</h1>

      {error && (
        <p
          role="alert"
          className="mb-6 rounded-md border border-state-bad/40 bg-state-bad/10 px-4 py-3 text-sm text-state-bad"
        >
          {error}
        </p>
      )}

      {isAdmin && (
        <section className="card mb-6">
          <h2 className="mb-1 font-medium text-slate-900">Outreach kill switch</h2>
          <p className="mb-4 text-sm text-slate-500">
            Pausing stops every queued LinkedIn and email action for this workspace immediately.
            Use it the moment an account looks at risk.
          </p>
          <button
            className={workspace?.outreach_paused ? "btn-primary" : "btn-danger"}
            disabled={busy}
            onClick={() =>
              void run(async () => {
                await api.updateWorkspace(workspaceId, {
                  outreach_paused: !workspace?.outreach_paused,
                });
                await refresh();
              })
            }
          >
            {workspace?.outreach_paused ? "Resume outreach" : "Pause all outreach"}
          </button>
        </section>
      )}

      <section className="card mb-6">
        <h2 className="mb-4 font-medium text-slate-900">Members</h2>
        <ul className="divide-y divide-slate-200">
          {members.map((member) => {
            const isSelf = member.user.id === me?.user.id;
            return (
              <li key={member.id} className="flex flex-wrap items-center gap-3 py-3">
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm text-slate-800">
                    {member.user.full_name || member.user.email}
                    {isSelf && <span className="ml-2 badge">you</span>}
                  </p>
                  <p className="truncate text-xs text-slate-500">{member.user.email}</p>
                </div>

                {isAdmin ? (
                  <select
                    className="input w-32"
                    value={member.role}
                    disabled={busy}
                    aria-label={`Role for ${member.user.email}`}
                    onChange={(e) =>
                      void run(async () => {
                        await api.updateMemberRole(
                          workspaceId,
                          member.id,
                          e.target.value as WorkspaceRole,
                        );
                      })
                    }
                  >
                    {ROLES.filter((r) => r !== "owner" || role === "owner").map((r) => (
                      <option key={r} value={r}>
                        {r}
                      </option>
                    ))}
                  </select>
                ) : (
                  <span className="badge">{member.role}</span>
                )}

                {isAdmin && !isSelf && (
                  <button
                    className="btn-ghost"
                    disabled={busy}
                    onClick={() => void run(() => api.removeMember(workspaceId, member.id))}
                  >
                    Remove
                  </button>
                )}
              </li>
            );
          })}
        </ul>
      </section>

      {isAdmin && (
        <section className="card">
          <h2 className="mb-4 font-medium text-slate-900">Invite someone</h2>
          <form
            className="flex flex-wrap items-end gap-3"
            onSubmit={(event) => {
              event.preventDefault();
              void run(async () => {
                const created = await api.createInvite(workspaceId, inviteEmail, inviteRole);
                setLastInviteUrl(created.invite_url);
                setInviteEmail("");
              });
            }}
          >
            <div className="min-w-56 flex-1">
              <label className="label" htmlFor="invite-email">
                Email
              </label>
              <input
                id="invite-email"
                type="email"
                className="input"
                value={inviteEmail}
                onChange={(e) => setInviteEmail(e.target.value)}
                required
              />
            </div>
            <div>
              <label className="label" htmlFor="invite-role">
                Role
              </label>
              <select
                id="invite-role"
                className="input w-32"
                value={inviteRole}
                onChange={(e) => setInviteRole(e.target.value as WorkspaceRole)}
              >
                {ROLES.filter((r) => r !== "owner" || role === "owner").map((r) => (
                  <option key={r} value={r}>
                    {r}
                  </option>
                ))}
              </select>
            </div>
            <button type="submit" className="btn-primary" disabled={busy}>
              Send invite
            </button>
          </form>

          {lastInviteUrl && (
            <div className="mt-4 rounded-md border border-slate-200 bg-slate-50 p-3">
              <p className="mb-1 text-xs text-slate-500">
                Share this link. It is shown once and cannot be retrieved later.
              </p>
              <code className="break-all text-xs text-accent">{lastInviteUrl}</code>
            </div>
          )}

          {invites.length > 0 && (
            <ul className="mt-6 divide-y divide-slate-200 border-t border-slate-200">
              {invites.map((invite) => (
                <li key={invite.id} className="flex items-center gap-3 py-3">
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm text-slate-800">{invite.email}</p>
                    <p className="text-xs text-slate-500">
                      {invite.role} · {invite.status}
                    </p>
                  </div>
                  {invite.status === "pending" && (
                    <button
                      className="btn-ghost"
                      disabled={busy}
                      onClick={() => void run(() => api.revokeInvite(workspaceId, invite.id))}
                    >
                      Revoke
                    </button>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>
      )}
    </div>
  );
}
