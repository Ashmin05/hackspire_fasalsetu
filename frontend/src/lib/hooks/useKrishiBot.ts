"use client";

import { useCallback } from "react";
import { apiClient, type ChatContext, type ChatMessage } from "@/lib/api";
import { AdvisorApiError, askAdvisor, type AdvisorSource } from "@/lib/api/advisor-client";
import { isRealFarmId } from "@/lib/hooks/useFarmSatelliteAnalysis";
import { useFarmStore } from "@/lib/stores/farmStore";

/** A KrishiBot reply, same shape as ChatMessage plus (for a real, signed-in
 * farm) the structured extras the AI advisor returns -- see
 * AdvisorAskResponse in advisor-client.ts. */
export interface KrishiBotMessage extends ChatMessage {
  sources?: AdvisorSource[];
  actionPoints?: string[];
  warnings?: string[];
}

/**
 * Shared send logic for KrishiBotWidget and AiChatPage: asks the real AI
 * Advisor (POST /farms/{id}/ask) for a real, signed-in farm, and falls back
 * to apiClient.sendChatMessage's scripted/mock replies otherwise (guest
 * farms, or no farm registered yet) -- mirrors the same real-vs-demo split
 * every other farm feature uses (see isRealFarmId).
 */
export function useKrishiBot(farmId: string | undefined, language: string = "en") {
  const { farms } = useFarmStore();
  const farm = farmId ? farms.find((f) => f.id === farmId) : farms[0];
  const isRealFarm = isRealFarmId(farm?.id);

  const send = useCallback(
    async (question: string, history: ChatMessage[], context?: ChatContext): Promise<KrishiBotMessage> => {
      if (isRealFarm && farm) {
        try {
          const res = await askAdvisor(farm.id, question, language);
          return {
            id: `a-${Date.now()}`,
            role: "assistant",
            content: res.answer,
            timestamp: res.generated_at,
            sources: res.sources_used,
            actionPoints: res.action_points,
            warnings: res.warnings,
          };
        } catch (err) {
          const message =
            err instanceof AdvisorApiError && err.status === 429
              ? "You've asked KrishiBot a lot of questions this hour -- please try again shortly."
              : "Sorry, I couldn't reach KrishiBot AI just now. Please try again.";
          return { id: `e-${Date.now()}`, role: "assistant", content: message, timestamp: new Date().toISOString() };
        }
      }

      const res = await apiClient.sendChatMessage(question, history, context);
      if (res.ok) return res.data;
      return {
        id: `e-${Date.now()}`,
        role: "assistant",
        content: "Sorry, I couldn't reach KrishiBot AI just now. Please try again.",
        timestamp: new Date().toISOString(),
      };
    },
    [isRealFarm, farm, language]
  );

  return { farm, isRealFarm, send };
}
