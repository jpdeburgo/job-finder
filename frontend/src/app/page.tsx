import { AlertCircleIcon } from "lucide-react";
import { connection } from "next/server";
import { Suspense } from "react";
import { JobsDashboard } from "@/components/JobsDashboard";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Skeleton } from "@/components/ui/skeleton";
import { getJobStore } from "@/lib/store";
import type { Job, StoreInfo } from "@/lib/types";

export default function Page() {
  return (
    <Suspense fallback={<Loading />}>
      <Dashboard />
    </Suspense>
  );
}

/** Server component: reads the store at request time and hands the data to the client UI. */
async function Dashboard() {
  // Never prerender this at build time; the jobs change with every script run.
  await connection();
  const result = await loadJobs();
  if (!result.ok) return <StoreProblem message={result.message} />;
  return <JobsDashboard initialJobs={result.jobs} initialStore={result.store} />;
}

type LoadResult = { ok: true; jobs: Job[]; store: StoreInfo } | { ok: false; message: string };

/** Open the store and list jobs, turning configuration problems into a message instead of a crash. */
async function loadJobs(): Promise<LoadResult> {
  try {
    const store = getJobStore();
    return { ok: true, jobs: await store.listJobs(), store: store.info() };
  } catch (error) {
    return { ok: false, message: (error as Error).message };
  }
}

function Loading() {
  return (
    <div className="space-y-4" role="status" aria-label="Loading jobs">
      <Skeleton className="h-12 w-full" />
      <Skeleton className="h-7 w-2/3" />
      <Skeleton className="h-9 w-full" />
      <Skeleton className="h-64 w-full" />
    </div>
  );
}

function StoreProblem({ message }: { message: string }) {
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
