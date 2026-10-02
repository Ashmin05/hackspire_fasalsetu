import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/lib/api";

export function useFields(farmId: string) {
  return useQuery({
    queryKey: ["fields", farmId],
    queryFn: () => apiClient.listFields(farmId).then((r) => r.data),
    enabled: !!farmId,
    staleTime: 5 * 60 * 1000,
  });
}

export function useField(farmId: string, fieldId: string) {
  return useQuery({
    queryKey: ["field", farmId, fieldId],
    queryFn: () => apiClient.getField(farmId, fieldId).then((r) => r.data),
    enabled: !!farmId && !!fieldId,
    staleTime: 5 * 60 * 1000,
  });
}
