import Link from "next/link";



import Navbar from "@/components/Navbar";
import Footer from "@/components/Footer";
import {
  Map, Satellite, BarChart2, Bell, Cloud,
  Droplet, DollarSign, Brain,
  ClipboardList, ArrowRight, ChevronRight
} from "lucide-react";

// Every card and bullet here describes something the app actually does
// today -- don't add planned features.
const featureGroups = [
  {
    group: "🌾 Farm & Field",
    color: "emerald",
    features: [
      {
        id: "farm-management",
        title: "Farm Management",
        desc: "Register all your farms in one account, each with its crop and sowing date.",
        icon: ClipboardList,
        detail: [
          "Multiple farms per account",
          "Crop and sowing date per farm",
          "Optional Soil Health Card / lab report entry",
          "Crop-stage tracking from the sowing date",
        ],
      },
      {
        id: "field-mapping",
        title: "Field Mapping",
        desc: "Draw your field boundary on a map. Area is calculated in acres and hectares.",
        icon: Map,
        detail: [
          "Draw the field boundary on a Mapbox map",
          "Area calculation in acres & hectares",
          "Village / place search",
          "Use your current GPS location",
        ],
      },
    ],
  },
  {
    group: "🛰️ Satellite Intelligence",
    color: "sky",
    features: [
      {
        id: "satellite-crop-health",
        title: "Satellite Crop Health",
        desc: "Sentinel-2 imagery of your own field boundary, showing healthy vs. stressed areas.",
        icon: Satellite,
        detail: [
          "True-colour, NDVI, NDWI and EVI map layers",
          "Stress-zone outlines you can click for details",
          "Slider to view earlier satellite passes",
          "Health score against your crop's growth stage",
        ],
      },
      {
        id: "ndvi-history",
        title: "NDVI Season Curve",
        desc: "Track your crop's greenness index across the season, one point per clear satellite pass.",
        icon: BarChart2,
        detail: [
          "NDVI graph over the current season",
          "Compared with the expected curve for your crop's stage",
          "Cloudy passes skipped automatically",
          "Updated nightly",
        ],
      },
      {
        id: "crop-stress-alert",
        title: "Crop Stress Alerts",
        desc: "In-app alerts when a new satellite pass shows your crop under stress.",
        icon: Bell,
        detail: [
          "Sudden NDVI drop",
          "NDVI below the benchmark for the crop stage",
          "Water stress",
          "Warning and critical severity levels",
        ],
      },
    ],
  },
  {
    group: "🌦️ Weather",
    color: "blue",
    features: [
      {
        id: "weather-forecast",
        title: "Weather Forecast",
        desc: "10-day forecast for your field's exact location, from Open-Meteo.",
        icon: Cloud,
        detail: [
          "Daily high / low temperature",
          "Rainfall probability & amount",
          "Wind, humidity and UV index",
          "Heavy-rain, heat-stress and good-spray-window flags",
        ],
      },
    ],
  },
  {
    group: "💧 Irrigation",
    color: "amber",
    features: [
      {
        id: "irrigation-recommendation",
        title: "Irrigation Recommendation",
        desc: "Know when and how much to irrigate, from a daily soil-water balance for your field.",
        icon: Droplet,
        detail: [
          "FAO-56 crop water model",
          "Crop-stage aware water needs",
          "Uses your soil type and the weather forecast",
          "3-day irrigate / hold plan with depth in mm",
        ],
      },
    ],
  },
  {
    group: "📈 Market",
    color: "orange",
    features: [
      {
        id: "price-trends",
        title: "Mandi Prices",
        desc: "Track mandi prices for your crop and see short-term price estimates.",
        icon: DollarSign,
        detail: [
          "Mandi price data from Agmarknet",
          "Price history over time",
          "7 / 14 / 30-day price estimates",
          "Sell-now or hold suggestion",
        ],
      },
    ],
  },
  {
    group: "🤖 AI Assistant",
    color: "purple",
    features: [
      {
        id: "ai-farming-assistant",
        title: "AI Farming Assistant",
        desc: "KrishiBot answers questions about your farm using its own satellite, weather, irrigation and mandi data.",
        icon: Brain,
        detail: [
          "Natural language Q&A",
          "Answers based on your farm's real data",
          "Shows which data each answer used",
          "Suggested next steps and warnings",
        ],
      },
    ],
  },
];

