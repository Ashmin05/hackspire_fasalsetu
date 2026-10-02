import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/lib/api";

export function useWeatherData(fieldId: string) {
  return useQuery({
    queryKey: ["weather", fieldId],
    queryFn: () => apiClient.getWeatherData(fieldId).then((r) => r.data),
    enabled: !!fieldId,
    staleTime: 15 * 60 * 1000, // weather refreshes every 15 min
    refetchInterval: 15 * 60 * 1000,
  });
}
