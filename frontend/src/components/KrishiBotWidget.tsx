"use client";


import { useState, useRef, useEffect } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Brain, Send, X, Sprout, Loader2, Maximize2, LogIn } from "lucide-react";
import { isAuthenticated } from "@/lib/auth/auth-client";
import { formatPassDate } from "@/components/SourceBadge";
import { useKrishiBot, type KrishiBotMessage } from "@/lib/hooks/useKrishiBot";

const WELCOME: KrishiBotMessage = {
  id: "welcome",
  role: "assistant",
  content:
    "Namaste! 🌾 I'm KrishiBot, your AI farming assistant. Ask about your farm's satellite crop health, irrigation timing, weather, or mandi prices.",
  timestamp: new Date().toISOString(),
};

export default function KrishiBotWidget() {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const [authed, setAuthed] = useState(false);
  const [messages, setMessages] = useState<KrishiBotMessage[]>([WELCOME]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const { send } = useKrishiBot(undefined, "en");

  useEffect(() => {
    setAuthed(isAuthenticated());
  }, [pathname]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, open]);

  if (pathname === "/login" || pathname === "/register") {
    return null;
  }

  async function handleSend(text?: string) {
    const msg = (text ?? input).trim();
    if (!msg || loading) return;
    const userMsg: KrishiBotMessage = { id: `u-${Date.now()}`, role: "user", content: msg, timestamp: new Date().toISOString() };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setLoading(true);
    try {
      const reply = await send(msg, messages);
      setMessages((prev) => [...prev, reply]);
    } finally {
      setLoading(false);
    }
  }

  function handleKey(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter") { e.preventDefault(); handleSend(); }
  }

  return (
    <div className="fixed bottom-6 right-6 z-50 flex flex-col items-end gap-3">
      {/* Signed-out: prompt to sign in instead of the real chat */}
      {open && !authed && (
        <div className="w-80 sm:w-96 bg-white rounded-2xl shadow-2xl border border-farm-border-color overflow-hidden flex flex-col">
          <div className="bg-farm-green px-4 py-3 flex items-center justify-between flex-shrink-0">
            <div className="flex items-center gap-2">
              <div className="w-7 h-7 bg-white/20 rounded-lg flex items-center justify-center">
                <Brain className="w-4 h-4 text-white" />
              </div>
              <p className="text-white font-bold text-sm">KrishiBot AI</p>
            </div>
            <button
              onClick={() => setOpen(false)}
              className="p-1.5 rounded-lg bg-white/10 hover:bg-white/20 text-white transition-colors"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
          <div className="p-6 flex flex-col items-center text-center gap-3">
            <div className="w-12 h-12 rounded-2xl bg-farm-green-light flex items-center justify-center">
              <Sprout className="w-6 h-6 text-farm-green" />
            </div>
            <p className="text-sm font-bold text-farm-dark">Sign in to chat with KrishiBot AI</p>
            <p className="text-xs text-farm-muted">
              Create a free account or sign in to ask about your crop health, irrigation, weather, and mandi prices.
            </p>
            <div className="flex gap-2 w-full mt-1">
              <Link
                href="/login"
                onClick={() => setOpen(false)}
                className="flex-1 flex items-center justify-center gap-1.5 bg-farm-green text-white text-xs font-semibold py-2.5 rounded-xl hover:bg-farm-green-dark transition-all"
              >
                <LogIn className="w-3.5 h-3.5" /> Sign In
              </Link>
              <Link
                href="/register"
                onClick={() => setOpen(false)}
                className="flex-1 flex items-center justify-center text-xs font-semibold py-2.5 rounded-xl border border-farm-border-color text-farm-dark hover:border-farm-green hover:text-farm-green transition-all"
              >
                Create Account
              </Link>
            </div>
          </div>
        </div>
      )}

      {/* Chat Box */}
      {open && authed && (
        <div className="w-80 sm:w-96 bg-white rounded-2xl shadow-2xl border border-farm-border-color overflow-hidden flex flex-col"
          style={{ height: "440px" }}>
          {/* Header */}
          <div className="bg-farm-green px-4 py-3 flex items-center justify-between flex-shrink-0">
            <div className="flex items-center gap-2">
              <div className="w-7 h-7 bg-white/20 rounded-lg flex items-center justify-center">
                <Brain className="w-4 h-4 text-white" />
              </div>
              <div>
                <p className="text-white font-bold text-sm">KrishiBot AI</p>
                <p className="text-white/70 text-xs flex items-center gap-1">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-300 animate-pulse inline-block" />
                  Online
                </p>
              </div>
            </div>
            <div className="flex items-center gap-1.5">
              <Link
                href="/ai-chat"
                onClick={() => setOpen(false)}
                title="Open full KrishiBot AI page"
                className="p-1.5 rounded-lg bg-white/10 hover:bg-white/20 text-white transition-colors"
              >
                <Maximize2 className="w-3.5 h-3.5" />
              </Link>
              <button
                onClick={() => setOpen(false)}
                className="p-1.5 rounded-lg bg-white/10 hover:bg-white/20 text-white transition-colors"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
          </div>

          {/* Messages */}
          <div className="flex-1 overflow-y-auto p-3 space-y-3 bg-farm-gray/30">
            {messages.map((msg) => (
              <div key={msg.id} className={`flex gap-2 ${msg.role === "user" ? "flex-row-reverse" : ""}`}>
                <div className={`w-7 h-7 rounded-xl flex items-center justify-center flex-shrink-0 ${msg.role === "assistant" ? "bg-farm-green" : "bg-purple-100"}`}>
                  {msg.role === "assistant"
                    ? <Sprout className="w-3.5 h-3.5 text-white" />
                    : <span className="text-purple-700 text-xs font-bold">Y</span>}
                </div>
                <div className={`max-w-[80%] px-3 py-2 rounded-2xl text-xs leading-relaxed whitespace-pre-wrap break-words ${msg.role === "user"
                    ? "bg-farm-green text-white rounded-tr-sm"
                    : "bg-white text-farm-dark rounded-tl-sm shadow-sm border border-farm-border-color"
                  }`}>
                  {msg.content}
                  {msg.actionPoints && msg.actionPoints.length > 0 && (
                    <ul className="mt-1.5 list-disc list-inside space-y-0.5">
                      {msg.actionPoints.map((point, i) => <li key={i}>{point}</li>)}
                    </ul>
                  )}
                  {msg.warnings && msg.warnings.length > 0 && (
                    <div className="mt-1.5 space-y-1">
                      {msg.warnings.map((warning, i) => (
                        <p key={i} className="text-[11px] font-semibold text-amber-800 bg-amber-100 rounded-lg px-2 py-1">
                          ⚠ {warning}
                        </p>
                      ))}
                    </div>
                  )}
                  {msg.sources && msg.sources.length > 0 && (
                    <p className="mt-1.5 pt-1.5 border-t border-farm-border-color text-[10px] text-farm-muted">
                      Based on: {msg.sources.map((s) => (s.as_of ? `${s.label} ${formatPassDate(s.as_of)}` : s.label)).join(", ")}
                    </p>
                  )}
                </div>
              </div>
            ))}
            {loading && (
              <div className="flex gap-2">
                <div className="w-7 h-7 rounded-xl bg-farm-green flex items-center justify-center flex-shrink-0">
                  <Sprout className="w-3.5 h-3.5 text-white" />
                </div>
                <div className="bg-white rounded-2xl rounded-tl-sm px-3 py-2 flex items-center gap-1.5 text-farm-muted border border-farm-border-color shadow-sm">
                  <Loader2 className="w-3 h-3 animate-spin" />
                  <span className="text-xs">KrishiBot AI is thinking…</span>
                </div>
              </div>
            )}
            <div ref={bottomRef} />
          </div>

          {/* Input */}
          <div className="flex-shrink-0 p-3 bg-white border-t border-farm-border-color">
            <div className="flex gap-2 items-center bg-farm-gray rounded-xl px-3 py-2 focus-within:ring-1 focus-within:ring-farm-green focus-within:bg-white transition-all">
              <input
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKey}
                placeholder="Ask KrishiBot AI…"
                className="flex-1 text-xs text-farm-dark placeholder-farm-muted bg-transparent focus:outline-none"
              />
              <button
                onClick={() => handleSend()}
                disabled={!input.trim() || loading}
                className="w-7 h-7 bg-farm-green rounded-lg flex items-center justify-center text-white hover:bg-farm-green-dark transition-all disabled:opacity-40"
              >
                {loading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Send className="w-3.5 h-3.5" />}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Floating Circle Button */}
      <button
        onClick={() => setOpen((prev) => !prev)}
        title="KrishiBot AI Assistant"
        className={`w-14 h-14 rounded-full flex items-center justify-center shadow-lg transition-all duration-300 hover:scale-110 ${open
            ? "bg-farm-dark text-white rotate-0"
            : "bg-farm-green text-white"
          }`}
      >
        {open ? <X className="w-5 h-5" /> : <Brain className="w-6 h-6" />}
      </button>
    </div>
  );
}
