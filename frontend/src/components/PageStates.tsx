import { AlertCircleIcon } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Skeleton } from "@/components/ui/skeleton";

/** Placeholder while a page reads the store. */
export function PageLoading({ label }: { label: string }) {
  return (
    <div className="space-y-4" role="status" aria-label={label}>
      <Skeleton className="h-12 w-full" />
      <Skeleton className="h-7 w-2/3" />
      <Skeleton className="h-9 w-full" />
      <Skeleton className="h-64 w-full" />
    </div>
  );
}

/** Shown instead of a page when the job store can't be opened. */
export function StoreProblem({ message }: { message: string }) {
  return (
    <Alert variant="destructive">
      <AlertCircleIcon />
      <AlertTitle>Could not open the job store</AlertTitle>
      <AlertDescription>
        <p className="font-mono text-xs whitespace-pre-wrap">{message}</p>
        <p>
          Check <code>IG_STATE_BACKEND</code> and the Firebase variables in <code>frontend/.env.local</code> or{" "}
          <code>backend/.env</code>; see <code>frontend/README.md</code>.
        </p>
      </AlertDescription>
    </Alert>
  );
}
