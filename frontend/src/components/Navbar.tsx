"use client";

import Link from "next/link";
import Image from "next/image";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Menu, X, LogIn, LogOut, LayoutDashboard, Globe, ChevronDown } from "lucide-react";
import { useLanguage, type Language } from "@/lib/LanguageContext";
import { isAuthenticated, logout } from "@/lib/auth/auth-client";

const LANGUAGES: { code: Language; label: string }[] = [
  { code: "en", label: "English" },
  { code: "bn", label: "বাংলা" },
  { code: "hi", label: "हिंदी" },
];

export default function Navbar() {
  const pathname = usePathname();
  const router = useRouter();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [authed, setAuthed] = useState(false);
  const { lang: currentLang, setLang, t } = useLanguage();

  useEffect(() => {
    setAuthed(isAuthenticated());
  }, [pathname]);

  function handleSignOut() {
    logout();
    setAuthed(false);
    setMobileOpen(false);
    router.push("/login");
  }

  const navLinks = [
    { href: "/", label: t.navHome },
    { href: "/features", label: t.navFeatures },
    { href: "/weather", label: t.navWeather },
    { href: "/help", label: t.navHelp },
  ];

  return (
    <nav className="fixed top-0 left-0 right-0 z-50 bg-white/95 backdrop-blur-md border-b border-farm-border-color shadow-[0_1px_8px_rgba(45,122,58,0.07)]">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16">
          {/* Left: Logo & Quick Yellow Login */}
          <div className="flex items-center gap-3">
            <Link href="/" onClick={() => setMobileOpen(false)} className="flex items-center flex-shrink-0 group" title="Return to FasalSetu Home">
              <Image src="/logo.webp" alt="FasalSetu" width={132} height={45} className="h-9 w-auto group-hover:scale-105 transition-transform" priority />
            </Link>

            {/* Left-side Login / Sign out button */}
            {authed ? (
              <button
                onClick={handleSignOut}
                className="hidden sm:inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold bg-farm-gray hover:bg-gray-200 text-farm-dark transition-all duration-150 shadow-xs border border-farm-border-color"
              >
                <LogOut className="w-3.5 h-3.5" />
                Sign out
              </button>
            ) : (
              <Link
                href="/login"
                className="hidden sm:inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold bg-amber-400 hover:bg-amber-500 text-farm-dark transition-all duration-150 shadow-xs border border-amber-500/20"
              >
                <LogIn className="w-3.5 h-3.5" />
                {t.navLogin}
              </Link>
            )}
          </div>

          {/* Desktop Nav Links */}
          <div className="hidden lg:flex items-center gap-1">
            {navLinks.map(({ href, label }) => (
              <Link
                key={href}
                href={href}
                className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-all duration-150 ${
                  pathname === href
                    ? "bg-farm-green text-white"
                    : "text-farm-muted hover:text-farm-green hover:bg-farm-green-light"
                }`}
              >
                {label}
              </Link>
            ))}
          </div>

          {/* Right Actions: Dashboard, Ask KrishiBot, Minimal Scrollable Language Selector */}
          <div className="hidden md:flex items-center gap-2.5">
            {/* Dashboard Link */}
            <Link
              href="/dashboard"
              className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-sm font-semibold bg-farm-green-light text-farm-green hover:bg-farm-green/20 transition-all duration-150"
            >
              <LayoutDashboard className="w-3.5 h-3.5" />
              {t.navDashboard}
            </Link>

            {/* Minimal Dropdown / Scrollable Language Selector */}
            <div className="relative inline-flex items-center">
              <div className="relative flex items-center">
                <Globe className="w-3.5 h-3.5 text-farm-muted absolute left-2.5 pointer-events-none" />
                <select
                  aria-label="Select language"
                  value={currentLang}
                  onChange={(e) => setLang(e.target.value as Language)}
                  className="appearance-none bg-farm-gray hover:bg-gray-100 border border-farm-border-color text-xs font-semibold text-farm-dark pl-7 pr-6 py-1.5 rounded-lg cursor-pointer focus:outline-none focus:border-farm-green transition-all shadow-xs"
                >
                  {LANGUAGES.map((l) => (
                    <option key={l.code} value={l.code}>
                      {l.label}
                    </option>
                  ))}
                </select>
                <ChevronDown className="w-3 h-3 text-farm-muted absolute right-2 pointer-events-none" />
              </div>
            </div>
          </div>

          {/* Mobile toggle */}
          <div className="flex items-center gap-2 lg:hidden">
            {/* Mobile quick login / sign out */}
            {authed ? (
              <button
                onClick={handleSignOut}
                className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-bold bg-farm-gray text-farm-dark"
              >
                <LogOut className="w-3 h-3" />
                Sign out
              </button>
            ) : (
              <Link
                href="/login"
                className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-bold bg-amber-400 text-farm-dark"
              >
                <LogIn className="w-3 h-3" />
                {t.navLogin}
              </Link>
            )}

            <button
              className="p-2 rounded-lg text-farm-dark hover:bg-farm-green-light transition-colors"
              onClick={() => setMobileOpen(!mobileOpen)}
              aria-label="Toggle menu"
            >
              {mobileOpen ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
            </button>
          </div>
        </div>
      </div>

      {/* Mobile Menu */}
      {mobileOpen && (
        <div className="lg:hidden bg-white border-t border-farm-border-color px-4 py-4 space-y-2 shadow-lg">
          {/* Mobile Language Selector Dropdown */}
          <div className="flex items-center justify-between pb-2 border-b border-farm-border-color">
            <span className="text-xs font-semibold text-farm-muted uppercase tracking-wider flex items-center gap-1">
              <Globe className="w-3 h-3" /> Language:
            </span>
            <div className="relative">
              <select
                value={currentLang}
                onChange={(e) => setLang(e.target.value as Language)}
                className="appearance-none bg-farm-gray border border-farm-border-color text-xs font-semibold text-farm-dark pl-3 pr-6 py-1.5 rounded-md cursor-pointer focus:outline-none focus:border-farm-green"
              >
                {LANGUAGES.map((l) => (
                  <option key={l.code} value={l.code}>
                    {l.label}
                  </option>
                ))}
              </select>
              <ChevronDown className="w-3 h-3 text-farm-muted absolute right-1.5 top-1/2 -translate-y-1/2 pointer-events-none" />
            </div>
          </div>

          {navLinks.map(({ href, label }) => (
            <Link
              key={href}
              href={href}
              onClick={() => setMobileOpen(false)}
              className={`block px-4 py-2.5 rounded-lg text-sm font-medium transition-all ${
                pathname === href
                  ? "bg-farm-green text-white"
                  : "text-farm-dark hover:bg-farm-green-light hover:text-farm-green"
              }`}
            >
              {label}
            </Link>
          ))}

          {/* Mobile Auth & App Links */}
          <div className="pt-3 border-t border-farm-border-color grid grid-cols-2 gap-2">
            {authed ? (
              <button
                onClick={handleSignOut}
                className="flex items-center justify-center gap-1.5 py-2.5 text-sm font-bold bg-farm-gray text-farm-dark rounded-lg hover:bg-gray-200 transition-all text-center shadow-xs"
              >
                <LogOut className="w-4 h-4" /> Sign out
              </button>
            ) : (
              <Link
                href="/login"
                onClick={() => setMobileOpen(false)}
                className="flex items-center justify-center gap-1.5 py-2.5 text-sm font-bold bg-amber-400 text-farm-dark rounded-lg hover:bg-amber-500 transition-all text-center shadow-xs"
              >
                <LogIn className="w-4 h-4" /> {t.navLogin}
              </Link>
            )}
            <Link
              href="/dashboard"
              onClick={() => setMobileOpen(false)}
              className="flex items-center justify-center gap-1.5 py-2.5 text-sm font-semibold bg-farm-green-light text-farm-green rounded-lg hover:bg-farm-green/20 transition-all text-center"
            >
              <LayoutDashboard className="w-4 h-4" /> {t.navDashboard}
            </Link>
          </div>


        </div>
      )}
    </nav>
  );
}
