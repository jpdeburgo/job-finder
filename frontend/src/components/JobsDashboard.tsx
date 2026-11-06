"use client";

import { AlertCircleIcon } from "lucide-react";
import { useCallback, useMemo, useState } from "react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Sheet } from "@/components/ui/sheet";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { fetchJobs, patchJob } from "@/lib/client";
import {
  DEFAULT_FILTERS,
  countByStatus,
  distinctCompanies,
  distinctRemoteStatuses,
  distinctTracks,
  filterJobs,
  sortJobs,
  type JobFilters,
  type SortKey,
} from "@/lib/jobs";
import { JOB_STATUSES, type Job, type JobPatch, type JobStatus, type StoreInfo } from "@/lib/types";
import { cn } from "@/lib/utils";
import { FilterBar } from "./FilterBar";
import { JobDetails } from "./JobDetails";
import { JobRow } from "./JobRow";
import { statusClasses, statusLabel } from "./StatusBadge";
import { StoreBanner } from "./StoreBanner";

interface Props {
  initialJobs: Job[];
  initialStore: StoreInfo;
}

const HEADERS = ["", "Job", "Track", "Skills", "Salary", "Posted", "Last seen", "Status", "Applied"];

/** The whole interactive dashboard: banner, summary, filters, table, and details drawer. */
export function JobsDashboard({ initialJobs, initialStore }: Props) {
  const [jobs, setJobs] = useState<Job[]>(initialJobs);
  const [store, setStore] = useState<StoreInfo>(initialStore);
  const [filters, setFilters] = useState<JobFilters>(DEFAULT_FILTERS);
  const [sort, setSort] = useState<SortKey>("last_seen");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [busyIds, setBusyIds] = useState<Set<string>>(new Set());
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const counts = useMemo(() => countByStatus(jobs), [jobs]);
  const companies = useMemo(() => distinctCompanies(jobs), [jobs]);
  const remoteStatuses = useMemo(() => distinctRemoteStatuses(jobs), [jobs]);
  const tracks = useMemo(() => distinctTracks(jobs), [jobs]);
  const visible = useMemo(() => sortJobs(filterJobs(jobs, filters), sort), [jobs, filters, sort]);
  const selected = useMemo(() => jobs.find((job) => job.id === selectedId) ?? null, [jobs, selectedId]);

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

  const changeStatus = (id: string, status: JobStatus) => {
    applyPatch(id, { status }).catch(() => {
      /* surfaced via `error` */
    });
  };

  const saveNotes = (id: string, notes: string) => applyPatch(id, { notes });

  const refresh = async () => {
    setRefreshing(true);
    setError(null);
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

      <div className="flex flex-wrap items-center gap-3">
        <ToggleGroup
          type="single"
          aria-label="Filter by status"
          value={filters.status === "all" ? "" : filters.status}
          onValueChange={(value) => setFilters((current) => ({ ...current, status: (value || "all") as JobStatus | "all" }))}
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
          {jobs.length} tracked · {visible.length} shown
        </span>
      </div>

      <FilterBar
        filters={filters}
        sort={sort}
        companies={companies}
        remoteStatuses={remoteStatuses}
        tracks={tracks}
        refreshing={refreshing}
        onFiltersChange={setFilters}
        onSortChange={setSort}
        onRefresh={refresh}
      />

      {error && (
        <Alert variant="destructive">
          <AlertCircleIcon />
          <AlertTitle>Something went wrong</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      <div className="rounded-lg border">
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
                    ? "No jobs tracked yet. Run the search script in backend/ to populate the database."
                    : "No jobs match the current filters."}
                </TableCell>
              </TableRow>
            ) : (
              visible.map((job) => (
                <JobRow
                  key={job.id}
                  job={job}
                  selected={selectedId === job.id}
                  busy={busyIds.has(job.id)}
                  onSelect={() => setSelectedId(job.id)}
                  onStatusChange={(status) => changeStatus(job.id, status)}
                />
              ))
            )}
          </TableBody>
        </Table>
      </div>

      <Sheet open={selected !== null} onOpenChange={(open) => !open && setSelectedId(null)}>
        {selected && (
          <JobDetails
            key={`${selected.id}:${selected.notes ?? ""}`}
            job={selected}
            busy={busyIds.has(selected.id)}
            onStatusChange={(status) => changeStatus(selected.id, status)}
            onNotesSave={(notes) => saveNotes(selected.id, notes)}
          />
        )}
      </Sheet>
    </div>
  );
}
