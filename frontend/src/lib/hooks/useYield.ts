import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/lib/api";

export function useYieldData(fieldId: string) {
  return useQuery({
    queryKey: ["yield", fieldId],
    queryFn: () => apiClient.getYieldData(fieldId).then((r) => r.data),
    enabled: !!fieldId,
    staleTime: 24 * 60 * 60 * 1000, // yield estimates update daily
  });
}

export function useMarketPrice(fieldId: string) {
  return useQuery({
    queryKey: ["market-price", fieldId],
    queryFn: () => apiClient.getMarketPrice(fieldId).then((r) => r.data),
    enabled: !!fieldId,
    staleTime: 60 * 60 * 1000,
    refetchInterval: 60 * 60 * 1000,
  });
}
