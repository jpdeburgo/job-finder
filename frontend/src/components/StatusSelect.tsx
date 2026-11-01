"use client";

import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { JOB_STATUSES, STATUS_INFO, type JobStatus } from "@/lib/types";
import { cn } from "@/lib/utils";
import { statusClasses } from "./StatusBadge";

interface Props {
  jobId: string;
  value: string;
  disabled?: boolean;
  onChange: (status: JobStatus) => void;
}

/** Inline status dropdown for a table row, coloured like the status badge. */
export function StatusSelect({ jobId, value, disabled = false, onChange }: Props) {
  const known = (JOB_STATUSES as readonly string[]).includes(value);
  return (
    <Select value={known ? value : undefined} disabled={disabled} onValueChange={(next) => onChange(next as JobStatus)}>
      <SelectTrigger
        size="sm"
        aria-label={`Status for job ${jobId}`}
        className={cn("w-[130px] rounded-full text-xs font-medium", statusClasses(value))}
      >
        {/* Explicit children render on the server too; Radix only discovers
            item text after hydration, which would leave SSR output blank. */}
        <SelectValue placeholder={value || "unknown"}>{known ? STATUS_INFO[value as JobStatus].label : value}</SelectValue>
      </SelectTrigger>
      <SelectContent>
        {JOB_STATUSES.map((status) => (
          <SelectItem key={status} value={status} title={STATUS_INFO[status].hint}>
            {STATUS_INFO[status].label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
