import { Badge } from "@/components/ui/badge";
import { REMOTE_STATUS_INFO, remoteStatus, workArrangementLabel, type RemoteStatus } from "@/lib/jobs";
import type { Job } from "@/lib/types";
import { cn } from "@/lib/utils";

const TEXT_STYLES: Record<RemoteStatus, string> = {
  remote: "text-green-700 dark:text-green-400",
  unmarked: "text-amber-700 dark:text-amber-400",
  not_remote: "text-muted-foreground",
};

/**
 * "Remote", "Remote not stated", or "Not remote" (or "On-site (you)" when
 * you've said how the job is worked): plain text in table rows, an outlined
 * badge in the details drawer. The hint explains it on hover.
 */
export function RemoteLabel({
  job,
  badge = false,
}: {
  job: Pick<Job, "is_remote"> & Partial<Pick<Job, "work_arrangement">>;
  badge?: boolean;
}) {
  const status = remoteStatus(job);
  const yours = workArrangementLabel({ work_arrangement: job.work_arrangement ?? null });
  const label = yours ?? REMOTE_STATUS_INFO[status].label;
  const hint = yours ? "You marked how this job is worked; it overrides what the site says." : REMOTE_STATUS_INFO[status].hint;
  if (badge) {
    return (
      <Badge variant="outline" className={TEXT_STYLES[status]} title={hint}>
        {label}
      </Badge>
    );
  }
  return (
    <span className={cn(TEXT_STYLES[status])} title={hint}>
      {label}
    </span>
  );
}
