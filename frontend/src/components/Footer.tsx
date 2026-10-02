import Image from "next/image";
import Link from "next/link";

const footerLinks = {
  Product: [
    { label: "Features", href: "/features" },
    { label: "Satellite Monitoring", href: "/satellite" },
    { label: "Weather", href: "/weather" },
    { label: "Mandi Prices", href: "/market" },
    { label: "AI Assistant (KrishiBot)", href: "/ai-chat" },
  ],
  Account: [
    { label: "Farmer Login", href: "/login" },
    { label: "Dashboard", href: "/dashboard" },
    { label: "Help Center", href: "/help" },
  ],
};

const crops = ["Rice", "Wheat", "Onion", "Potato", "Sugarcane"];

export default function Footer() {
  return (
    <footer className="bg-farm-dark text-white">
      {/* Crops marquee band */}
      <div className="bg-farm-green py-4 overflow-hidden">
        <div className="flex gap-6 whitespace-nowrap" style={{ animation: "marquee 20s linear infinite" }}>
          {[...crops, ...crops].map((c, i) => (
            <span key={i} className="text-white/90 text-sm font-medium flex-shrink-0">
              🌾 {c}
            </span>
          ))}
        </div>
      </div>

      <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-16">
        <div className="grid grid-cols-1 md:grid-cols-4 gap-12">
          {/* Brand */}
          <div className="md:col-span-2">
            <Link href="/" className="inline-flex mb-4 bg-white rounded-lg px-3 py-1.5">
              <Image src="/logo.webp" alt="FasalSetu" width={132} height={45} className="h-9 w-auto" />
            </Link>
            <p className="text-white/60 text-sm leading-relaxed max-w-xs">
              Empowering Indian farmers with satellite intelligence, AI-driven advice,
              and weather and market insights for their own fields.
            </p>
          </div>

          {/* Links */}
          {Object.entries(footerLinks).map(([group, links]) => (
            <div key={group}>
              <h4 className="font-semibold text-white/90 mb-4 text-sm uppercase tracking-wider">{group}</h4>
              <ul className="space-y-2.5">
                {links.map(({ label, href }) => (
                  <li key={href}>
                    <Link
                      href={href}
                      className="text-white/55 text-sm hover:text-white transition-colors hover:underline underline-offset-2"
                    >
                      {label}
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>

        <div className="mt-14 pt-8 border-t border-white/10 flex flex-col sm:flex-row items-center justify-between gap-4">
          <div className="flex flex-col items-center sm:items-start gap-1">
            <p className="text-white/40 text-sm">© 2026 FasalSetu. Built with ❤️ for Indian farmers.</p>
            <p className="text-white/30 text-xs">Created by Team Necxtron</p>
          </div>
          <p className="text-white/40 text-sm">🇮🇳 FasalSetu – Smart Agriculture</p>
        </div>
      </div>
    </footer>
  );
}
