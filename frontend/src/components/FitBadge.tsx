import { Badge } from "@/components/ui/badge";
import { fitLabel, type FitLabel } from "@/lib/jobs";
import type { Job } from "@/lib/types";
import { cn } from "@/lib/utils";

const FIT_STYLES: Record<FitLabel, string> = {
  Strong: "border-green-300 bg-green-100 text-green-900 dark:border-green-800 dark:bg-green-950/60 dark:text-green-200",
  Good: "border-sky-300 bg-sky-100 text-sky-900 dark:border-sky-800 dark:bg-sky-950/60 dark:text-sky-200",
  Fair: "border-amber-300 bg-amber-100 text-amber-900 dark:border-amber-800 dark:bg-amber-950/60 dark:text-amber-200",
  Weak: "border-zinc-300 bg-zinc-100 text-zinc-700 dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-300",
};

/**
 * "82 · Strong": how well a job fits you (backend/job_fit.py). Hover for the
 * reasons. Jobs saved before the fit score existed show a dash.
 */
export function FitBadge({ job, className }: { job: Pick<Job, "fit_score" | "fit_reasons">; className?: string }) {
  const label = fitLabel(job.fit_score);
  if (job.fit_score == null || label == null) {
    return (
      <span className="text-muted-foreground text-xs" title="Not scored: saved before the fit score existed">
        —
      </span>
    );
  }
  return (
    <Badge
      variant="outline"
      className={cn("rounded-full tabular-nums", FIT_STYLES[label], className)}
      title={job.fit_reasons.length ? job.fit_reasons.join("\n") : undefined}
      aria-label={`Fit ${job.fit_score} of 100, ${label}`}
    >
      {job.fit_score} · {label}
    </Badge>
  );
}
