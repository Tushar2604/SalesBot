"use client";

/**
 * Invite acceptance. The token in the URL is the credential, so this page is
 * intentionally reachable without signing in. A password field is shown because
 * the invitee may not have an account yet; the API ignores it if they do.
 */

import { useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import { useSession } from "@/lib/session";

export default function AcceptInvitePage() {
  const params = useParams<{ token: string }>();
  const router = useRouter();
  const { refresh } = useSession();

  const [fullName, setFullName] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await api.acceptInvite({
        token: params.token,
        password: password || undefined,
        full_name: fullName,
      });
      await refresh();
      router.push("/dashboard");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "This invite could not be accepted");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center px-4 py-10">
      <div className="w-full max-w-sm">
        <h1 className="mb-1 text-2xl font-semibold text-ink-950">Join the workspace</h1>
        <p className="mb-6 text-sm text-slate-500">
          Set a password to finish creating your account. Already have one? Leave it blank.
        </p>

        <form onSubmit={onSubmit} className="card space-y-4">
          <div>
            <label className="label" htmlFor="full_name">
              Your name
            </label>
            <input
              id="full_name"
              className="input"
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
            />
          </div>

          <div>
            <label className="label" htmlFor="password">
              Password
            </label>
            <input
              id="password"
              type="password"
              className="input"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="new-password"
            />
            <p className="mt-1.5 text-xs text-slate-500">
              At least 10 characters, with letters and numbers.
            </p>
          </div>

          {error && (
            <p role="alert" className="text-sm text-state-bad">
              {error}
            </p>
          )}

          <button type="submit" className="btn-primary w-full" disabled={busy}>
            {busy ? "Joining…" : "Accept invite"}
          </button>
        </form>
      </div>
    </main>
  );
}
