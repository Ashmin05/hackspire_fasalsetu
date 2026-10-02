"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FarmAlert, getFarmAlerts, markAlertRead } from "@/lib/api/satellite-client";
import { isRealFarmId } from "@/lib/hooks/useFarmSatelliteAnalysis";


export function useFarmAlerts(farmId: string | undefined) {
  const isRealFarm = isRealFarmId(farmId);
  const queryClient = useQueryClient();
  const queryKey = ["farm-alerts", farmId];

  const query = useQuery({
    queryKey,
    queryFn: () => getFarmAlerts(farmId as string),
    enabled: isRealFarm,
  });

  const markReadMutation = useMutation({
    mutationFn: (alertId: string) => markAlertRead(alertId),
    onMutate: async (alertId: string) => {
      await queryClient.cancelQueries({ queryKey });
      const previous = queryClient.getQueryData<FarmAlert[]>(queryKey);
      queryClient.setQueryData<FarmAlert[]>(queryKey, (alerts) =>
        alerts?.map((a) => (a.id === alertId ? { ...a, is_read: true } : a))
      );
      return { previous };
    },
    onError: (_err, _alertId, context) => {
      if (context?.previous) queryClient.setQueryData(queryKey, context.previous);
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey }),
  });

  const alerts = isRealFarm ? query.data ?? [] : [];

  return {
    alerts,
    unread: alerts.filter((a) => !a.is_read),
    isLoading: isRealFarm && query.isLoading,
    isError: query.isError,
    retry: query.refetch,
    markRead: markReadMutation.mutate,
    markReadError: markReadMutation.isError,
  };
}
