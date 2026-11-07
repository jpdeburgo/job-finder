import { connection } from "next/server";
import { Suspense } from "react";
import { HomeOverview } from "@/components/HomeOverview";
import { PageLoading, StoreProblem } from "@/components/PageStates";
import { loadJobs } from "@/lib/load-jobs";

/** The home screen. The job tracker itself lives at /jobs. */
export default function HomePage() {
  return (
    <Suspense fallback={<PageLoading label="Loading overview" />}>
      <Overview />
    </Suspense>
  );
}

/** Server component: reads the store at request time and hands the data to the client UI. */
async function Overview() {
  // Never prerender this at build time; the jobs change with every script run.
  await connection();
  const result = await loadJobs();
  if (!result.ok) return <StoreProblem message={result.message} />;
  return <HomeOverview jobs={result.jobs} store={result.store} />;
}
