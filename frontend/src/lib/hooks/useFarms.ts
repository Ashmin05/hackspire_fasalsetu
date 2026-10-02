import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/lib/api";

export function useFarms() {
  return useQuery({
    queryKey: ["farms"],
    queryFn: () => apiClient.listFarms().then((r) => r.data),
    staleTime: 5 * 60 * 1000,
  });
}

export function useFarm(farmId: string) {
  return useQuery({
    queryKey: ["farm", farmId],
    queryFn: () => apiClient.getFarm(farmId).then((r) => r.data),
    enabled: !!farmId,
    staleTime: 5 * 60 * 1000,
  });
}
