"use client";

import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { REMOTE_STATUS_INFO, remoteStatus } from "@/lib/jobs";
import { WORK_ARRANGEMENTS, WORK_ARRANGEMENT_LABELS, type Job, type WorkArrangement } from "@/lib/types";

// Radix Select needs a non-empty value for "no override".
const SITE = "site";

interface Props {
  job: Pick<Job, "id" | "work_arrangement" | "site_is_remote">;
  disabled?: boolean;
  /** null: go back to what the site says. */
  onChange: (value: WorkArrangement | null) => void;
}

/**
 * How the job is really worked, for when the site gets it wrong: a posting
 * flagged remote that is on-site or hybrid (or the other way round). Your
 * choice overrides the site's in filters and labels, and searches never undo it.
 */
export function WorkArrangementSelect({ job, disabled = false, onChange }: Props) {
  const siteLabel = REMOTE_STATUS_INFO[remoteStatus({ is_remote: job.site_is_remote })].label;
  const siteOption = `As the site says (${siteLabel})`;
  const value = job.work_arrangement ?? SITE;
  return (
    <Select
      value={value}
      disabled={disabled}
      onValueChange={(next) => onChange(next === SITE ? null : (next as WorkArrangement))}
    >
      <SelectTrigger size="sm" aria-label={`Work arrangement for job ${job.id}`} className="w-[220px] text-xs">
        <SelectValue>{job.work_arrangement ? WORK_ARRANGEMENT_LABELS[job.work_arrangement] : siteOption}</SelectValue>
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={SITE}>{siteOption}</SelectItem>
        {WORK_ARRANGEMENTS.map((arrangement) => (
          <SelectItem key={arrangement} value={arrangement}>
            {WORK_ARRANGEMENT_LABELS[arrangement]}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
