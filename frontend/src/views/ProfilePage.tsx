"use client";



import { useCallback, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { CheckCircle2, AlertCircle, User as UserIcon, Save } from "lucide-react";
import AppLayout from "@/components/AppLayout";
import { getCurrentUser, updateProfile, isAuthenticated, AuthError, type AuthUser } from "@/lib/auth/auth-client";
import { saveProfile, getStoredProfile } from "@/lib/stores/farmStore";

// All 28 Indian states + 8 union territories, alphabetical.
const states = [
  "Andaman and Nicobar Islands", "Andhra Pradesh", "Arunachal Pradesh", "Assam",
  "Bihar", "Chandigarh", "Chhattisgarh",
  "Dadra and Nagar Haveli and Daman and Diu", "Delhi", "Goa", "Gujarat",
  "Haryana", "Himachal Pradesh", "Jammu and Kashmir", "Jharkhand", "Karnataka",
  "Kerala", "Ladakh", "Lakshadweep", "Madhya Pradesh", "Maharashtra",
  "Manipur", "Meghalaya", "Mizoram", "Nagaland", "Odisha", "Puducherry",
  "Punjab", "Rajasthan", "Sikkim", "Tamil Nadu", "Telangana", "Tripura",
  "Uttar Pradesh", "Uttarakhand", "West Bengal",
];

export default function ProfilePage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const completingSignup = searchParams.get("complete") === "1";

  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [state, setState] = useState("Maharashtra");
  const [location, setLocation] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [success, setSuccess] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const loadUser = useCallback(async () => {
    if (!isAuthenticated()) {
      router.push("/login");
      return;
    }
    setLoadError(false);
    const current = await getCurrentUser();
    if (!current) {
      // Signed in (we have a token) but the request failed — a network
      // hiccup or an expired/invalid token, not necessarily "not signed
      // in". Show a retry instead of silently bouncing to /login.
      setLoadError(true);
      setLoading(false);
      return;
    }
    setUser(current);
    setName(current.full_name ?? "");
    setPhone(current.phone ?? "");
    setState(current.state ?? "Maharashtra");
    setLocation(current.location ?? "");
    setLoading(false);
  }, [router]);

  useEffect(() => {
    loadUser();
  }, [loadUser]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSuccess(false);
    setSubmitting(true);
    try {
      const updated = await updateProfile({
        full_name: name.trim() || undefined,
        phone: phone.trim() || undefined,
        state: state || undefined,
        location: location.trim() || undefined,
      });
      setUser(updated);
      // Keep the local demo/farm-store profile (used for dashboard greeting,
      // sidebar, etc.) in sync with the backend profile.
      const existing = getStoredProfile();
      saveProfile({ ...existing, name: name.trim() || existing.name, phone: phone.trim(), state, location: location.trim() });
      setSuccess(true);
    } catch (err) {
      setError(err instanceof AuthError ? err.message : "Could not save your profile. Please try again.");
    } finally {
      setSubmitting(false);
    }
  }

  if (loadError) {
    return (
      <AppLayout>
        <div className="max-w-sm mx-auto p-12 text-center space-y-3">
          <AlertCircle className="w-8 h-8 text-red-500 mx-auto" />
          <p className="text-farm-dark font-medium">Couldn't load your profile.</p>
          <p className="text-farm-muted text-sm">Check your connection and try again.</p>
          <button
            onClick={() => { setLoading(true); loadUser(); }}
            className="inline-flex items-center gap-2 bg-farm-green text-white px-4 py-2 rounded-lg text-sm font-semibold hover:bg-farm-green-dark transition-all"
          >
            Retry
          </button>
        </div>
      </AppLayout>
    );
  }

  if (loading || !user) {
    return (
      <AppLayout>
        <div className="p-12 text-center text-farm-muted">Loading profile…</div>
      </AppLayout>
    );
  }

  return (
    <AppLayout>
      <div className="max-w-lg mx-auto space-y-6 pb-16">
        <div>
          <h1 className="text-2xl font-bold text-farm-dark flex items-center gap-2">
            <UserIcon className="w-6 h-6 text-farm-green" /> Your Profile
          </h1>
          <p className="text-farm-muted text-sm mt-1">
            Manage your account details. Your email stays fixed as your sign-in id.
          </p>
        </div>

        {completingSignup && !user.profile_complete && (
          <div className="flex items-start gap-2 text-sm text-amber-800 bg-amber-50 border border-amber-200 rounded-lg px-4 py-3">
            <AlertCircle className="w-4 h-4 flex-shrink-0 mt-0.5" />
            <span>
              Just a couple more details to finish setting up your account — mobile number and
              state are required before you can register a farm.
            </span>
          </div>
        )}

        <div className="bg-white rounded-2xl shadow-card border border-farm-border-color p-6 sm:p-8">
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-farm-dark mb-1.5" htmlFor="profile-email">
                Email
              </label>
              <input
                id="profile-email"
                type="email"
                value={user.email}
                disabled
                className="w-full px-4 py-2.5 border border-farm-border-color rounded-lg text-sm bg-farm-gray text-farm-muted cursor-not-allowed"
              />
              <p className="text-xs text-farm-muted mt-1">Email can't be changed — it's tied to your account.</p>
            </div>

            <div>
              <label className="block text-sm font-medium text-farm-dark mb-1.5" htmlFor="profile-name">
                Full Name
              </label>
              <input
                id="profile-name"
                type="text"
                required
                disabled={submitting}
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Your name"
                className="w-full px-4 py-2.5 border border-farm-border-color rounded-lg text-sm focus:outline-none focus:border-farm-green focus:ring-1 focus:ring-farm-green disabled:bg-farm-gray disabled:text-farm-muted disabled:cursor-not-allowed"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-farm-dark mb-1.5" htmlFor="profile-phone">
                Mobile Number
              </label>
              <div className="flex">
                <span className="inline-flex items-center px-3 bg-farm-gray border border-r-0 border-farm-border-color rounded-l-lg text-farm-muted text-sm font-medium">
                  +91
                </span>
                <input
                  id="profile-phone"
                  type="tel"
                  inputMode="numeric"
                  required
                  disabled={submitting}
                  pattern="\d{10}"
                  maxLength={10}
                  title="Enter a 10-digit mobile number"
                  value={phone}
                  onChange={(e) => setPhone(e.target.value.replace(/\D/g, "").slice(0, 10))}
                  placeholder="9876543210"
                  className="flex-1 px-4 py-2.5 border border-farm-border-color rounded-r-lg text-sm focus:outline-none focus:border-farm-green focus:ring-1 focus:ring-farm-green bg-white disabled:bg-farm-gray disabled:text-farm-muted disabled:cursor-not-allowed"
                />
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-farm-dark mb-1.5" htmlFor="profile-state">
                State
              </label>
              <select
                id="profile-state"
                required
                disabled={submitting}
                value={state}
                onChange={(e) => setState(e.target.value)}
                className="w-full px-3 py-2.5 border border-farm-border-color rounded-lg text-sm focus:outline-none focus:border-farm-green focus:ring-1 focus:ring-farm-green bg-white text-farm-dark font-medium disabled:bg-farm-gray disabled:text-farm-muted disabled:cursor-not-allowed"
              >
                {states.map((s) => (
                  <option key={s} value={s}>{s}</option>
                ))}
              </select>
            </div>

            <div>
              <label className="block text-sm font-medium text-farm-dark mb-1.5" htmlFor="profile-location">
                District / Village
              </label>
              <input
                id="profile-location"
                type="text"
                disabled={submitting}
                value={location}
                onChange={(e) => setLocation(e.target.value)}
                placeholder="e.g. Nashik"
                className="w-full px-4 py-2.5 border border-farm-border-color rounded-lg text-sm focus:outline-none focus:border-farm-green focus:ring-1 focus:ring-farm-green disabled:bg-farm-gray disabled:text-farm-muted disabled:cursor-not-allowed"
              />
            </div>

            {error && (
              <div className="flex items-start gap-2 text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
                <AlertCircle className="w-4 h-4 flex-shrink-0 mt-0.5" />
                <span>{error}</span>
              </div>
            )}

            {success && (
              <div className="flex items-start gap-2 text-sm text-green-700 bg-green-50 border border-green-200 rounded-lg px-3 py-2">
                <CheckCircle2 className="w-4 h-4 flex-shrink-0 mt-0.5" />
                <span>Profile saved.</span>
              </div>
            )}

            <button
              type="submit"
              disabled={submitting}
              className="w-full flex items-center justify-center gap-2 bg-farm-green text-white py-3 rounded-xl font-semibold hover:bg-farm-green-dark transition-all duration-150 shadow-sm hover:shadow-md disabled:opacity-60 disabled:cursor-not-allowed"
            >
              <Save className="w-4 h-4" /> {submitting ? "Saving..." : "Save Profile"}
            </button>
          </form>
        </div>
      </div>
    </AppLayout>
  );
}
