"use client";

import { useQuery } from "@tanstack/react-query";
import { getFarmIrrigation } from "@/lib/api/irrigation-client";
import { isRealFarmId } from "@/lib/hooks/useFarmSatelliteAnalysis";

/**
 * FAO-56 root-zone water balance (depletion vs. RAW, next irrigation date +
 * depth) for a real farm. No-op for guest/demo farms. staleTime matches
 * useFarmEnvironment's -- the balance only meaningfully changes once a day
 * as it rolls forward over CHIRPS/Open-Meteo history.
 */
export function useFarmIrrigation(farmId: string | undefined) {
  const isRealFarm = isRealFarmId(farmId);

  const query = useQuery({
    queryKey: ["farm-irrigation", farmId],
    queryFn: () => getFarmIrrigation(farmId as string),
    enabled: isRealFarm,
    staleTime: 30 * 60 * 1000,
  });

  return {
    plan: isRealFarm ? query.data ?? null : null,
    isLoading: isRealFarm && query.isLoading,
    isError: query.isError,
    retry: query.refetch,
  };
}
