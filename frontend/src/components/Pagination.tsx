"use client";

import { ChevronLeftIcon, ChevronRightIcon, ChevronsLeftIcon, ChevronsRightIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { PAGE_SIZES, pageNumbers, type Page, type PageSize } from "@/lib/pagination";

interface Props {
  page: Page<unknown>;
  pageSize: PageSize;
  /** What's being counted, for "Showing 1–25 of 312 jobs". */
  noun?: string;
  onPageChange: (page: number) => void;
  onPageSizeChange: (pageSize: PageSize) => void;
}

/** "Showing 26–50 of 312 jobs", rows per page, and first/previous/numbered/next/last buttons. */
export function Pagination({ page, pageSize, noun = "jobs", onPageChange, onPageSizeChange }: Props) {
  const { page: current, pageCount, start, end, total } = page;
  const atStart = current <= 1;
  const atEnd = current >= pageCount;

  return (
    <div className="flex flex-wrap items-center justify-between gap-3 text-sm">
      <p className="text-muted-foreground" aria-live="polite">
        {total === 0 ? `No ${noun}` : `Showing ${start}–${end} of ${total} ${noun}`}
      </p>

      <div className="flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-2">
          <span className="text-muted-foreground text-xs" id="rows-per-page">
            Rows per page
          </span>
          <Select value={String(pageSize)} onValueChange={(value) => onPageSizeChange(Number(value) as PageSize)}>
            <SelectTrigger size="sm" aria-labelledby="rows-per-page" className="w-[76px]">
              <SelectValue>{pageSize}</SelectValue>
            </SelectTrigger>
            <SelectContent>
              {PAGE_SIZES.map((size) => (
                <SelectItem key={size} value={String(size)}>
                  {size}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {pageCount > 1 && (
          <nav aria-label="Pagination" className="flex items-center gap-1">
            <Button variant="outline" size="icon-sm" disabled={atStart} onClick={() => onPageChange(1)} aria-label="First page">
              <ChevronsLeftIcon />
            </Button>
            <Button
              variant="outline"
              size="icon-sm"
              disabled={atStart}
              onClick={() => onPageChange(current - 1)}
              aria-label="Previous page"
            >
              <ChevronLeftIcon />
            </Button>
            {pageNumbers(current, pageCount).map((n, index) =>
              n === "gap" ? (
                <span key={`gap-${index}`} className="text-muted-foreground px-1" aria-hidden>
                  …
                </span>
              ) : (
                <Button
                  key={n}
                  variant={n === current ? "default" : "ghost"}
                  size="sm"
                  className="min-w-8 px-2 tabular-nums"
                  aria-label={`Page ${n}`}
                  aria-current={n === current ? "page" : undefined}
                  onClick={() => n !== current && onPageChange(n)}
                >
                  {n}
                </Button>
              ),
            )}
            <Button
              variant="outline"
              size="icon-sm"
              disabled={atEnd}
              onClick={() => onPageChange(current + 1)}
              aria-label="Next page"
            >
              <ChevronRightIcon />
            </Button>
            <Button
              variant="outline"
              size="icon-sm"
              disabled={atEnd}
              onClick={() => onPageChange(pageCount)}
              aria-label="Last page"
            >
              <ChevronsRightIcon />
            </Button>
          </nav>
        )}
      </div>
    </div>
  );
}
