"use client";



import { useState, useRef, useEffect, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import AppLayout from "@/components/AppLayout";
import { isAuthenticated } from "@/lib/auth/auth-client";
import { formatPassDate } from "@/components/SourceBadge";
import { useKrishiBot, type KrishiBotMessage } from "@/lib/hooks/useKrishiBot";
import {
  Brain, Send, Sprout,
  Loader2, RefreshCw
} from "lucide-react";

function ChatContent() {
  const searchParams = useSearchParams();
  const prefillQ = searchParams.get("q") ?? "";
  const fieldId = searchParams.get("fieldId") ?? undefined;
  const farmId = searchParams.get("farm") ?? undefined;
  const { farm, isRealFarm, send } = useKrishiBot(farmId, "en");

  const [messages, setMessages] = useState<KrishiBotMessage[]>([
    {
      id: "welcome",
      role: "assistant",
      content:
        "Namaste! 🌾 I'm KrishiBot, your AI farming assistant.\n\nI answer questions about your farm using its own data:\n• Satellite crop health (NDVI) and stress alerts\n• Irrigation timing and amount\n• Weather forecast for your field\n• Mandi prices and the sell-or-hold suggestion\n\nAsk in English, বাংলা (Bengali), or हिंदी (Hindi).",
      timestamp: new Date().toISOString(),
    },
  ]);
  const [input, setInput] = useState(prefillQ);
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function sendMessage(text?: string) {
    const msg = (text ?? input).trim();
    if (!msg || loading) return;

    const userMsg: KrishiBotMessage = {
      id: `u-${Date.now()}`,
      role: "user",
      content: msg,
      timestamp: new Date().toISOString(),
    };

    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setLoading(true);

    try {
      const reply = await send(msg, messages, { field_id: fieldId, farm_id: farm?.id, crop: farm?.crop });
      setMessages((prev) => [...prev, reply]);
    } finally {
      setLoading(false);
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  }

  function resetChat() {
    setMessages([
      {
        id: "welcome-" + Date.now(),
        role: "assistant",
        content: "Chat reset. How can I assist you with your crops today? (English, বাংলা, हिंदी)",
        timestamp: new Date().toISOString(),
      },
    ]);
    setInput("");
  }

  return (
    <AppLayout>
      <div className="max-w-4xl mx-auto h-[calc(100vh-10rem)] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between mb-4 flex-shrink-0">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-farm-green rounded-xl flex items-center justify-center">
              <Brain className="w-5 h-5 text-white" />
            </div>
            <div>
              <h1 className="font-bold text-farm-dark text-lg">KrishiBot AI</h1>
              <p className="text-xs text-farm-muted">
                <span className="inline-flex items-center gap-1">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
                  Online · Powered by FasalSetu AI
                </span>
                {fieldId && <span className="ml-2 bg-farm-green-light text-farm-green px-2 py-0.5 rounded-full">Field context active</span>}
                {isRealFarm && farm && (
                  <span className="ml-2 bg-farm-green-light text-farm-green px-2 py-0.5 rounded-full">Answering for: {farm.name}</span>
                )}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={resetChat}
              className="p-2 rounded-lg border border-farm-border-color hover:bg-farm-green-light hover:border-farm-green text-farm-muted hover:text-farm-green transition-all"
              title="Reset chat"
            >
              <RefreshCw className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Message area */}
        <div className="flex-1 overflow-y-auto bg-white rounded-2xl border border-farm-border-color p-4 space-y-4 min-h-0">
          {messages.map((msg) => (
            <div
              key={msg.id}
              className={`flex gap-3 ${msg.role === "user" ? "flex-row-reverse" : ""}`}
            >
              {/* Avatar */}
              <div className={`w-8 h-8 rounded-xl flex items-center justify-center flex-shrink-0 ${
                msg.role === "assistant"
                  ? "bg-farm-green"
                  : "bg-purple-100"
              }`}>
                {msg.role === "assistant" ? (
                  <Sprout className="w-4 h-4 text-white" />
                ) : (
                  <span className="text-purple-700 text-xs font-bold">R</span>
                )}
              </div>

              {/* Bubble */}
              <div
                className={`max-w-[80%] px-4 py-3 rounded-2xl text-sm leading-relaxed whitespace-pre-wrap ${
                  msg.role === "user"
                    ? "bg-farm-green text-white rounded-tr-sm"
                    : "bg-farm-gray text-farm-dark rounded-tl-sm"
                }`}
              >
                {msg.content}
                {msg.actionPoints && msg.actionPoints.length > 0 && (
                  <ul className="mt-2 list-disc list-inside space-y-0.5 text-sm">
                    {msg.actionPoints.map((point, i) => <li key={i}>{point}</li>)}
                  </ul>
                )}
                {msg.warnings && msg.warnings.length > 0 && (
                  <div className="mt-2 space-y-1">
                    {msg.warnings.map((warning, i) => (
                      <p key={i} className="text-xs font-semibold text-amber-800 bg-amber-100 rounded-lg px-2 py-1">
                        ⚠ {warning}
                      </p>
                    ))}
                  </div>
                )}
                {msg.sources && msg.sources.length > 0 && (
                  <p className="mt-2 pt-2 border-t border-farm-border-color/60 text-xs text-farm-muted">
                    Based on: {msg.sources.map((s) => (s.as_of ? `${s.label} ${formatPassDate(s.as_of)}` : s.label)).join(", ")}
                  </p>
                )}
                <p className={`text-xs mt-1.5 ${msg.role === "user" ? "text-white/60 text-right" : "text-farm-muted"}`}>
                  {new Date(msg.timestamp).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" })}
                </p>
              </div>
            </div>
          ))}

          {/* Typing indicator */}
          {loading && (
            <div className="flex gap-3">
              <div className="w-8 h-8 rounded-xl bg-farm-green flex items-center justify-center flex-shrink-0">
                <Sprout className="w-4 h-4 text-white" />
              </div>
              <div className="bg-farm-gray rounded-2xl rounded-tl-sm px-4 py-3 flex items-center gap-2 text-farm-muted">
                <Loader2 className="w-4 h-4 animate-spin" />
                <span className="text-sm">KrishiBot is thinking…</span>
              </div>
            </div>
          )}

          <div ref={bottomRef} />
        </div>

        {/* Input box */}
        <div className="flex-shrink-0 pt-3">
          <div className="flex gap-2 items-end bg-white border border-farm-border-color rounded-2xl px-4 py-3 focus-within:border-farm-green focus-within:ring-1 focus-within:ring-farm-green transition-all">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Ask about your crop health, irrigation, weather or mandi price… (Enter to send)"
              rows={2}
              className="flex-1 resize-none text-sm text-farm-dark placeholder-farm-muted focus:outline-none bg-transparent leading-relaxed"
            />
            <div className="flex items-center gap-2 flex-shrink-0">
              <button
                onClick={() => sendMessage()}
                disabled={!input.trim() || loading}
                className="w-9 h-9 bg-farm-green rounded-xl flex items-center justify-center text-white hover:bg-farm-green-dark transition-all disabled:opacity-40 disabled:cursor-not-allowed"
              >
                {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
              </button>
            </div>
          </div>
          <p className="text-center text-xs text-farm-muted mt-2">
            KrishiBot answers from your farm&apos;s own satellite, weather, irrigation and mandi data.
          </p>
        </div>
      </div>
    </AppLayout>
  );
}

// KrishiBot requires a signed-in account (see also KrishiBotWidget.tsx, which
// shows a sign-in prompt for the floating widget) -- this gate covers every
// other way to land on /ai-chat: the home page CTAs, the footer link, or
// typing the URL directly.
function AuthGate({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (isAuthenticated()) {
      setReady(true);
    } else {
      router.replace("/login");
    }
  }, [router]);

  if (!ready) {
    return (
      <AppLayout>
        <div className="flex items-center justify-center h-64 text-farm-muted">Redirecting to sign in…</div>
      </AppLayout>
    );
  }
  return <>{children}</>;
}

export default function AiChatPage() {
  return (
    <AuthGate>
      <Suspense fallback={<AppLayout><div className="flex items-center justify-center h-64 text-farm-muted">Loading…</div></AppLayout>}>
        <ChatContent />
      </Suspense>
    </AuthGate>
  );
}
