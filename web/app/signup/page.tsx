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
      setError(err instanceof ApiError ? err.message : "Could not create your account. Is the API running?");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthShell
      title="Get started for free"
      switchPrompt="Already registered?"
      switchHref="/login"
      switchLabel="Sign in to your account"
    >
      <form onSubmit={onSubmit} className="space-y-4">
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="label" htmlFor="first_name">
              First Name
            </label>
            <input id="first_name" className="input" value={firstName} onChange={(e) => setFirstName(e.target.value)} required />
          </div>
          <div>
            <label className="label" htmlFor="last_name">
              Last Name
            </label>
            <input id="last_name" className="input" value={lastName} onChange={(e) => setLastName(e.target.value)} required />
          </div>
        </div>

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
          <label className="label" htmlFor="confirm_password">
            Confirm Password
          </label>
          <div className="relative">
            <input
              id="confirm_password"
              type={showConfirm ? "text" : "password"}
              className="input pr-11"
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
          <label className="label" htmlFor="workspace_name">
            Workspace name
          </label>
          <input
            id="workspace_name"
            className="input"
            value={workspaceName}
            onChange={(e) => setWorkspaceName(e.target.value)}
            placeholder="Acme Outbound"
          />
        </div>

        <label className="flex items-start gap-2.5 text-[13.5px] font-medium text-slate-600">
          <input
            type="checkbox"
            checked={agreed}
            onChange={(e) => setAgreed(e.target.checked)}
            className="mt-0.5 h-4 w-4 rounded border-slate-300 text-accent"
          />
          <span>
            I agree to{" "}
            <a href="#faq" className="font-semibold text-accent hover:underline">
              Terms of Service
            </a>{" "}
            and{" "}
            <a href="#faq" className="font-semibold text-accent hover:underline">
              Privacy Policy
            </a>
          </span>
        </label>

        {error && (
          <p role="alert" className="text-sm text-state-bad">
            {error}
          </p>
        )}

        <button type="submit" className="btn-primary h-12 w-full text-[15px]" disabled={busy}>
          {busy ? "Creating…" : "Sign up"}
          {!busy && <IconArrowRight className="h-4 w-4" />}
        </button>
      </form>
    </AuthShell>
  );
}
