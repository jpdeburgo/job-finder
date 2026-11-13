"use client";

import { AlertCircleIcon } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Sheet } from "@/components/ui/sheet";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { fetchJobs, patchJob, reassessJobs } from "@/lib/client";
import {
  DEFAULT_FILTERS,
  countByStatus,
  distinctCompanies,
  distinctRemoteStatuses,
  distinctSkills,
  distinctTracks,
  filterJobs,
  sortJobs,
  type JobFilters,
  type SortKey,
} from "@/lib/jobs";
import { DEFAULT_PAGE_SIZE, paginate, type PageSize } from "@/lib/pagination";
import { describeReassess, reassessProblem, type ReassessNotice } from "@/lib/reassess";
import { JOB_STATUSES, type Job, type JobPatch, type JobStatus, type StoreInfo, type WorkArrangement } from "@/lib/types";
import { cn } from "@/lib/utils";
import { FilterBar } from "./FilterBar";
import { JobDetails } from "./JobDetails";
import { JobRow } from "./JobRow";
import { Pagination } from "./Pagination";
import { ReassessNoticeAlert } from "./ReassessNoticeAlert";
import { RunSearchPanel } from "./RunSearchPanel";
import { statusClasses, statusLabel } from "./StatusBadge";
import { StoreBanner } from "./StoreBanner";

interface Props {
  initialJobs: Job[];
  initialStore: StoreInfo;
  /** Starting filters, e.g. from `/jobs?status=applied`. */
  initialFilters?: JobFilters;
  /** Starting page and page size, e.g. from `/jobs?page=2&per_page=50`. */
  initialPage?: number;
  initialPageSize?: PageSize;
}

const HEADERS = ["", "Job", "Fit", "Track", "Skills", "Salary", "Posted", "Last seen", "Status", "Applied"];

