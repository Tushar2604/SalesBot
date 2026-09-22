"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import { useSession } from "@/lib/session";
import { AuthShell } from "@/components/auth/AuthShell";
import { IconArrowRight, IconEye } from "@/components/app/icons";

export default function LoginPage() {
  const router = useRouter();
  const { refresh } = useSession();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await api.login({ email, password });
      await refresh();
      router.push("/dashboard");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not sign in");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthShell
      title="Welcome back"
      switchPrompt="New to SalesBot?"
      switchHref="/signup"
      switchLabel="Create an account"
    >
      <form onSubmit={onSubmit} className="space-y-5">
        <div>
          <label className="mb-1.5 block text-[14px] font-bold text-ink-950" htmlFor="email">
            Email address
          </label>
          <input
            id="email"
            type="email"
            className="w-full rounded-xl border border-slate-200 bg-brand-50/40 px-4 py-3 text-[14.5px] text-ink-950 placeholder:text-slate-400 focus:border-brand-400 focus:outline-none focus:ring-1 focus:ring-brand-400"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoComplete="email"
            required
          />
        </div>

        <div>
          <label className="mb-1.5 block text-[14px] font-bold text-ink-950" htmlFor="password">
            Password
          </label>
          <div className="relative">
            <input
              id="password"
              type={showPassword ? "text" : "password"}
              className="w-full rounded-xl border border-slate-200 bg-brand-50/40 px-4 py-3 pr-11 text-[14.5px] text-ink-950 placeholder:text-slate-400 focus:border-brand-400 focus:outline-none focus:ring-1 focus:ring-brand-400"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              required
            />
            <button
              type="button"
              onClick={() => setShowPassword((v) => !v)}
              className="absolute right-3.5 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
              aria-label={showPassword ? "Hide password" : "Show password"}
            >
              <IconEye className="h-5 w-5" />
            </button>
          </div>
        </div>

        {error && (
          <p role="alert" className="text-sm text-state-bad">
            {error}
          </p>
        )}

        <button
          type="submit"
          className="flex w-full items-center justify-center gap-2 rounded-xl bg-brand-600 py-3.5 text-[15px] font-bold text-white hover:bg-brand-700 disabled:opacity-50"
          disabled={busy}
        >
          {busy ? "Signing in…" : "Sign in"}
          {!busy && <IconArrowRight className="h-4 w-4" />}
        </button>
      </form>
    </AuthShell>
  );
}
