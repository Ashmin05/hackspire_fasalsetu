"use client";


import { useState } from "react";
import Link from "next/link";
import AppLayout from "@/components/AppLayout";
import FarmsLoadError from "@/components/FarmsLoadError";
import { useFarmStore } from "@/lib/stores/farmStore";
import { isRealFarmId } from "@/lib/hooks/useFarmSatelliteAnalysis";
import { useFarmNews } from "@/lib/hooks/useFarmNews";
import type { NewsArticle } from "@/lib/api/news-client";
import {
  Newspaper, ChevronDown, ChevronRight, Loader2,
  AlertTriangle, Sprout, ExternalLink,
} from "lucide-react";

function timeAgo(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const minutes = Math.max(0, Math.round((Date.now() - then) / 60000));
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  return `${days}d ago`;
}

function ArticleCard({ article }: { article: NewsArticle }) {
  return (
    <a
      href={article.url}
      target="_blank"
      rel="noopener noreferrer"
      className="flex flex-col sm:flex-row gap-4 bg-white rounded-2xl border border-farm-border-color p-4 shadow-xs hover:shadow-card transition-all group"
    >
      <div className="w-full sm:w-40 h-40 sm:h-28 rounded-xl overflow-hidden flex-shrink-0 bg-farm-gray flex items-center justify-center">
        {article.image_url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={article.image_url}
            alt=""
            className="w-full h-full object-cover"
            onError={(e) => {
              (e.currentTarget as HTMLImageElement).style.display = "none";
            }}
          />
        ) : (
          <Newspaper className="w-6 h-6 text-farm-muted" />
        )}
      </div>
      <div className="min-w-0 flex-1 flex flex-col">
        <p className="text-sm font-bold text-farm-dark leading-snug group-hover:text-farm-green transition-colors">
          {article.title}
        </p>
        {article.description && (
          <p className="text-xs text-farm-muted mt-1.5 leading-relaxed line-clamp-2">{article.description}</p>
        )}
        <div className="mt-auto pt-2 flex items-center gap-1.5 text-[11px] text-farm-muted">
          <span className="font-semibold">{article.source}</span>
          {article.published_at && (
            <>
              <span>·</span>
              <span>{timeAgo(article.published_at)}</span>
            </>
          )}
          <ExternalLink className="w-3 h-3 ml-auto text-farm-muted group-hover:text-farm-green transition-colors flex-shrink-0" />
        </div>
      </div>
    </a>
  );
}

export default function NewsPage() {
  const { farms, mounted, loadError, retryLoad } = useFarmStore();
  const realFarms = farms.filter((f) => isRealFarmId(f.id));
  const [selectedFarmId, setSelectedFarmId] = useState<string | undefined>();
  const farm = realFarms.find((f) => f.id === selectedFarmId) ?? realFarms[0];
  const { news, isLoading, isError, retry } = useFarmNews(farm?.id);

  if (!mounted) {
    return <AppLayout>{null}</AppLayout>;
  }

  if (loadError) {
    return (
      <AppLayout>
        <FarmsLoadError message={loadError} onRetry={() => retryLoad()} />
      </AppLayout>
    );
  }

  return (
    <AppLayout>
      <div className="max-w-4xl mx-auto space-y-5 pb-16">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-xl font-bold text-farm-dark flex items-center gap-2">
              <Newspaper className="w-5 h-5 text-farm-green" />
              Farmer News
            </h1>
            <p className="text-xs text-farm-muted mt-0.5">
              {news?.location ? `Local to ${news.location}` : "Farming and agriculture news near you"}
            </p>
          </div>

          {realFarms.length > 1 && (
            <div className="relative">
              <select
                aria-label="Select farm"
                value={farm?.id}
                onChange={(e) => setSelectedFarmId(e.target.value)}
                className="appearance-none bg-white border-2 border-farm-green/70 hover:border-farm-green text-farm-dark font-bold text-xs sm:text-sm pl-4 pr-10 py-2.5 rounded-2xl shadow-xs cursor-pointer focus:outline-none focus:ring-2 focus:ring-farm-green/20 transition-all"
              >
                {realFarms.map((f) => (
                  <option key={f.id} value={f.id}>
                    {f.name} · {f.district}
                  </option>
                ))}
              </select>
              <ChevronDown className="w-4 h-4 text-farm-green absolute right-3.5 top-3 pointer-events-none" />
            </div>
          )}
        </div>

        {!farm ? (
          <div className="max-w-md mx-auto text-center py-16 space-y-4">
            <div className="w-14 h-14 rounded-2xl bg-farm-green-light flex items-center justify-center mx-auto">
              <Sprout className="w-7 h-7 text-farm-green" />
            </div>
            <h2 className="text-lg font-bold text-farm-dark">Register a farm first</h2>
            <p className="text-farm-muted text-sm">
              News is fetched for your farm&apos;s district and state, so add a farm to see it.
            </p>
            <Link
              href="/farms"
              className="inline-flex items-center gap-2 bg-farm-green text-white px-5 py-2.5 rounded-xl font-semibold hover:bg-farm-green-dark transition-all shadow-sm"
            >
              Register a Farm
              <ChevronRight className="w-4 h-4" />
            </Link>
          </div>
        ) : isLoading ? (
          <div className="bg-white rounded-2xl border border-farm-border-color p-10 flex items-center justify-center gap-2 text-sm text-farm-muted">
            <Loader2 className="w-4 h-4 animate-spin" /> Loading news…
          </div>
        ) : isError ? (
          <div className="bg-white rounded-2xl border border-farm-border-color p-10 text-sm text-red-700 text-center flex flex-col items-center gap-2">
            <AlertTriangle className="w-5 h-5" />
            Couldn&apos;t load news.{" "}
            <button onClick={() => retry()} className="font-semibold underline">
              Retry
            </button>
          </div>
        ) : news && !news.is_configured ? (
          <div className="bg-white rounded-2xl border border-farm-border-color p-10 text-sm text-farm-muted text-center">
            News feed isn&apos;t set up yet — ask your administrator to configure NEWS_API_KEY.
          </div>
        ) : news && news.articles.length === 0 ? (
          <div className="bg-white rounded-2xl border border-farm-border-color p-10 text-sm text-farm-muted text-center">
            No recent farming news found for {news.location || "your area"}.
          </div>
        ) : (
          <div className="space-y-3">
            {news?.articles.map((article) => (
              <ArticleCard key={article.url} article={article} />
            ))}
          </div>
        )}
      </div>
    </AppLayout>
  );
}