const featureCount = featureGroups.reduce((n, g) => n + g.features.length, 0);

export default function FeaturesPage() {
  return (
    <div className="min-h-screen bg-white" data-theme="light">
      <Navbar />

      {/* Hero */}
      <div className="pt-28 pb-16 bg-farm-green-light border-b border-farm-border-color">
        <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 text-center">
          <p className="text-farm-green text-sm font-semibold uppercase tracking-wider mb-2">Complete Agri-Tech Suite</p>
          <h1 className="text-4xl sm:text-5xl font-bold text-farm-dark mb-4">
            {featureCount} tools for smarter farming.
          </h1>
          <p className="text-farm-muted text-lg max-w-2xl mx-auto">
            From satellite imagery to an AI farm advisor — built for Indian farmers.
          </p>
        </div>
      </div>

      {/* Features grouped */}
      <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-16 space-y-16">
        {featureGroups.map(({ group, features }) => (
          <div key={group}>
            <h2 className="text-2xl font-bold text-farm-dark mb-6 pb-3 border-b border-farm-border-color">
              {group}
            </h2>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              {features.map(({ id, title, desc, icon: Icon, detail }) => (
                <div
                  key={id}
                  className="group p-6 rounded-2xl border border-farm-border-color bg-white hover:shadow-card-hover hover:border-farm-green transition-all duration-200"
                >
                  <div className="flex items-start justify-between mb-4">
                    <div className="w-11 h-11 rounded-xl bg-farm-green-light flex items-center justify-center">
                      <Icon className="w-5 h-5 text-farm-green" />
                    </div>
                  </div>
                  <h3 className="font-bold text-farm-dark text-lg mb-2 group-hover:text-farm-green transition-colors">
                    {title}
                  </h3>
                  <p className="text-farm-muted text-sm mb-4 leading-relaxed">{desc}</p>
                  <ul className="space-y-1.5">
                    {detail.map((d) => (
                      <li key={d} className="flex items-start gap-2 text-sm text-farm-dark/80">
                        <span className="mt-0.5 w-4 h-4 rounded-full bg-farm-green-light flex items-center justify-center flex-shrink-0">
                          <ChevronRight className="w-2.5 h-2.5 text-farm-green" />
                        </span>
                        {d}
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>

      {/* CTA */}
      <div className="bg-farm-sand py-16 border-t border-farm-border-color">
        <div className="max-w-2xl mx-auto px-4 text-center">
          <h2 className="text-3xl font-bold text-farm-dark mb-3">Ready to get started?</h2>
          <p className="text-farm-muted mb-8">Access all {featureCount} farming tools directly from your dashboard.</p>
          <div className="flex flex-col sm:flex-row gap-3 justify-center">
            <Link
              href="/register"
              className="inline-flex items-center justify-center gap-2 bg-farm-green text-white px-8 py-3.5 rounded-xl font-bold hover:bg-farm-green-dark transition-all duration-200 shadow-card group"
            >
              Create Farmer Account <ArrowRight className="w-4 h-4 group-hover:translate-x-1 transition-transform" />
            </Link>
            <Link
              href="/login"
              className="inline-flex items-center justify-center gap-2 bg-white border border-farm-border-color text-farm-dark px-8 py-3.5 rounded-xl font-semibold hover:border-farm-green hover:text-farm-green transition-all duration-200"
            >
              Sign In to Dashboard
            </Link>
          </div>
        </div>
      </div>

      <Footer />
    </div>
  );
}
