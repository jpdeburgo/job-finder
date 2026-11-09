/**
 * Paging through the tracker's results: pure helpers, no React, so the
 * dashboard, the URL, and the tests all agree on what page N shows.
 */

/** Choices for "Rows per page". */
export const PAGE_SIZES = [25, 50, 100] as const;
export type PageSize = (typeof PAGE_SIZES)[number];
export const DEFAULT_PAGE_SIZE: PageSize = 25;

export function isPageSize(value: unknown): value is PageSize {
  return typeof value === "number" && (PAGE_SIZES as readonly number[]).includes(value);
}

export interface Page<T> {
  /** The items on this page. */
  items: T[];
  /** 1-based, clamped into range: asking for page 9 of 3 gives page 3. */
  page: number;
  /** At least 1, so an empty result is "page 1 of 1". */
  pageCount: number;
  /** 1-based positions of the first and last item shown (0 and 0 when empty). */
  start: number;
  end: number;
  total: number;
}

/** Slice one page out of `items`. */
export function paginate<T>(items: T[], page: number, pageSize: number): Page<T> {
  const total = items.length;
  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  const current = Math.min(Math.max(1, Math.floor(page) || 1), pageCount);
  const offset = (current - 1) * pageSize;
  const shown = items.slice(offset, offset + pageSize);
  return {
    items: shown,
    page: current,
    pageCount,
    start: shown.length ? offset + 1 : 0,
    end: offset + shown.length,
    total,
  };
}

/** Up to this many pages, every page number is shown. */
const SHOW_ALL_PAGES_UP_TO = 7;

/**
 * The page buttons to show. A few pages are all shown; beyond that, the first
 * and last pages, the current page and its neighbours, and "gap" where pages
 * are skipped (never hiding a single page behind a gap).
 *
 *   pageNumbers(1, 5)   -> [1, 2, 3, 4, 5]
 *   pageNumbers(10, 20) -> [1, "gap", 9, 10, 11, "gap", 20]
 */
export function pageNumbers(page: number, pageCount: number, neighbours = 1): (number | "gap")[] {
  if (pageCount <= SHOW_ALL_PAGES_UP_TO) {
    return Array.from({ length: pageCount }, (_, index) => index + 1);
  }
  const wanted = new Set<number>([1, pageCount]);
  for (let n = page - neighbours; n <= page + neighbours; n += 1) {
    if (n >= 1 && n <= pageCount) wanted.add(n);
  }
  const sorted = [...wanted].sort((a, b) => a - b);
  const result: (number | "gap")[] = [];
  sorted.forEach((n, index) => {
    const previous = sorted[index - 1];
    if (previous !== undefined && n - previous === 2) result.push(previous + 1); // a gap of one page: show it
    else if (previous !== undefined && n - previous > 2) result.push("gap");
    result.push(n);
  });
  return result;
}

function firstParam(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

/** `?page=3&per_page=50` -> `{ page: 3, pageSize: 50 }`; anything odd falls back to the defaults. */
export function paginationFromSearchParams(params: Record<string, string | string[] | undefined>): {
  page: number;
  pageSize: PageSize;
} {
  const page = Number.parseInt(firstParam(params.page) ?? "", 10);
  const pageSize = Number.parseInt(firstParam(params.per_page) ?? "", 10);
  return {
    page: Number.isFinite(page) && page >= 1 ? page : 1,
    pageSize: isPageSize(pageSize) ? pageSize : DEFAULT_PAGE_SIZE,
  };
}
