"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

// Since Farm == Field, each farm is directly analyzed via Satellite Analysis
export default function FarmDetailPage({ params }: { params: { farmId: string } }) {
  const router = useRouter();

  useEffect(() => {
    router.replace(`/satellite?farm=${params.farmId}`);
  }, [params.farmId, router]);

  return (
    <div className="min-h-screen flex items-center justify-center text-farm-muted text-sm">
      <div className="flex flex-col items-center gap-2">
        <div className="w-6 h-6 border-2 border-farm-green border-t-transparent rounded-full animate-spin" />
        <span>Navigating to farm satellite analysis...</span>
      </div>
    </div>
  );
}
