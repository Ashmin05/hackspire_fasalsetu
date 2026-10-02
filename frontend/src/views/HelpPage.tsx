import Link from "next/link";




import Navbar from "@/components/Navbar";
import Footer from "@/components/Footer";
import { BookOpen, Satellite, Droplet, MessageCircle, TrendingUp } from "lucide-react";

const topics = [
  {
    icon: BookOpen,
    title: "Getting started",
    points: [
      "Create an account, then complete your profile (phone and state).",
      "Go to My Farms → Register New Farm: enter the name, location, crop and sowing date.",
      "Draw your field boundary on the map — the area is calculated for you.",
    ],
    link: { href: "/farms", label: "Go to My Farms" },
  },
  {
    icon: Satellite,
    title: "Satellite & NDVI",
    points: [
      "NDVI measures how green and dense your crop is (roughly 0 = bare soil, 0.8+ = very dense).",
      "The health score compares your field's NDVI with what's expected for your crop at its current stage.",
      "Sentinel-2 passes about every 5 days; cloudy passes are skipped, so gaps between points are normal.",
    ],
    link: { href: "/satellite", label: "Open Satellite" },
  },
  {
    icon: Droplet,
    title: "Irrigation advice",
    points: [
      "The Dashboard shows a 3-day irrigate / hold plan with a depth in mm.",
      "It comes from a daily soil-water balance (FAO-56) using your crop stage, soil type and the weather forecast.",
    ],
    link: { href: "/dashboard", label: "Open Dashboard" },
  },
  {
    icon: TrendingUp,
    title: "Mandi prices",
    points: [
      "Prices come from Agmarknet for your crop in your farm's state.",
      "Price estimates and the sell-or-hold suggestion are estimates, not guarantees.",
    ],
    link: { href: "/market", label: "Open Mandi Prices" },
  },
  {
    icon: MessageCircle,
    title: "Asking KrishiBot",
    points: [
      "KrishiBot answers from your farm's own data — satellite, weather, irrigation and mandi prices.",
      "Ask specific questions, e.g. “When should I irrigate next?” or “Should I sell now?”.",
      "If it doesn't have the data for something, it will say so instead of guessing.",
    ],
    link: { href: "/ai-chat", label: "Ask KrishiBot" },
  },
];

export default function HelpPage() {
  return (
    <div className="min-h-screen bg-white" data-theme="light">
      <Navbar />
      <div className="pt-24 pb-14 bg-farm-green-light border-b border-farm-border-color text-center">
        <h1 className="text-4xl font-bold text-farm-dark mb-3">Help Center</h1>
        <p className="text-farm-muted max-w-md mx-auto">Quick answers on how each part of FasalSetu works.</p>
      </div>
      <div className="max-w-4xl mx-auto px-4 py-16">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
          {topics.map(({ icon: Icon, title, points, link }) => (
            <div key={title} className="p-6 rounded-2xl border border-farm-border-color flex flex-col">
              <div className="w-11 h-11 bg-farm-green-light rounded-xl flex items-center justify-center mb-4">
                <Icon className="w-5 h-5 text-farm-green" />
              </div>
              <h3 className="font-bold text-farm-dark mb-2">{title}</h3>
              <ul className="space-y-1.5 text-farm-muted text-sm list-disc list-inside flex-1">
                {points.map((p) => (
                  <li key={p}>{p}</li>
                ))}
              </ul>
              <Link href={link.href} className="mt-4 text-farm-green text-sm font-semibold hover:underline">
                {link.label} →
              </Link>
            </div>
          ))}
        </div>
      </div>
      <Footer />
    </div>
  );
}
