import { Badge } from "@/components/ui/badge";
import { STATUS_INFO, isJobStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

/** Tailwind colour classes per status, shared by badges, chips, and the select. */
export const STATUS_STYLES: Record<string, string> = {
  unemailed: "border-amber-300 bg-amber-100 text-amber-900 dark:border-amber-800 dark:bg-amber-950/60 dark:text-amber-200",
  emailed: "border-sky-300 bg-sky-100 text-sky-900 dark:border-sky-800 dark:bg-sky-950/60 dark:text-sky-200",
  applied: "border-green-300 bg-green-100 text-green-900 dark:border-green-800 dark:bg-green-950/60 dark:text-green-200",
  skipped: "border-zinc-300 bg-zinc-100 text-zinc-700 dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-300",
  interviewing:
    "border-violet-300 bg-violet-100 text-violet-900 dark:border-violet-800 dark:bg-violet-950/60 dark:text-violet-200",
  rejected: "border-rose-300 bg-rose-100 text-rose-900 dark:border-rose-800 dark:bg-rose-950/60 dark:text-rose-200",
  offer: "border-emerald-400 bg-emerald-200 text-emerald-950 dark:border-emerald-700 dark:bg-emerald-900/60 dark:text-emerald-100",
  seen: "border-zinc-200 bg-zinc-50 text-zinc-500 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-400",
};

const UNKNOWN_STYLE = "border-zinc-300 bg-zinc-100 text-zinc-600 dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-300";

export function statusClasses(status: string): string {
  return STATUS_STYLES[status] ?? UNKNOWN_STYLE;
}

export function statusLabel(status: string): string {
  return isJobStatus(status) ? STATUS_INFO[status].label : status;
}

export function StatusBadge({ status, className }: { status: string; className?: string }) {
  return (
    <Badge
      variant="outline"
      className={cn("rounded-full", statusClasses(status), className)}
      title={isJobStatus(status) ? STATUS_INFO[status].hint : undefined}
    >
      {statusLabel(status)}
    </Badge>
  );
}
