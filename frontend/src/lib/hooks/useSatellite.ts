import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/lib/api";

export function useSatelliteData(fieldId: string) {
  return useQuery({
    queryKey: ["satellite", fieldId],
    queryFn: () => apiClient.getSatelliteData(fieldId).then((r) => r.data),
    enabled: !!fieldId,
    staleTime: 30 * 60 * 1000, // satellite data updates every 5 days; 30m is fine
  });
}
