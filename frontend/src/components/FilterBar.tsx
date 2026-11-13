"use client";

import { RefreshCwIcon, SearchIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  REMOTE_STATUS_INFO,
  SALARY_FILTER_LABELS,
  SORT_OPTIONS,
  thenByOptions,
  type JobFilters,
  type FilterOption,
  type RemoteStatus,
  type SalaryFilter,
  type SortKey,
} from "@/lib/jobs";
import { JOB_STATUSES, STATUS_INFO, type JobStatus } from "@/lib/types";
import { MultiSelectFilter } from "./MultiSelectFilter";

interface Props {
  filters: JobFilters;
  /** The sort, then (optionally) what orders its ties. */
  sort: SortKey[];
  /** Companies the jobs are from, with counts (see `distinctCompanies`). */
  companies: FilterOption[];
  /** Remote statuses present in the data (see `distinctRemoteStatuses`). */
  remoteStatuses: RemoteStatus[];
  tracks: string[];
  /** Skills the jobs matched, with counts (see `distinctSkills`). */
  skills?: FilterOption[];
  refreshing: boolean;
  /** Refresh is re-scoring the saved jobs against your skills (before reloading them). */
  reassessing?: boolean;
  onFiltersChange: (filters: JobFilters) => void;
  onSortChange: (sort: SortKey[]) => void;
  onRefresh: () => void;
}

export function FilterBar({
  filters,
  sort,
  companies,
  remoteStatuses,
  tracks,
  skills = [],
  refreshing,
  reassessing = false,
  onFiltersChange,
  onSortChange,
  onRefresh,
}: Props) {
  const update = (patch: Partial<JobFilters>) => onFiltersChange({ ...filters, ...patch });
  const [primary = "last_seen", thenBy] = sort;
  const tieOptions = thenByOptions(primary);
  const label = (key: SortKey) => SORT_OPTIONS.find((option) => option.value === key)?.label;
  const changePrimary = (next: SortKey) =>
    // Keep "Then by" unless it's the new sort itself (or its other direction).
    onSortChange(thenBy && thenByOptions(next).some((option) => option.value === thenBy) ? [next, thenBy] : [next]);
  const changeThenBy = (next: string) => onSortChange(next === "none" ? [primary] : [primary, next as SortKey]);

  return (
    <div className="flex flex-wrap items-end gap-3">
      <div className="flex min-w-[220px] flex-1 flex-col gap-1.5">
        <Label htmlFor="job-search">Search</Label>
        <div className="relative">
          <SearchIcon className="text-muted-foreground pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2" />
          <Input
            id="job-search"
            type="search"
            placeholder="Title, company, skill, city, note, job ID…"
            value={filters.query}
            onChange={(event) => update({ query: event.target.value })}
            className="pl-8"
          />
        </div>
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="filter-status">Status</Label>
        <Select value={filters.status} onValueChange={(value) => update({ status: value as JobStatus | "all" })}>
          <SelectTrigger id="filter-status" className="w-[150px]">
            <SelectValue>{filters.status === "all" ? "All statuses" : STATUS_INFO[filters.status].label}</SelectValue>
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All statuses</SelectItem>
            {JOB_STATUSES.map((status) => (
              <SelectItem key={status} value={status}>
                {STATUS_INFO[status].label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="filter-company">Company</Label>
        <MultiSelectFilter
          id="filter-company"
          className="w-[200px]"
          options={companies}
          selected={filters.companies}
          onChange={(selected) => update({ companies: selected })}
          noneLabel="All companies"
          emptyLabel="No companies yet."
          clearLabel="Clear companies"
          searchLabel="Search companies"
        />
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="filter-remote">Remote</Label>
        <Select value={filters.remote} onValueChange={(value) => update({ remote: value as RemoteStatus | "all" })}>
          <SelectTrigger id="filter-remote" className="w-[170px]">
            <SelectValue>{filters.remote === "all" ? "Any" : REMOTE_STATUS_INFO[filters.remote].label}</SelectValue>
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Any</SelectItem>
            {(Object.keys(REMOTE_STATUS_INFO) as RemoteStatus[])
              // Keep the selected status listed even if a refresh removed its last job.
              .filter((status) => remoteStatuses.includes(status) || status === filters.remote)
              .map((status) => (
                <SelectItem key={status} value={status} title={REMOTE_STATUS_INFO[status].hint}>
                  {REMOTE_STATUS_INFO[status].label}
                </SelectItem>
              ))}
          </SelectContent>
        </Select>
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="filter-track">Track</Label>
        <Select value={filters.track} onValueChange={(value) => update({ track: value })}>
          <SelectTrigger id="filter-track" className="w-[220px]">
            <SelectValue>{filters.track === "all" ? "All tracks" : filters.track}</SelectValue>
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All tracks</SelectItem>
            {tracks.map((track) => (
              <SelectItem key={track} value={track}>
                {track}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="filter-skills">Skills</Label>
        <MultiSelectFilter
          id="filter-skills"
          className="w-[200px]"
          options={skills}
          selected={filters.skills}
          onChange={(selected) => update({ skills: selected })}
          match={{ value: filters.skillMatch, onChange: (skillMatch) => update({ skillMatch }), plural: "skills" }}
          noneLabel="Any skill"
          emptyLabel="No skills matched yet."
          clearLabel="Clear skills"
          searchLabel="Search skills"
        />
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="filter-salary">Salary</Label>
        <Select value={filters.salary} onValueChange={(value) => update({ salary: value as SalaryFilter })}>
          <SelectTrigger id="filter-salary" className="w-[130px]">
            <SelectValue>{SALARY_FILTER_LABELS[filters.salary]}</SelectValue>
          </SelectTrigger>
          <SelectContent>
            {(Object.keys(SALARY_FILTER_LABELS) as SalaryFilter[]).map((option) => (
              <SelectItem key={option} value={option}>
                {SALARY_FILTER_LABELS[option]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="sort-by">Sort</Label>
        <Select value={primary} onValueChange={(value) => changePrimary(value as SortKey)}>
          <SelectTrigger id="sort-by" className="w-[200px]">
            <SelectValue>{label(primary)}</SelectValue>
          </SelectTrigger>
          <SelectContent>
            {SORT_OPTIONS.map((option) => (
              <SelectItem key={option.value} value={option.value} title={option.hint}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="sort-then-by">Then by</Label>
        <Select value={thenBy ?? "none"} onValueChange={changeThenBy}>
          <SelectTrigger
            id="sort-then-by"
            className={thenBy ? "w-[200px]" : "text-muted-foreground w-[200px]"}
            title="Orders the jobs that tie on the first sort. Jobs that still tie stay newest first."
          >
            <SelectValue>{thenBy ? label(thenBy) : "Nothing else"}</SelectValue>
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="none">Nothing else</SelectItem>
            {tieOptions.map((option) => (
              <SelectItem key={option.value} value={option.value} title={option.hint}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <Button
        variant="outline"
        onClick={onRefresh}
        disabled={refreshing}
        className="ml-auto"
        title="Re-score every saved job against your skills, then reload the list"
      >
        <RefreshCwIcon className={refreshing ? "animate-spin" : undefined} />
        {reassessing ? "Reassessing…" : refreshing ? "Refreshing…" : "Refresh"}
      </Button>
    </div>
  );
}
