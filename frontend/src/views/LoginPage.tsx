"use client";



import { useCallback, useEffect, useState } from "react";
import Image from "next/image";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowRight, Globe, AlertCircle } from "lucide-react";
import { login, getCurrentUser, AuthError } from "@/lib/auth/auth-client";
import GoogleSignInButton from "@/components/GoogleSignInButton";

const languages = [
  { code: "en", label: "English" },
  { code: "bn", label: "বাংলা" },
  { code: "hi", label: "हिंदी" },
];

const GOOGLE_ENABLED = Boolean(process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID);

export default function LoginPage() {
  const router = useRouter();
  const [lang, setLang] = useState("en");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  // Set when authorizedFetch ended an expired session (/login?expired=1).
  // Read in an effect rather than via useSearchParams so this page doesn't
  // need a Suspense boundary.
  const [sessionExpired, setSessionExpired] = useState(false);

  useEffect(() => {
    setSessionExpired(new URLSearchParams(window.location.search).get("expired") === "1");
  }, []);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await login(email.trim(), password);
      router.push("/dashboard");
    } catch (err) {
      setError(err instanceof AuthError ? err.message : "Something went wrong. Please try again.");
      setSubmitting(false);
    }
  }

  const handleGoogleSuccess = useCallback(async () => {
    const user = await getCurrentUser();
    router.push(user && !user.profile_complete ? "/profile?complete=1" : "/dashboard");
  }, [router]);

  const handleGoogleError = useCallback((message: string) => {
    setError(message);
  }, []);

  return (
    <div className="min-h-screen relative flex items-center justify-center p-4 overflow-hidden" data-theme="light">
      {/* Background: a farmer using FasalSetu in the field, with a frosted-glass card floating over it */}
      <Image
        src="/images/field_satellite.jpg"
        alt="Satellite-style aerial view of patchwork farmland"
        fill
        priority
        className="object-cover"
      />
      <div className="absolute inset-0 bg-gradient-to-b from-farm-dark/25 via-transparent to-farm-dark/40" />

      <div className="relative z-10 w-full max-w-sm">
        {/* Logo */}
        <Link href="/" className="flex justify-center mb-6">
          <div className="bg-white/90 backdrop-blur-sm rounded-xl px-4 py-2 shadow-card">
            <Image src="/logo.webp" alt="FasalSetu" width={132} height={45} className="h-10 w-auto" priority />
          </div>
        </Link>

        <div className="bg-white/60 backdrop-blur-2xl rounded-2xl shadow-2xl border border-white/40 p-8">
          {/* Language Switcher */}
          <div className="flex items-center justify-between mb-5 pb-3 border-b border-farm-border-color">
            <span className="text-xs text-farm-muted flex items-center gap-1 font-medium">
              <Globe className="w-3 h-3" /> Language:
            </span>
            <div className="flex gap-1">
              {languages.map((l) => (
                <button
                  key={l.code}
                  type="button"
                  onClick={() => setLang(l.code)}
                  className={`text-xs px-2 py-0.5 rounded-md font-medium transition-all ${lang === l.code ? "bg-farm-green text-white" : "text-farm-muted hover:text-farm-dark bg-farm-gray"
                    }`}
                >
                  {l.label}
                </button>
              ))}
            </div>
          </div>

          <h1 className="text-2xl font-bold text-farm-dark mb-1">
            {lang === "bn" ? "স্বাগতম" : lang === "hi" ? "वापसी पर स्वागत" : "Welcome back"}
          </h1>
          <p className="text-farm-muted text-sm mb-6">
            {lang === "bn"
              ? "আপনার কৃষি ড্যাশবোর্ডে সাইন ইন করুন"
              : lang === "hi"
                ? "अपने किसान डैशबोर्ड में साइन इन करें"
                : "Sign in to your farming dashboard"}
          </p>

          <form onSubmit={handleSubmit} className="space-y-4">
            {sessionExpired && !error && (
              <div className="flex items-start gap-2 text-sm text-amber-800 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
                <AlertCircle className="w-4 h-4 flex-shrink-0 mt-0.5" />
                <span>Your session has expired. Please sign in again.</span>
              </div>
            )}

            <div>
              <label className="block text-sm font-medium text-farm-dark mb-1.5" htmlFor="email">
                Email
              </label>
              <input
                id="email"
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@example.com"
                className="w-full px-4 py-2.5 border border-farm-border-color rounded-lg text-sm focus:outline-none focus:border-farm-green focus:ring-1 focus:ring-farm-green bg-white"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-farm-dark mb-1.5" htmlFor="password">
                Password
              </label>
              <input
                id="password"
                type="password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                className="w-full px-4 py-2.5 border border-farm-border-color rounded-lg text-sm focus:outline-none focus:border-farm-green focus:ring-1 focus:ring-farm-green"
              />
            </div>

            {error && (
              <div className="flex items-start gap-2 text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
                <AlertCircle className="w-4 h-4 flex-shrink-0 mt-0.5" />
                <span>{error}</span>
              </div>
            )}

            <button
              type="submit"
              disabled={submitting}
              className="w-full flex items-center justify-center gap-2 bg-farm-green text-white py-3 rounded-xl font-semibold hover:bg-farm-green-dark transition-all duration-150 group shadow-sm hover:shadow-md disabled:opacity-60 disabled:cursor-not-allowed"
            >
              {submitting ? "Signing in..." : "Sign In to Dashboard"}
              <ArrowRight className="w-4 h-4 group-hover:translate-x-1 transition-transform" />
            </button>
          </form>

          {GOOGLE_ENABLED && (
            <>
              <div className="flex items-center gap-3 my-5">
                <div className="flex-1 h-px bg-farm-border-color" />
                <span className="text-xs text-farm-muted font-medium">OR</span>
                <div className="flex-1 h-px bg-farm-border-color" />
              </div>

              <GoogleSignInButton onSuccess={handleGoogleSuccess} onError={handleGoogleError} />
            </>
          )}
        </div>

        <p className="text-center text-sm text-white/90 drop-shadow-sm mt-6">
          New to FasalSetu?{" "}
          <Link href="/register" className="text-amber-300 font-semibold hover:text-amber-200 hover:underline">
            Create account
          </Link>
        </p>
      </div>
    </div>
  );
}
