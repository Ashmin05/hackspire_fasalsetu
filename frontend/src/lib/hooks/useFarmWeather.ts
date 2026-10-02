"use client";

import { useQuery } from "@tanstack/react-query";
import { getFarmWeather } from "@/lib/api/weather-client";
import { isRealFarmId } from "@/lib/hooks/useFarmSatelliteAnalysis";

/**
 * 10-day Open-Meteo forecast for a real farm. No-op for guest/demo farms.
 * staleTime matches the backend's own WEATHER_CACHE_HOURS (3h) -- no point
 * refetching more often than the cache can actually change.
 */
export function useFarmWeather(farmId: string | undefined) {
  const isRealFarm = isRealFarmId(farmId);

  const query = useQuery({
    queryKey: ["farm-weather", farmId],
    queryFn: () => getFarmWeather(farmId as string),
    enabled: isRealFarm,
    staleTime: 3 * 60 * 60 * 1000,
  });

  return {
    weather: isRealFarm ? query.data ?? null : null,
    isLoading: isRealFarm && query.isLoading,
    isError: query.isError,
    retry: query.refetch,
  };
}
