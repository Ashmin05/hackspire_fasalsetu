import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import QueryProvider from "@/components/QueryProvider";
import { LanguageProvider } from "@/lib/LanguageContext";
import dynamic from "next/dynamic";

// Load widget client-side only (it uses browser APIs and state)
const KrishiBotWidget = dynamic(() => import("@/components/KrishiBotWidget"), { ssr: false });

const inter = Inter({
  variable: "--font-sans",
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
});

export const metadata: Metadata = {
  title: "FasalSetu – Smart Farming Intelligence",
  description: "Satellite crop monitoring, weather alerts, soil analysis, AI advice — built for Indian farmers.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="light" style={{ colorScheme: "light" }}>
      <body
        className={`${inter.variable} font-sans bg-white text-farm-dark antialiased`}
        data-theme="light"
        style={{ colorScheme: "light" }}
      >
        <LanguageProvider>
          <QueryProvider>
            {children}
            <KrishiBotWidget />
          </QueryProvider>
        </LanguageProvider>
      </body>
    </html>
  );
}
