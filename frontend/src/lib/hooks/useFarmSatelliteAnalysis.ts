"use client";

import { useCallback } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  getLatestSatelliteAnalysis,
  isNoImageryError,
  refreshSatelliteAnalysis,
  SatelliteApiError,
  SatelliteObservation,
} from "@/lib/api/satellite-client";

// Real backend farm ids are UUIDs (backend/app/models/farm.py). Guest/demo
// farms use ids like "farm-1" or "farm-<timestamp>" that never hit the
// backend at all -- this hook is a deliberate no-op for those, so it never
// makes a network call (and never shows an error) for a farm that was never
// going to have a real analysis.
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function isRealFarmId(farmId: string | undefined): boolean {
  return !!farmId && UUID_RE.test(farmId);
}

/**
 * - guest:      demo farm, no network calls at all
 * - checking:   reading the cached analysis (/latest)
 * - analysing:  no cached analysis yet, so the first live one is running (~30 s)
 * - ready:      `observation` is set
 * - no-imagery: the first analysis found no Sentinel-2 scene for this field yet
 * - error:      anything else went wrong -- `retry` re-runs whichever step failed
 */
export type SatelliteStatus = "guest" | "checking" | "analysing" | "ready" | "no-imagery" | "error";

export function useFarmSatelliteAnalysis(farmId: string | undefined) {
  const isRealFarm = isRealFarmId(farmId);
  const queryClient = useQueryClient();

  const latestQuery = useQuery({
    queryKey: ["satellite-latest", farmId],
    queryFn: () => getLatestSatelliteAnalysis(farmId as string),
    enabled: isRealFarm,
  });

  // The first-ever analysis is a query rather than a mutation so every
  // component showing this farm (Dashboard, Satellite page) shares one
  // in-flight Earth Engine run and one error state via the query cache,
  // instead of each kicking off its own.
  const firstAnalysisQuery = useQuery({
    queryKey: ["satellite-first-analysis", farmId],
    queryFn: async () => {
      const observation = await refreshSatelliteAnalysis(farmId as string);
      queryClient.setQueryData(["satellite-latest", farmId], observation);
      return observation;
    },
    enabled: isRealFarm && latestQuery.isSuccess && latestQuery.data === null,
    staleTime: Infinity,
    retry: false,
  });

  const refreshMutation = useMutation({
    mutationFn: (id: string) => refreshSatelliteAnalysis(id),
    onSuccess: (observation: SatelliteObservation, id: string) => {
      queryClient.setQueryData(["satellite-latest", id], observation);
      queryClient.invalidateQueries({ queryKey: ["satellite-layers", id] });
    },
  });

  const refresh = useCallback(() => {
    if (!isRealFarm) return;
    refreshMutation.mutate(farmId as string);
  }, [isRealFarm, farmId, refreshMutation]);

  const observation = isRealFarm ? latestQuery.data ?? null : null;
  const mutationIsForThisFarm = refreshMutation.variables === farmId;

  let status: SatelliteStatus;
  let error: unknown = null;
  if (!isRealFarm) status = "guest";
  else if (observation) status = "ready"; // keep showing cached data even if a background refetch failed
  else if (latestQuery.isLoading) status = "checking";
  else if (latestQuery.isError) {
    status = "error";
    error = latestQuery.error;
  }
  else if (firstAnalysisQuery.isError) {
    error = firstAnalysisQuery.error;
    status = isNoImageryError(error) ? "no-imagery" : "error";
  } else status = "analysing";

  const retry = useCallback(() => {
    if (latestQuery.isError) latestQuery.refetch();
    else firstAnalysisQuery.refetch();
  }, [latestQuery, firstAnalysisQuery]);

  return {
    isRealFarm,
    status,
    observation,
    error: error instanceof Error ? error.message : error ? "Something went wrong." : null,
    retry,
    isLoading: isRealFarm && latestQuery.isLoading,
    isRefreshing: refreshMutation.isPending && mutationIsForThisFarm,
    refreshError:
      mutationIsForThisFarm && refreshMutation.error instanceof SatelliteApiError
        ? refreshMutation.error.message
        : null,
    refresh,
  };
}
