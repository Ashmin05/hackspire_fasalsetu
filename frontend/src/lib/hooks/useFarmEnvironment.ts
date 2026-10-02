"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { getEnvironmentReport, refreshEnvironmentReport } from "@/lib/api/satellite-client";
import { isRealFarmId } from "@/lib/hooks/useFarmSatelliteAnalysis";

/**
 * Rainfall / land-surface temperature / soil moisture / soil properties for
 * a real farm. The backend refreshes this nightly, but a brand-new farm has
 * no cached report to show until then -- so, same pattern as
 * useFarmSatelliteAnalysis's first-analysis query, once the cache read comes
 * back empty this runs one live refresh itself rather than leaving the
 * farmer staring at "--" until the next 02:30 job. No-op for guest/demo
 * farms.
 */
export function useFarmEnvironment(farmId: string | undefined) {
  const isRealFarm = isRealFarmId(farmId);
  const queryClient = useQueryClient();

  const query = useQuery({
    queryKey: ["farm-environment", farmId],
    queryFn: () => getEnvironmentReport(farmId as string),
    enabled: isRealFarm,
    staleTime: 30 * 60 * 1000, // refreshed nightly on the backend
  });

  const firstRefreshQuery = useQuery({
    queryKey: ["farm-environment-first-refresh", farmId],
    queryFn: async () => {
      const report = await refreshEnvironmentReport(farmId as string);
      queryClient.setQueryData(["farm-environment", farmId], report);
      return report;
    },
    enabled: isRealFarm && query.isSuccess && query.data === null,
    staleTime: Infinity,
    retry: false,
  });

  return {
    report: isRealFarm ? query.data ?? null : null,
    isLoading: isRealFarm && (query.isLoading || (query.isSuccess && query.data === null && firstRefreshQuery.isLoading)),
    isError: query.isError || firstRefreshQuery.isError,
    retry: query.isError ? query.refetch : firstRefreshQuery.refetch,
  };
}
