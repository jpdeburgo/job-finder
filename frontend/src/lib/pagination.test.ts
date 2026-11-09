import { describe, expect, it } from "vitest";
import { DEFAULT_PAGE_SIZE, pageNumbers, paginate, paginationFromSearchParams } from "./pagination";

const items = Array.from({ length: 60 }, (_, index) => index + 1);

describe("paginate", () => {
  it("slices a page and says which items it holds", () => {
    expect(paginate(items, 2, 25)).toEqual({
      items: items.slice(25, 50),
      page: 2,
      pageCount: 3,
      start: 26,
      end: 50,
      total: 60,
    });
    expect(paginate(items, 3, 25)).toMatchObject({ items: items.slice(50), start: 51, end: 60 });
  });

  it("clamps pages that don't exist", () => {
    expect(paginate(items, 9, 25).page).toBe(3);
    expect(paginate(items, 0, 25).page).toBe(1);
    expect(paginate(items, Number.NaN, 25).page).toBe(1);
  });

  it("is page 1 of 1 when there's nothing", () => {
    expect(paginate([], 4, 25)).toEqual({ items: [], page: 1, pageCount: 1, start: 0, end: 0, total: 0 });
  });
});

describe("pageNumbers", () => {
  it.each([
    [1, 1, [1]],
    [1, 5, [1, 2, 3, 4, 5]],
    [3, 7, [1, 2, 3, 4, 5, 6, 7]], // a few pages: all of them
    [10, 20, [1, "gap", 9, 10, 11, "gap", 20]],
    [3, 20, [1, 2, 3, 4, "gap", 20]], // a gap of one page is shown, not hidden
    [1, 20, [1, 2, "gap", 20]],
    [20, 20, [1, "gap", 19, 20]],
  ])("page %i of %i", (page, count, expected) => {
    expect(pageNumbers(page, count)).toEqual(expected);
  });
});

describe("paginationFromSearchParams", () => {
  it("reads ?page= and ?per_page=", () => {
    expect(paginationFromSearchParams({ page: "3", per_page: "50" })).toEqual({ page: 3, pageSize: 50 });
    expect(paginationFromSearchParams({ page: ["2", "9"] })).toEqual({ page: 2, pageSize: DEFAULT_PAGE_SIZE });
  });

  it("falls back to page 1 and the default size for anything odd", () => {
    expect(paginationFromSearchParams({})).toEqual({ page: 1, pageSize: DEFAULT_PAGE_SIZE });
    expect(paginationFromSearchParams({ page: "-2", per_page: "33" })).toEqual({ page: 1, pageSize: DEFAULT_PAGE_SIZE });
    expect(paginationFromSearchParams({ page: "abc", per_page: "" })).toEqual({ page: 1, pageSize: DEFAULT_PAGE_SIZE });
  });
});
