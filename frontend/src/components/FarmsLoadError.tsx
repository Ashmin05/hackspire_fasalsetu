"use client";

import { AlertTriangle, RefreshCw } from "lucide-react";


export default function FarmsLoadError({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="max-w-md mx-auto text-center py-20 space-y-4" role="alert">
      <div className="w-14 h-14 rounded-2xl bg-red-50 flex items-center justify-center mx-auto">
        <AlertTriangle className="w-7 h-7 text-red-600" />
      </div>
      <h2 className="text-xl font-bold text-farm-dark">Couldn&apos;t load your farms</h2>
      <p className="text-farm-muted text-sm">{message}</p>
      <button
        onClick={onRetry}
        className="inline-flex items-center gap-2 bg-farm-green text-white px-5 py-2.5 rounded-xl font-semibold hover:bg-farm-green-dark transition-all shadow-sm"
      >
        <RefreshCw className="w-4 h-4" /> Try again
      </button>
    </div>
  );
}
