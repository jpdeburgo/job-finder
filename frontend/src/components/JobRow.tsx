"use client";

import { CheckIcon, PanelRightOpenIcon } from "lucide-react";
import { memo } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { TableCell, TableRow } from "@/components/ui/table";
import { formatDate, formatLocation, formatSalary, hasApplied, salaryPeriodNote, trackLabel } from "@/lib/jobs";
import type { Job, JobStatus } from "@/lib/types";
import { cn } from "@/lib/utils";
import { ExternalLink } from "./ExternalLink";
import { FitBadge } from "./FitBadge";
import { RemoteLabel } from "./RemoteLabel";
import { StatusSelect } from "./StatusSelect";

interface Props {
  job: Job;
  selected: boolean;
  busy: boolean;
  // Take the job's ID, so the dashboard can pass the same functions to every
  // row and a row whose job hasn't changed skips re-rendering (memo below).
  onSelect: (id: string) => void;
  onStatusChange: (id: string, status: JobStatus) => void;
}

/** One job in the tracker table. Memoized: typing in the search box or
 * paging doesn't re-render rows whose job, selection, and busy state are unchanged. */
export const JobRow = memo(function JobRow({ job, selected, busy, onSelect, onStatusChange }: Props) {
  const applied = hasApplied(job);
  const name = job.title ?? job.job_id;

  return (
    <TableRow data-testid={`job-row-${job.id}`} data-state={selected ? "selected" : undefined} className={cn(busy && "opacity-70")}>
      <TableCell className="w-10 pr-0">
        <Button
          variant="ghost"
          size="icon-sm"
          onClick={() => onSelect(job.id)}
          aria-label={`Show details for ${name}`}
          aria-pressed={selected}
        >
          <PanelRightOpenIcon className="text-muted-foreground" />
        </Button>
      </TableCell>

      <TableCell className="min-w-[240px] whitespace-normal">
        {job.url ? (
          <ExternalLink href={job.url} className="font-medium">
            {name}
          </ExternalLink>
        ) : (
          <span className="font-medium">{name}</span>
        )}
        <div className="text-muted-foreground mt-0.5 flex flex-wrap gap-x-2 text-xs">
          {job.company && <span className="text-foreground font-medium">{job.company}</span>}
          <span>{formatLocation(job)}</span>
          <RemoteLabel job={job} />
          {job.job_type && <span>{job.job_type}</span>}
        </div>
        {job.matches_skills === false && (
          <Badge
            variant="outline"
            className="mt-1 border-amber-300 text-amber-800 dark:border-amber-800 dark:text-amber-300"
            title={job.skills_mismatch_reason ? `No longer matches your skills: ${job.skills_mismatch_reason}` : undefined}
          >
            No longer matches your skills
          </Badge>
        )}
      </TableCell>

      <TableCell>
        <FitBadge job={job} />
      </TableCell>

      <TableCell>
        <Badge variant="secondary" title={job.track ?? undefined}>
          {trackLabel(job.track)}
        </Badge>
      </TableCell>

      <TableCell className="max-w-[260px] whitespace-normal">
        {job.matched_skills.length > 0 ? (
          <span className="text-xs" title={job.matched_skills.join(", ")}>
            <span className="font-semibold">{job.score ?? job.matched_skills.length}</span>{" "}
            <span className="text-muted-foreground">· {job.matched_skills.slice(0, 4).join(", ")}</span>
            {job.matched_skills.length > 4 && (
              <span className="text-muted-foreground"> +{job.matched_skills.length - 4}</span>
            )}
          </span>
        ) : (
          <span className="text-muted-foreground text-xs">—</span>
        )}
      </TableCell>

      <TableCell title={salaryPeriodNote(job) ?? undefined}>{formatSalary(job)}</TableCell>
      <TableCell className="text-muted-foreground">{formatDate(job.posted_date)}</TableCell>
      <TableCell className="text-muted-foreground">{formatDate(job.last_seen_at)}</TableCell>

      <TableCell>
        <StatusSelect jobId={job.id} value={job.status} disabled={busy} onChange={(status) => onStatusChange(job.id, status)} />
      </TableCell>

      <TableCell>
        {applied ? (
          <span
            className="inline-flex items-center gap-1 text-xs text-green-700 dark:text-green-400"
            title={job.applied_at ?? undefined}
          >
            <CheckIcon className="size-3.5" />
            {job.applied_at ? formatDate(job.applied_at) : "Applied"}
          </span>
        ) : (
          <Button
            variant="outline"
            size="sm"
            disabled={busy}
            onClick={() => onStatusChange(job.id, "applied")}
            className="text-green-700 dark:text-green-400"
          >
            Mark applied
          </Button>
        )}
      </TableCell>
    </TableRow>
  );
});
