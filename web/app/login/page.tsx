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
  const [remember, setRemember] = useState(true);
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
      setError(err instanceof ApiError ? err.message : "Could not sign in. Is the API running?");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthShell
      title="Sign in to your account"
      switchPrompt="Don't have an account?"
      switchHref="/signup"
      switchLabel="Sign up for a free trial"
    >
      <form onSubmit={onSubmit} className="space-y-5">
        <div>
          <label className="label" htmlFor="email">
            Email address
          </label>
          <input
            id="email"
            type="email"
            className="input"
            placeholder="Enter your email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoComplete="email"
            required
          />
        </div>

        <div>
          <label className="label" htmlFor="password">
            Password
          </label>
          <div className="relative">
            <input
              id="password"
              type={showPassword ? "text" : "password"}
              className="input pr-11"
              placeholder="Enter your password"
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

        <div className="flex items-center justify-between text-[13.5px]">
          <label className="flex items-center gap-2 font-medium text-ink-950">
            <input
              type="checkbox"
              checked={remember}
              onChange={(e) => setRemember(e.target.checked)}
              className="h-4 w-4 rounded border-slate-300 text-accent"
            />
            Remember me
          </label>
          <span className="text-slate-400">Forgot password?</span>
        </div>

        {error && (
          <p role="alert" className="text-sm text-state-bad">
            {error}
          </p>
        )}

        <button type="submit" className="btn-primary h-12 w-full text-[15px]" disabled={busy}>
          {busy ? "Signing in…" : "Sign in"}
          {!busy && <IconArrowRight className="h-4 w-4" />}
        </button>
      </form>
    </AuthShell>
  );
}
