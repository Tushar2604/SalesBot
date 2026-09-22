"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import { useSession } from "@/lib/session";
import { AuthShell } from "@/components/auth/AuthShell";
import { IconArrowRight, IconEye } from "@/components/app/icons";

export default function SignupPage() {
  const router = useRouter();
  const { refresh } = useSession();
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [workspaceName, setWorkspaceName] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [agreed, setAgreed] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);

    if (password !== confirmPassword) {
      setError("Passwords do not match");
      return;
    }
    if (!agreed) {
      setError("Please agree to the Terms of Service and Privacy Policy");
      return;
    }

    setBusy(true);
    try {
      await api.signup({
        full_name: `${firstName} ${lastName}`.trim(),
        email,
        password,
        workspace_name: workspaceName,
      });
      await refresh();
      router.push("/dashboard");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not create your account");
    } finally {
      setBusy(false);
    }
  }

  const fieldClass =
    "w-full rounded-xl border border-slate-200 bg-brand-50/40 px-4 py-3 text-[14.5px] text-ink-950 placeholder:text-slate-400 focus:border-brand-400 focus:outline-none focus:ring-1 focus:ring-brand-400";
  const labelClass = "mb-1.5 block text-[14px] font-bold text-ink-950";

  return (
    <AuthShell
      title="Get started for free"
      switchPrompt="Already registered?"
      switchHref="/login"
      switchLabel="Sign in to your account"
    >
      <form onSubmit={onSubmit} className="space-y-5">
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className={labelClass} htmlFor="first_name">
              First Name
            </label>
            <input
              id="first_name"
              className={fieldClass}
              value={firstName}
              onChange={(e) => setFirstName(e.target.value)}
              required
            />
          </div>
          <div>
            <label className={labelClass} htmlFor="last_name">
              Last Name
            </label>
            <input
              id="last_name"
              className={fieldClass}
              value={lastName}
              onChange={(e) => setLastName(e.target.value)}
              required
            />
          </div>
        </div>

        <div>
          <label className={labelClass} htmlFor="email">
            Email address
          </label>
          <input
            id="email"
            type="email"
            className={fieldClass}
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoComplete="email"
            required
          />
        </div>

        <div>
          <label className={labelClass} htmlFor="password">
            Password
          </label>
          <div className="relative">
            <input
              id="password"
              type={showPassword ? "text" : "password"}
              className={`${fieldClass} pr-11`}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="new-password"
              minLength={10}
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
          <p className="mt-1.5 text-xs text-slate-500">At least 10 characters, with letters and numbers.</p>
        </div>

        <div>
          <label className={labelClass} htmlFor="confirm_password">
            Confirm Password
          </label>
          <div className="relative">
            <input
              id="confirm_password"
              type={showConfirm ? "text" : "password"}
              className={`${fieldClass} pr-11`}
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              autoComplete="new-password"
              required
            />
            <button
              type="button"
              onClick={() => setShowConfirm((v) => !v)}
              className="absolute right-3.5 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
              aria-label={showConfirm ? "Hide password" : "Show password"}
            >
              <IconEye className="h-5 w-5" />
            </button>
          </div>
        </div>

        <div>
          <label className={labelClass} htmlFor="workspace_name">
            Workspace name
          </label>
          <input
            id="workspace_name"
            className={fieldClass}
            value={workspaceName}
            onChange={(e) => setWorkspaceName(e.target.value)}
            placeholder="Acme Outbound"
          />
        </div>

        <label className="flex items-center gap-2.5 text-[13.5px] font-medium text-slate-600">
          <input
            type="checkbox"
            checked={agreed}
            onChange={(e) => setAgreed(e.target.checked)}
            className="h-4 w-4 rounded border-slate-300 text-brand-600"
          />
          I agree to{" "}
          <a href="#" className="font-semibold text-brand-600 hover:underline">
            Terms of Service
          </a>{" "}
          and{" "}
          <a href="#" className="font-semibold text-brand-600 hover:underline">
            Privacy Policy
          </a>
        </label>

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
          {busy ? "Creating…" : "Sign up"}
          {!busy && <IconArrowRight className="h-4 w-4" />}
        </button>
      </form>
    </AuthShell>
  );
}
