"use client";

import { useQuery } from "@tanstack/react-query";
import { getFarmNews } from "@/lib/api/news-client";
import { isRealFarmId } from "@/lib/hooks/useFarmSatelliteAnalysis";

/**
 * Location-based farming news for a real farm's district/state. No-op for
 * guest/demo farms. staleTime matches the backend's own NEWS_CACHE_MINUTES
 * (30m) -- no point refetching more often than the cache can actually change.
 */
export function useFarmNews(farmId: string | undefined) {
  const isRealFarm = isRealFarmId(farmId);

  const query = useQuery({
    queryKey: ["farm-news", farmId],
    queryFn: () => getFarmNews(farmId as string),
    enabled: isRealFarm,
    staleTime: 30 * 60 * 1000,
  });

  return {
    news: isRealFarm ? query.data ?? null : null,
    isLoading: isRealFarm && query.isLoading,
    isError: query.isError,
    retry: query.refetch,
  };
}
