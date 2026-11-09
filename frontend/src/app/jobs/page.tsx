import type { Metadata } from "next";
import { connection } from "next/server";
import { Suspense } from "react";
import { JobsDashboard } from "@/components/JobsDashboard";
import { PageLoading, StoreProblem } from "@/components/PageStates";
import { loadJobs } from "@/lib/load-jobs";
import { filtersFromSearchParams } from "@/lib/overview";
import { paginationFromSearchParams } from "@/lib/pagination";

export const metadata: Metadata = { title: "Jobs" };

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

/**
 * The job tracker. `?status=applied` opens it filtered to one status (the home
 * screen links here); `?page=2&per_page=50` opens a page of the results.
 */
export default function JobsPage({ searchParams }: { searchParams: SearchParams }) {
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold tracking-tight">Jobs</h1>
      <Suspense fallback={<PageLoading label="Loading jobs" />}>
        <Tracker searchParams={searchParams} />
      </Suspense>
    </div>
  );
}

/** Server component: reads the store at request time and hands the data to the client UI. */
async function Tracker({ searchParams }: { searchParams: SearchParams }) {
  // Never prerender this at build time; the jobs change with every script run.
  await connection();
  const [result, params] = await Promise.all([loadJobs(), searchParams]);
  if (!result.ok) return <StoreProblem message={result.message} />;
  const { page, pageSize } = paginationFromSearchParams(params);
  return (
    <JobsDashboard
      initialJobs={result.jobs}
      initialStore={result.store}
      initialFilters={filtersFromSearchParams(params)}
      initialPage={page}
      initialPageSize={pageSize}
    />
  );
}
