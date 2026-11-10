import { InfoIcon, TriangleAlertIcon, XIcon } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import type { ReassessNotice } from "@/lib/reassess";

interface Props {
  notice: ReassessNotice;
  onDismiss?: () => void;
  /** Anything to add under the details, e.g. a link to the Jobs page. */
  children?: React.ReactNode;
}

/** What re-scoring the saved jobs against your skills did (or why it didn't happen). */
export function ReassessNoticeAlert({ notice, onDismiss, children }: Props) {
  const warning = notice.tone === "warning";
  return (
    <Alert
      data-testid="reassess-notice"
      role={warning ? "alert" : "status"}
      className={warning ? "border-amber-300 dark:border-amber-800" : undefined}
    >
      {warning ? <TriangleAlertIcon /> : <InfoIcon />}
      <AlertTitle className={onDismiss ? "pr-8" : undefined}>{notice.title}</AlertTitle>
      {(notice.details.length > 0 || children) && (
        <AlertDescription>
          {notice.details.map((line) => (
            <p key={line}>{line}</p>
          ))}
          {children}
        </AlertDescription>
      )}
      {onDismiss && (
        <Button variant="ghost" size="icon-xs" className="absolute top-2.5 right-2.5" aria-label="Dismiss" onClick={onDismiss}>
          <XIcon />
        </Button>
      )}
    </Alert>
  );
}
