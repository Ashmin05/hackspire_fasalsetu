"use client";



import Image from "next/image";
import Link from "next/link";
import { useEffect, useState } from "react";
import Navbar from "@/components/Navbar";
import Footer from "@/components/Footer";
import { ArrowRight, MapPin, Satellite, CloudRain, Brain, TrendingUp, Wheat, ChevronRight, LogIn, LayoutDashboard } from "lucide-react";
import { useLanguage } from "@/lib/LanguageContext";
import { isAuthenticated } from "@/lib/auth/auth-client";

export default function HomePage() {
  const { t } = useLanguage();
  const [authed, setAuthed] = useState(false);

  useEffect(() => {
    setAuthed(isAuthenticated());
  }, []);

  const howItWorks = [
    { step: "01", title: t.step1Title, desc: t.step1Desc, icon: MapPin },
    { step: "02", title: t.step2Title, desc: t.step2Desc, icon: Satellite },
    { step: "03", title: t.step3Title, desc: t.step3Desc, icon: Brain },
    { step: "04", title: t.step4Title, desc: t.step4Desc, icon: TrendingUp },
  ];

  const features = [
    { title: t.featFieldWatchTitle, desc: t.featFieldWatchDesc, icon: MapPin, color: "bg-emerald-50 text-emerald-600", href: "/satellite" },
    { title: t.featSoilHealthTitle, desc: t.featSoilHealthDesc, icon: Wheat, color: "bg-amber-50 text-amber-600", href: "/features" },
    { title: t.featRainWeatherTitle, desc: t.featRainWeatherDesc, icon: CloudRain, color: "bg-sky-50 text-sky-600", href: "/weather" },
    { title: t.featKrishiBotTitle, desc: t.featKrishiBotDesc, icon: Brain, color: "bg-purple-50 text-purple-600", href: "/ai-chat" },
  ];

  const fieldViews = [
    {
      label: t.viewFromAbove,
      desc: t.viewFromAboveDesc,
      image: "/images/field_satellite.jpg",
      tag: "Satellite",
    },
    {
      label: t.viewCloseup,
      desc: t.viewCloseupDesc,
      image: "/images/field_closeup.jpg",
      tag: "Crop Health",
    },
    {
      label: t.viewOnGround,
      desc: t.viewOnGroundDesc,
      image: "/images/field_farmer.jpg",
      tag: "Soil",
    },
    {
      label: t.viewWhenRains,
      desc: t.viewWhenRainsDesc,
      image: "/images/field_rain.jpg",
      tag: "Weather",
    },
  ];

  const crops = [
    t.cropRice,
    t.cropWheat,
    t.cropOnion,
    t.cropSugarcane,
    t.cropPotato,
  ];

  return (
    <div className="min-h-screen bg-white" data-theme="light">
      <Navbar />

      {/* ── HERO ── */}
      <section className="relative min-h-[90vh] flex items-center overflow-hidden">
        <div className="absolute inset-0">
          <Image
            src="/hero_field.jpg"
            alt="Lush green Indian farmland aerial view"
            fill
            className="object-cover"
            priority
          />
          <div className="absolute inset-0 bg-gradient-to-r from-farm-dark/90 via-farm-dark/65 to-transparent" />
        </div>

        <div className="relative z-10 max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 pt-28 pb-20">
          <div className="max-w-xl">
            <div className="inline-flex items-center gap-2 bg-white/15 backdrop-blur-sm border border-white/25 rounded-full px-4 py-1.5 mb-6">
              <span className="w-2 h-2 bg-amber-400 rounded-full animate-pulse" />
              <span className="text-white/90 text-sm font-medium">{t.heroBadge}</span>
            </div>

            <h1 className="text-4xl sm:text-5xl lg:text-6xl font-bold text-white leading-tight mb-5">
              {t.heroTitle1}<br />
              <span className="text-amber-400">{t.heroTitle2}</span>
            </h1>

            <p className="text-white/85 text-lg mb-8 leading-relaxed">
              {t.heroSubtitle}
            </p>

            <div className="flex flex-wrap gap-3">
              <Link
                href={authed ? "/dashboard" : "/login"}
                className="inline-flex items-center justify-center gap-2 bg-amber-400 text-farm-dark px-6 py-3.5 rounded-xl font-bold hover:bg-amber-500 transition-all duration-200 shadow-hero text-base group"
              >
                {authed ? <LayoutDashboard className="w-4 h-4" /> : <LogIn className="w-4 h-4" />}
                {authed ? "Go to Dashboard" : t.btnLogin}
              </Link>
              <Link
                href="/features"
                className="inline-flex items-center justify-center gap-2 bg-farm-green text-white px-6 py-3.5 rounded-xl font-semibold hover:bg-farm-green-dark transition-all duration-200 shadow-hero text-base group"
              >
                {t.btnExplore}
                <ArrowRight className="w-4 h-4 group-hover:translate-x-1 transition-transform" />
              </Link>
            </div>
          </div>
        </div>
      </section>

      {/* ── 4 THINGS EXPLAINED ── */}
      <section className="py-20 bg-white">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="text-center mb-14">
            <p className="text-farm-green text-sm font-semibold uppercase tracking-wider mb-2">{t.sectionWhatWeDoBadge}</p>
            <h2 className="text-3xl sm:text-4xl font-bold text-farm-dark">
              {t.sectionWhatWeDoTitle}
            </h2>
            <p className="text-farm-muted mt-3 max-w-lg mx-auto text-base">
              {t.sectionWhatWeDoSubtitle}
            </p>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
            {features.map(({ title, desc, icon: Icon, color, href }) => (
              <Link
                key={title}
                href={href}
                className="group p-6 rounded-2xl border border-farm-border-color bg-white hover:shadow-card-hover hover:border-farm-green transition-all duration-200 cursor-pointer"
              >
                <div className={`w-11 h-11 rounded-xl flex items-center justify-center mb-4 ${color}`}>
                  <Icon className="w-5 h-5" />
                </div>
                <h3 className="font-semibold text-farm-dark mb-2 text-base group-hover:text-farm-green transition-colors">{title}</h3>
                <p className="text-farm-muted text-sm leading-relaxed">{desc}</p>
                <div className="mt-3 flex items-center text-farm-green text-xs font-medium opacity-0 group-hover:opacity-100 transition-opacity gap-1">
                  {t.learnMore} <ChevronRight className="w-3 h-3" />
                </div>
              </Link>
            ))}
          </div>
        </div>
      </section>

      {/* ── FIELD VIEWS (REAL PICTURES + NO IOT CLAIM) ── */}
      <section className="py-20 bg-farm-sand">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="text-center mb-14">
            <p className="text-farm-green text-sm font-semibold uppercase tracking-wider mb-2">{t.section4WaysBadge}</p>
            <h2 className="text-3xl sm:text-4xl font-bold text-farm-dark">
              {t.section4WaysTitle}
            </h2>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5">
            {fieldViews.map(({ label, desc, image, tag }) => (
              <div
                key={label}
                className="group bg-white rounded-2xl overflow-hidden border border-farm-border-color hover:shadow-card-hover hover:border-farm-green transition-all duration-300"
              >
                <div className="h-48 relative overflow-hidden">
                  <Image
                    src={image}
                    alt={label}
                    fill
                    className="object-cover group-hover:scale-105 transition-transform duration-500"
                  />
                  <div className="absolute inset-0 bg-gradient-to-t from-farm-dark/85 via-farm-dark/20 to-transparent" />
                  <span className="absolute top-3 right-3 bg-black/50 backdrop-blur-sm text-white text-[11px] font-medium px-2 py-0.5 rounded-md border border-white/20">
                    {tag}
                  </span>
                  <div className="absolute bottom-3 left-3 right-3">
                    <span className="text-white font-bold text-base drop-shadow-sm block">{label}</span>
                  </div>
                </div>
                <div className="p-4 bg-white">
                  <p className="text-farm-muted text-xs font-medium leading-relaxed">{desc}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── HOW IT WORKS ── */}
      <section className="py-20 bg-white">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="text-center mb-14">
            <p className="text-farm-green text-sm font-semibold uppercase tracking-wider mb-2">{t.sectionStepsBadge}</p>
            <h2 className="text-3xl sm:text-4xl font-bold text-farm-dark">{t.sectionStepsTitle}</h2>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-8">
            {howItWorks.map(({ step, title, desc, icon: Icon }, i) => (
              <div key={step} className="relative flex flex-col items-center text-center">
                {i < howItWorks.length - 1 && (
                  <div className="hidden lg:block absolute top-8 left-1/2 w-full h-px bg-farm-border-color" />
                )}
                <div className="w-16 h-16 rounded-full bg-farm-green-light border-2 border-farm-green flex items-center justify-center mb-4 z-10 relative">
                  <Icon className="w-7 h-7 text-farm-green" />
                </div>
                <span className="text-xs font-bold text-farm-green uppercase tracking-widest mb-1">{step}</span>
                <h3 className="font-bold text-farm-dark text-base mb-2">{title}</h3>
                <p className="text-farm-muted text-sm leading-relaxed">{desc}</p>
              </div>
            ))}
          </div>

          <div className="flex justify-center mt-12">
            <Link
              href="/ai-chat"
              className="inline-flex items-center gap-2 bg-farm-green text-white px-8 py-3.5 rounded-xl font-semibold hover:bg-farm-green-dark transition-all duration-200 shadow-card group"
            >
              {t.btnTryKrishiBot}
              <ArrowRight className="w-4 h-4 group-hover:translate-x-1 transition-transform" />
            </Link>
          </div>
        </div>
      </section>

      {/* ── CROPS ── */}
      <section className="py-20 bg-farm-sand">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-16 items-center">
            <div>
              <p className="text-farm-green text-sm font-semibold uppercase tracking-wider mb-2">{t.sectionCropsBadge}</p>
              <h2 className="text-3xl sm:text-4xl font-bold text-farm-dark mb-4">
                {t.sectionCropsTitle}
              </h2>
              <div className="flex flex-wrap gap-2.5 mb-5">
                {crops.map((c) => (
                  <span key={c} className="px-4 py-2 bg-white border border-farm-border-color rounded-xl text-sm text-farm-dark font-medium hover:border-farm-green hover:text-farm-green transition-colors cursor-default shadow-xs">
                    🌾 {c}
                  </span>
                ))}
              </div>
              <p className="text-farm-muted text-sm mb-6 leading-relaxed">
                {t.sectionCropsDesc}
              </p>
              <Link href="/login" className="inline-flex items-center gap-2 text-farm-green font-semibold hover:gap-3 transition-all text-sm">
                {t.linkManageCrops} <ArrowRight className="w-4 h-4" />
              </Link>
            </div>
            <div className="relative rounded-3xl overflow-hidden h-72 shadow-card-hover">
              <Image src="/farmer_closeup.jpg" alt="Farmer holding crop seedlings" fill className="object-cover" />
            </div>
          </div>
        </div>
      </section>

      {/* ── BOTTOM CTA ── */}
      <section className="bg-farm-dark py-20">
        <div className="max-w-4xl mx-auto px-4 text-center">
          <h2 className="text-3xl sm:text-4xl font-bold text-white mb-4">
            {t.bottomCtaTitle}
          </h2>
          <p className="text-white/70 mb-8 max-w-lg mx-auto">
            {t.bottomCtaDesc}
          </p>
          <div className="flex flex-col sm:flex-row gap-4 justify-center">
            <Link
              href="/login"
              className="inline-flex items-center justify-center gap-2 bg-amber-400 text-farm-dark px-8 py-4 rounded-xl font-bold text-base hover:bg-amber-500 transition-all duration-200 group shadow-md"
            >
              {t.bottomCtaBtnSign}
              <ArrowRight className="w-5 h-5 group-hover:translate-x-1 transition-transform" />
            </Link>
            <Link
              href="/ai-chat"
              className="inline-flex items-center justify-center gap-2 bg-white/10 text-white px-8 py-4 rounded-xl font-bold text-base border border-white/20 hover:bg-white/20 transition-all duration-200"
            >
              {t.bottomCtaBtnChat}
            </Link>
          </div>
          <p className="mt-6 text-white/40 text-xs">{t.bottomCtaLangFoot}</p>
        </div>
      </section>

      <Footer />
    </div>
  );
}
