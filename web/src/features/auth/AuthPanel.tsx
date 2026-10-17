import { useState, type FormEvent } from "react";
import { AlertCircle } from "lucide-react";

import { GoogleIcon } from "@/components/GoogleIcon";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api, ApiError } from "@/lib/api";
import { useApp } from "@/store/app";

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

interface FieldErrors {
  email?: string;
  password?: string;
  form?: string;
}

export function AuthPanel() {
  const { authConfig, setUser } = useApp();
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [errors, setErrors] = useState<FieldErrors>({});
  const [pending, setPending] = useState(false);

  const googleEnabled = authConfig?.google_enabled ?? false;

  const validate = (): FieldErrors => {
    const next: FieldErrors = {};
    if (!EMAIL_RE.test(email.trim())) next.email = "Enter a valid email address.";
    if (mode === "signup" && password.length < 8) {
      next.password = "Use at least 8 characters.";
    }
    if (mode === "login" && password.length === 0) {
      next.password = "Enter your password.";
    }
    return next;
  };

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    const found = validate();
    setErrors(found);
    if (Object.keys(found).length > 0) return;

    setPending(true);
    try {
      const user =
        mode === "login"
          ? await api.login(email.trim(), password)
          : await api.signup(email.trim(), password);
      setUser(user);
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Something went wrong. Try again.";
      setErrors({ form: message });
    } finally {
      setPending(false);
    }
  };

  return (
    <div className="rounded-[var(--radius-card)] border border-border bg-surface p-6 shadow-[var(--shadow-1)]">
      <div className="mb-5 space-y-1">
        <h2 className="text-lg font-semibold tracking-[-0.02em] text-fg">
          {mode === "login" ? "Sign in" : "Create your account"}
        </h2>
        <p className="text-[13px] text-fg-muted">
          {mode === "login"
            ? "Pick up your streak where you left off."
            : "Start logging your #100DaysOfCode today."}
        </p>
      </div>

      {googleEnabled ? (
        <>
          <Button asChild variant="google" size="lg" className="w-full">
            <a href="/auth/google/login">
              <GoogleIcon />
              Continue with Google
            </a>
          </Button>
          <div className="my-5 flex items-center gap-3" aria-hidden="true">
            <span className="h-px flex-1 bg-border" />
            <span className="text-[11px] uppercase tracking-wider text-fg-subtle">or</span>
            <span className="h-px flex-1 bg-border" />
          </div>
        </>
      ) : null}

      <form onSubmit={onSubmit} noValidate className="space-y-4">
        <div className="space-y-1.5">
          <Label htmlFor="email">Email</Label>
          <Input
            id="email"
            name="email"
            type="email"
            autoComplete="email"
            required
            value={email}
            aria-invalid={Boolean(errors.email)}
            aria-describedby={errors.email ? "email-error" : undefined}
            onChange={(e) => setEmail(e.target.value)}
          />
          {errors.email ? (
            <p id="email-error" className="text-[12px] text-danger" role="alert">
              {errors.email}
            </p>
          ) : null}
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="password">Password</Label>
          <Input
            id="password"
            name="password"
            type="password"
            autoComplete={mode === "login" ? "current-password" : "new-password"}
            required
            minLength={mode === "signup" ? 8 : undefined}
            value={password}
            aria-invalid={Boolean(errors.password)}
            aria-describedby={errors.password ? "password-error" : undefined}
            onChange={(e) => setPassword(e.target.value)}
          />
          {errors.password ? (
            <p id="password-error" className="text-[12px] text-danger" role="alert">
              {errors.password}
            </p>
          ) : mode === "signup" ? (
            <p className="text-[12px] text-fg-subtle">At least 8 characters.</p>
          ) : null}
        </div>

        {errors.form ? (
          <div
            role="alert"
            className="flex items-start gap-2 rounded-xl border border-danger/30 bg-danger/10 px-3 py-2.5 text-[13px] text-danger"
          >
            <AlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
            <span>{errors.form}</span>
          </div>
        ) : null}

        <Button type="submit" variant="primary" size="lg" className="w-full" loading={pending}>
          {mode === "login" ? "Sign in" : "Create account"}
        </Button>
      </form>

      <p className="mt-4 text-center text-[13px] text-fg-muted">
        {mode === "login" ? "New here?" : "Already have an account?"}{" "}
        <button
          type="button"
          className="font-medium text-accent transition-colors hover:text-accent-strong"
          onClick={() => {
            setMode(mode === "login" ? "signup" : "login");
            setErrors({});
          }}
        >
          {mode === "login" ? "Create an account" : "Sign in"}
        </button>
      </p>
    </div>
  );
}
