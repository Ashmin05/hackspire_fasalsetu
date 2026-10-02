import type { Provenance } from "@/lib/api/types";
import { Wifi, Cpu, FlaskConical, Globe2 } from "lucide-react";

/** Provenance of one real backend number (satellite pass, CHIRPS, SMAP, ...). */
export interface LiveSource {
  /** Short dataset name shown in the badge, e.g. "Sentinel-2", "CHIRPS". */
  source: string;
  /** ISO date the value is valid for. */
  asOf: string | null;
  cloudPct?: number | null;
  /** Native resolution label from the backend, e.g. "~9-11 km regional (SMAP L4)".
   * Anything containing "regional" is flagged as regional in the badge. */
  resolution?: string;
  /** Leading word -- "Live" for refreshed data, e.g. "Soil map" for a static layer. */
  label?: string;
}

type SourceBadgeProps =
  | { provenance: Provenance; size?: "sm" | "md" }
  | { live: LiveSource; size?: "sm" | "md" }
  | { demo: true; size?: "sm" | "md" };

/**
 * Shows Live / Modelled / Estimate based on the provenance field.
 *
 * Logic:
 *   is_live: true                              → "Live"   (green)
 *   is_live: false + source satellite/weather  → "Modelled" (blue)
 *   source: model / manual / estimate          → "Estimate" (amber)
 *   source: market_feed                        → "Live"   (green) — market feeds are always live
 */
function getLabel(p: Provenance): { label: string; color: string; bg: string; Icon: typeof Wifi } {
  if (p.is_live || p.source === "market_feed") {
    return { label: "Live", color: "text-emerald-700", bg: "bg-emerald-50 border-emerald-200", Icon: Wifi };
  }
  if (p.source === "satellite" || p.source === "weather_api" || p.source === "soil_sensor") {
    return { label: "Modelled", color: "text-sky-700", bg: "bg-sky-50 border-sky-200", Icon: Cpu };
  }
  return { label: "Estimate", color: "text-amber-700", bg: "bg-amber-50 border-amber-200", Icon: FlaskConical };
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "2026-09-20" → "20 Sep". Formatted by hand: parsing the date string
 * directly never shifts a day across timezones, and newer browsers render
 * en-GB's short September as "Sept". */
export function formatPassDate(isoDate: string): string {
  const [, month, day] = isoDate.slice(0, 10).split("-").map(Number);
  return `${day} ${MONTHS[month - 1]}`;
}

export function formatCloudPct(cloudPct: number): string {
  return `${cloudPct < 10 ? cloudPct.toFixed(1) : cloudPct.toFixed(0)}%`;
}

/** "Live — Sentinel-2, 20 Sep, cloud 0.3%" */
export function liveSourceText(live: LiveSource): string {
  const parts = [live.source];
  if (live.asOf) parts.push(formatPassDate(live.asOf));
  if (live.cloudPct !== undefined && live.cloudPct !== null) parts.push(`cloud ${formatCloudPct(live.cloudPct)}`);
  return `${live.label ?? "Live"} — ${parts.join(", ")}`;
}

function sizeClasses(size: "sm" | "md") {
  return size === "sm" ? "text-xs px-2 py-0.5" : "text-sm px-3 py-1";
}

export default function SourceBadge(props: SourceBadgeProps) {
  const size = props.size ?? "sm";

  if ("demo" in props) {
    return (
      <span
        className={`inline-flex items-center gap-1 border rounded-full font-medium bg-amber-50 border-amber-200 text-amber-700 whitespace-nowrap ${sizeClasses(size)}`}
        title="Sample values for a demo farm — sign in and register a farm to see live satellite data"
      >
        <FlaskConical className={size === "sm" ? "w-3 h-3" : "w-4 h-4"} />
        Demo data
      </span>
    );
  }

  if ("live" in props) {
    const { live } = props;
    const isRegional = !!live.resolution && /regional/i.test(live.resolution);
    return (
      <span
        className={`inline-flex items-center gap-1 border rounded-xl font-medium max-w-full leading-snug ${
          isRegional ? "bg-sky-50 border-sky-200 text-sky-700" : "bg-emerald-50 border-emerald-200 text-emerald-700"
        } ${sizeClasses(size)}`}
        title={live.resolution ? `${live.source} · native resolution ${live.resolution}` : live.source}
      >
        {isRegional ? (
          <Globe2 className={`${size === "sm" ? "w-3 h-3" : "w-4 h-4"} flex-shrink-0`} />
        ) : (
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse flex-shrink-0" />
        )}
        <span>
          {liveSourceText(live)}
          {isRegional && <span className="opacity-70"> · regional</span>}
        </span>
      </span>
    );
  }

  const { provenance } = props;
  const { label, color, bg, Icon } = getLabel(provenance);
  const isLive = label === "Live";

  return (
    <span
      className={`inline-flex items-center gap-1 border rounded-full font-medium ${bg} ${color} ${sizeClasses(size)}`}
      title={`Source: ${provenance.provider ?? provenance.source} · Last updated: ${new Date(provenance.fetched_at).toLocaleString("en-IN")}`}
    >
      {isLive ? (
        <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
      ) : (
        <Icon className={size === "sm" ? "w-3 h-3" : "w-4 h-4"} />
      )}
      {label}
      {provenance.confidence !== undefined && (
        <span className="opacity-60 ml-0.5">({Math.round(provenance.confidence * 100)}%)</span>
      )}
    </span>
  );
}
