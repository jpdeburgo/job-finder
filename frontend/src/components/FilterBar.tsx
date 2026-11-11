"use client";

import { RefreshCwIcon, SearchIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  REMOTE_STATUS_INFO,
  SORT_OPTIONS,
  type JobFilters,
  type FilterOption,
  type RemoteStatus,
  type SortKey,
} from "@/lib/jobs";
import { JOB_STATUSES, STATUS_INFO, type JobStatus } from "@/lib/types";
import { MultiSelectFilter } from "./MultiSelectFilter";

interface Props {
  filters: JobFilters;
  sort: SortKey;
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
  onSortChange: (sort: SortKey) => void;
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
        />
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="sort-by">Sort</Label>
        <Select value={sort} onValueChange={(value) => onSortChange(value as SortKey)}>
          <SelectTrigger id="sort-by" className="w-[200px]">
            <SelectValue>{SORT_OPTIONS.find((option) => option.value === sort)?.label}</SelectValue>
          </SelectTrigger>
          <SelectContent>
            {SORT_OPTIONS.map((option) => (
              <SelectItem key={option.value} value={option.value}>
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
