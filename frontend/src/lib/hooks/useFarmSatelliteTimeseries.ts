"use client";

import { useQuery } from "@tanstack/react-query";
import { getSatelliteTimeseries } from "@/lib/api/satellite-client";
import { isRealFarmId } from "@/lib/hooks/useFarmSatelliteAnalysis";

/**
 * Every accumulated clear Sentinel-2 pass for a real farm, oldest first --
 * drives the season curve and the map's pass-date slider. Cache-only on the
 * backend (filled by the nightly job), so an empty list is normal for a new
 * farm. No-op for guest/demo farm ids.
 */
export function useFarmSatelliteTimeseries(farmId: string | undefined) {
  const isRealFarm = isRealFarmId(farmId);

  const query = useQuery({
    queryKey: ["satellite-timeseries", farmId],
    queryFn: () => getSatelliteTimeseries(farmId as string),
    enabled: isRealFarm,
  });

  return {
    points: isRealFarm ? query.data ?? [] : [],
    isLoading: isRealFarm && query.isLoading,
    isError: isRealFarm && query.isError,
    retry: query.refetch,
  };
}
