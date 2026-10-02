import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/lib/api";

export function useIrrigationData(fieldId: string) {
  return useQuery({
    queryKey: ["irrigation", fieldId],
    queryFn: () => apiClient.getIrrigationData(fieldId).then((r) => r.data),
    enabled: !!fieldId,
    staleTime: 60 * 60 * 1000, // soil sensor data, hourly is fine
  });
}
