import { Badge } from "@/components/ui/badge";
import { REMOTE_STATUS_INFO, remoteStatus, type RemoteStatus } from "@/lib/jobs";
import type { Job } from "@/lib/types";
import { cn } from "@/lib/utils";

const TEXT_STYLES: Record<RemoteStatus, string> = {
  remote: "text-green-700 dark:text-green-400",
  unmarked: "text-amber-700 dark:text-amber-400",
  not_remote: "text-muted-foreground",
};

/**
 * "Remote", "Remote not stated", or "Not remote": plain text in table rows,
 * an outlined badge in the details drawer. The hint explains it on hover.
 */
export function RemoteLabel({ job, badge = false }: { job: Pick<Job, "is_remote">; badge?: boolean }) {
  const status = remoteStatus(job);
  const { label, hint } = REMOTE_STATUS_INFO[status];
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