/** The whole interactive dashboard: banner, summary, filters, table, and details drawer. */
export function JobsDashboard({
  initialJobs,
  initialStore,
  initialFilters = DEFAULT_FILTERS,
  initialPage = 1,
  initialPageSize = DEFAULT_PAGE_SIZE,
}: Props) {
  const [jobs, setJobs] = useState<Job[]>(initialJobs);
  const [store, setStore] = useState<StoreInfo>(initialStore);
  const [filters, setFilters] = useState<JobFilters>(initialFilters);
  // The sort, then what orders its ties ("Then by"), if anything.
  const [sort, setSort] = useState<SortKey[]>(["last_seen"]);
  const [page, setPage] = useState(initialPage);
  const [pageSize, setPageSize] = useState<PageSize>(initialPageSize);
  const tableRef = useRef<HTMLDivElement>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [busyIds, setBusyIds] = useState<Set<string>>(new Set());
  const [refreshing, setRefreshing] = useState(false);
  const [reassessing, setReassessing] = useState(false);
  const [notice, setNotice] = useState<ReassessNotice | null>(null);
  const [error, setError] = useState<string | null>(null);

  const counts = useMemo(() => countByStatus(jobs), [jobs]);
  const companies = useMemo(() => distinctCompanies(jobs), [jobs]);
  const remoteStatuses = useMemo(() => distinctRemoteStatuses(jobs), [jobs]);
  const tracks = useMemo(() => distinctTracks(jobs), [jobs]);
  const skillOptions = useMemo(() => distinctSkills(jobs), [jobs]);
  const visible = useMemo(() => sortJobs(filterJobs(jobs, filters), sort), [jobs, filters, sort]);
  // The page is clamped here, so a page that emptied (say, the last job on it
  // changed status and left the filter) shows the last page that has jobs.
  const current = useMemo(() => paginate(visible, page, pageSize), [visible, page, pageSize]);
  const selected = useMemo(() => jobs.find((job) => job.id === selectedId) ?? null, [jobs, selectedId]);

  // Keep ?status=, ?page=, and ?per_page= in the address bar in step with the
  // view, so a reload or a shared link opens the same view (the home screen
  // links here). Defaults are left out.
  useEffect(() => {
    const url = new URL(window.location.href);
    const set = (name: string, value: string | null) =>
      value === null ? url.searchParams.delete(name) : url.searchParams.set(name, value);
    set("status", filters.status === "all" ? null : filters.status);
    set("page", current.page === 1 ? null : String(current.page));
    set("per_page", pageSize === DEFAULT_PAGE_SIZE ? null : String(pageSize));
    if (url.href !== window.location.href) window.history.replaceState(window.history.state, "", url);
  }, [filters.status, current.page, pageSize]);

  // A different filter, sort, or page size starts again at page 1.
  const updateFilters = (update: JobFilters | ((current: JobFilters) => JobFilters)) => {
    setFilters(update);
    setPage(1);
  };
  const updateSort = (next: SortKey[]) => {
    setSort(next);
    setPage(1);
  };
  const updatePageSize = (next: PageSize) => {
    setPageSize(next);
    setPage(1);
  };
  const goToPage = (next: number) => {
    setPage(next);
    // Back to the top of the table if it has scrolled out of view.
    const top = tableRef.current?.getBoundingClientRect().top;
    if (top !== undefined && top < 0) tableRef.current?.scrollIntoView?.({ block: "start", behavior: "smooth" });
  };

  const setBusy = (id: string, busy: boolean) =>
    setBusyIds((current) => {
      const next = new Set(current);
      if (busy) next.add(id);
      else next.delete(id);
      return next;
    });

  const applyPatch = useCallback(async (id: string, patch: JobPatch) => {
    setError(null);
    setBusy(id, true);
    try {
      const updated = await patchJob(id, patch);
      setJobs((current) => current.map((job) => (job.id === id ? updated : job)));
    } catch (caught) {
      setError(`Could not update job ${id}: ${(caught as Error).message}`);
      throw caught;
    } finally {
      setBusy(id, false);
    }
  }, []);

  const changeStatus = useCallback(
    (id: string, status: JobStatus) => {
      applyPatch(id, { status }).catch(() => {
        /* surfaced via `error` */
      });
    },
    [applyPatch],
  );

  const saveNotes = (id: string, notes: string) => applyPatch(id, { notes });

  const changeArrangement = (id: string, workArrangement: WorkArrangement | null) => {
    applyPatch(id, { work_arrangement: workArrangement }).catch(() => {
      /* surfaced via `error` */
    });
  };

  /**
   * Reload the jobs. From the Refresh button, first re-score every saved job
   * against your skills (through the search API); if that can't happen, the
   * jobs are still reloaded and the notice says why.
   */
  const refresh = async ({ reassess = false }: { reassess?: boolean } = {}) => {
    setRefreshing(true);
    setError(null);
    if (reassess) {
      setReassessing(true);
      setNotice(null);
      try {
        setNotice(describeReassess(await reassessJobs()));
      } catch (caught) {
        setNotice(reassessProblem(caught));
      } finally {
        setReassessing(false);
      }
    }
    try {
      const result = await fetchJobs();
      setJobs(result.jobs);
      setStore(result.store);
    } catch (caught) {
      setError(`Could not refresh: ${(caught as Error).message}`);
    } finally {
      setRefreshing(false);
    }
  };

  return (
    <div className="space-y-4">
      <StoreBanner store={store} />

      {/* A finished search reloads the table, so its new matches show up right away
          (the search has already reassessed the saved jobs). */}
      <RunSearchPanel onFinished={() => void refresh()} />

      <div className="flex flex-wrap items-center gap-3">
        <ToggleGroup
          type="single"
          aria-label="Filter by status"
          value={filters.status === "all" ? "" : filters.status}
          onValueChange={(value) =>
            updateFilters((current) => ({ ...current, status: (value || "all") as JobStatus | "all" }))
          }
          className="flex-wrap gap-1.5"
        >
          {JOB_STATUSES.filter((status) => counts[status]).map((status) => (
            <ToggleGroupItem
              key={status}
              value={status}
              size="sm"
              className={cn(
                "h-7 flex-none rounded-full border px-3 text-xs first:rounded-full last:rounded-full data-[state=on]:ring-2 data-[state=on]:ring-ring",
                statusClasses(status),
                "data-[state=on]:bg-[inherit] hover:opacity-80",
              )}
            >
              {statusLabel(status)} <span className="font-bold">{counts[status]}</span>
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
        <span className="text-muted-foreground text-xs">
          {jobs.length} tracked · {visible.length} match
        </span>
      </div>

      <FilterBar
        filters={filters}
        sort={sort}
        companies={companies}
        remoteStatuses={remoteStatuses}
        tracks={tracks}
        skills={skillOptions}
        refreshing={refreshing}
        reassessing={reassessing}
        onFiltersChange={updateFilters}
        onSortChange={updateSort}
        onRefresh={() => void refresh({ reassess: true })}
      />

      {reassessing && (
        <p className="text-muted-foreground text-sm" aria-live="polite">
          Re-scoring your saved jobs against your skills… The first time, each job&apos;s description is loaded from
          its site, which can take a minute.
        </p>
      )}

      {notice && <ReassessNoticeAlert notice={notice} onDismiss={() => setNotice(null)} />}

      {error && (
        <Alert variant="destructive">
          <AlertCircleIcon />
          <AlertTitle>Something went wrong</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      <div ref={tableRef} className="scroll-mt-4 rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow>
              {HEADERS.map((header, index) => (
                <TableHead key={index} className="text-muted-foreground text-xs tracking-wide uppercase">
                  {header}
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {visible.length === 0 ? (
              <TableRow>
                <TableCell colSpan={HEADERS.length} className="text-muted-foreground h-24 text-center">
                  {jobs.length === 0
                    ? "No jobs tracked yet. Click Run search above (or run the search script in backend/) to populate the database."
                    : "No jobs match the current filters."}
                </TableCell>
              </TableRow>
            ) : (
              current.items.map((job) => (
                <JobRow
                  key={job.id}
                  job={job}
                  selected={selectedId === job.id}
                  busy={busyIds.has(job.id)}
                  onSelect={setSelectedId}
                  onStatusChange={changeStatus}
                />
              ))
            )}
          </TableBody>
        </Table>
      </div>

      {visible.length > 0 && (
        <Pagination page={current} pageSize={pageSize} onPageChange={goToPage} onPageSizeChange={updatePageSize} />
      )}

      <Sheet open={selected !== null} onOpenChange={(open) => !open && setSelectedId(null)}>
        {selected && (
          <JobDetails
            key={`${selected.id}:${selected.notes ?? ""}`}
            job={selected}
            busy={busyIds.has(selected.id)}
            onStatusChange={(status) => changeStatus(selected.id, status)}
            onNotesSave={(notes) => saveNotes(selected.id, notes)}
            onArrangementChange={(value) => changeArrangement(selected.id, value)}
          />
        )}
      </Sheet>
    </div>
  );
}
