"use client";

import { useQuery } from "@tanstack/react-query";
import { getSatelliteLayers } from "@/lib/api/satellite-client";
import { isRealFarmId } from "@/lib/hooks/useFarmSatelliteAnalysis";

/**
 * Visualised Sentinel-2 tile URLs + stress zones for a real farm's map.
 * A no-op for guest/demo farm ids (see isRealFarmId) -- no network call,
 * no loading state, nothing. Can take several seconds on a cache miss
 * (a real Earth Engine round trip), so `isLoading` is worth showing.
 * Waits for `imageDate` (a known pass date), so it never fires for a farm
 * that has no analysis yet.
 */
export function useFarmSatelliteLayers(farmId: string | undefined, imageDate: string | undefined) {
  const isRealFarm = isRealFarmId(farmId);

  const query = useQuery({
    queryKey: ["satellite-layers", farmId, imageDate],
    queryFn: () => getSatelliteLayers(farmId as string, imageDate),
    enabled: isRealFarm && !!imageDate,
    staleTime: 10 * 60 * 1000, // tile URLs are backend-cached ~12h; no need to refetch often
    retry: false,
  });

  return {
    isRealFarm,
    layers: isRealFarm ? query.data ?? null : null,
    isLoading: isRealFarm && !!imageDate && query.isLoading,
    error:
      isRealFarm && query.isError
        ? query.error instanceof Error
          ? query.error.message
          : "Couldn't load the map layers."
        : null,
    retry: query.refetch,
  };
}
