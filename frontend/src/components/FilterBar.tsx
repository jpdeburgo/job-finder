"use client";

import { RefreshCwIcon, SearchIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { SORT_OPTIONS, type JobFilters, type SortKey } from "@/lib/jobs";
import { JOB_STATUSES, STATUS_INFO, type JobStatus } from "@/lib/types";

interface Props {
  filters: JobFilters;
  sort: SortKey;
  tracks: string[];
  legacyCount: number;
  refreshing: boolean;
  onFiltersChange: (filters: JobFilters) => void;
  onSortChange: (sort: SortKey) => void;
  onRefresh: () => void;
}

export function FilterBar({
  filters,
  sort,
  tracks,
  legacyCount,
  refreshing,
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
            placeholder="Title, skill, city, note, job ID…"
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

      <div className="flex h-9 items-center gap-2">
        <Checkbox
          id="hide-legacy"
          checked={filters.hideLegacy}
          onCheckedChange={(checked) => update({ hideLegacy: checked === true })}
        />
        <Label htmlFor="hide-legacy" className="font-normal">
          Hide imported IDs without details
          {legacyCount > 0 && <span className="text-muted-foreground text-xs">({legacyCount})</span>}
        </Label>
      </div>

      <Button variant="outline" onClick={onRefresh} disabled={refreshing} className="ml-auto">
        <RefreshCwIcon className={refreshing ? "animate-spin" : undefined} />
        {refreshing ? "Refreshing…" : "Refresh"}
      </Button>
    </div>
  );
}
