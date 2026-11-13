"use client";

import { ChevronDownIcon, SearchIcon } from "lucide-react";
import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import type { FilterOption, SkillMatch } from "@/lib/jobs";
import { cn } from "@/lib/utils";

/** Offered when a job can have several of the choices (skills): any of them, or all. */
interface MatchMode {
  value: SkillMatch;
  onChange: (match: SkillMatch) => void;
  /** What's being picked, in the plural: "skills". */
  plural: string;
}

interface Props {
  id?: string;
  /** The choices, with how many jobs have each, in the order to show them. */
  options: FilterOption[];
  selected: string[];
  onChange: (selected: string[]) => void;
  /** What the closed menu says with nothing picked: "All companies", "Any skill". */
  noneLabel: string;
  /** Shown when there's nothing to pick: "No skills matched yet." */
  emptyLabel: string;
  /** "Clear skills" */
  clearLabel: string;
  /** Any or all of the picked ones; leave out when a job has just one (its company). */
  match?: MatchMode;
  /** The search box's label: "Search companies". */
  searchLabel?: string;
  className?: string;
}

const same = (a: string, b: string) => a.toLowerCase() === b.toLowerCase();

/** Letters and digits only, lowercased: "Insight Global" and "insightglobal" are the same. */
const compact = (text: string) => text.toLowerCase().replace(/[^a-z0-9]/g, "");

/** A choice that matches the search, and where (to highlight it). */
export interface OptionMatch extends FilterOption {
  /** `[start, end]` of the search text in `value`; null when it only matches ignoring spaces and punctuation. */
  match: [number, number] | null;
}

/**
 * The choices that match `query`, best first: names that start with it
 * ("a" → Accenture, Adobe), then names with a word that starts with it
 * ("global" → Insight Global), then any other match. Case, spaces, and
 * punctuation don't matter ("doordash" finds Doordashusa, "insightglobal"
 * finds Insight Global). Ties keep the given order. An empty query returns
 * every choice.
 */
export function searchOptions(options: FilterOption[], query: string): OptionMatch[] {
  const wanted = query.trim().toLowerCase();
  if (!wanted) return options.map((option) => ({ ...option, match: null }));
  const wantedCompact = compact(wanted);
  const found: (OptionMatch & { rank: number; index: number })[] = [];
  options.forEach((option, index) => {
    const lower = option.value.toLowerCase();
    const at = lower.indexOf(wanted);
    let rank: number;
    if (at === 0) rank = 0;
    else if (at > 0 && /[^a-z0-9]/.test(lower[at - 1])) rank = 1;
    else if (at > 0 || (wantedCompact && compact(option.value).includes(wantedCompact))) rank = 2;
    else return;
    found.push({ ...option, match: at >= 0 ? [at, at + wanted.length] : null, rank, index });
  });
  return found
    .sort((a, b) => a.rank - b.rank || a.index - b.index)
    .map(({ value, count, match }) => ({ value, count, match }));
}

/** `value` with the part that matched the search in bold. */
function Highlighted({ value, match }: { value: string; match: [number, number] | null }) {
  if (!match) return <>{value}</>;
  const [start, end] = match;
  return (
    <>
      {value.slice(0, start)}
      <span className="text-foreground font-semibold">{value.slice(start, end)}</span>
      {value.slice(end)}
    </>
  );
}

/**
 * What the closed menu says: the none label, "Python", "Python or React",
 * "Python and React" (all), "Python or 2 more", "Python + 2 more" (all).
 */
export function multiSelectLabel(selected: string[], noneLabel: string, match: SkillMatch = "any"): string {
  if (selected.length === 0) return noneLabel;
  if (selected.length === 1) return selected[0];
  if (selected.length === 2) return selected.join(match === "all" ? " and " : " or ");
  return `${selected[0]} ${match === "all" ? "+" : "or"} ${selected.length - 1} more`;
}

/**
 * A filter that takes any number of choices (the tracker's Company and Skills
 * filters). Nothing picked means no filter. The menu stays open while you
 * pick, and a choice you picked stays listed even if a refresh removed its
 * last job. Choices are compared in any case.
 *
 * A search box at the top narrows the list as you type (`searchOptions`); it
 * has the focus when the menu opens. Enter picks the best match and clears
 * the search for the next one, ↓ moves into the list, and Escape clears the
 * search (a second Escape closes the menu). Typing while a choice has the
 * focus goes to the search box too.
 */
export function MultiSelectFilter({
  id,
  options,
  selected,
  onChange,
  noneLabel,
  emptyLabel,
  clearLabel,
  match,
  searchLabel = "Search",
  className,
}: Props) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const searchRef = useRef<HTMLInputElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);

  // Start in the search box, so you can type right away. The menu focuses
  // itself (or its first choice) as it opens, so this waits for that.
  useEffect(() => {
    if (!open) return;
    const timer = setTimeout(() => searchRef.current?.focus());
    return () => clearTimeout(timer);
  }, [open]);
  const missing = selected.filter((value) => !options.some((option) => same(option.value, value)));
  const listed = [...options, ...missing.map((value) => ({ value, count: 0 }))];
  const isSelected = (value: string) => selected.some((chosen) => same(chosen, value));
  const toggle = (value: string, checked: boolean) =>
    onChange(checked ? [...selected, value] : selected.filter((chosen) => !same(chosen, value)));
  // Keep the menu open, so several can be picked in a row.
  const stayOpen = (event: Event) => event.preventDefault();
  const label = multiSelectLabel(selected, noneLabel, match?.value);
  const shown = searchOptions(listed, query);
  const searching = query.trim() !== "";

  const pickBestMatch = () => {
    const best = shown[0];
    if (!searching || !best) return;
    if (!isSelected(best.value)) onChange([...selected, best.value]);
    setQuery("");
  };

  const onSearchKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      contentRef.current?.querySelector<HTMLElement>('[role="menuitemcheckbox"]')?.focus();
    } else if (event.key === "Enter") {
      event.preventDefault();
      pickBestMatch();
    }
    // The rest is typing: keep it from the menu, which would jump to a
    // choice by its first letter. (Escape is handled by onEscapeKeyDown.)
    event.stopPropagation();
  };

  const onMenuKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.target === searchRef.current || !searchRef.current) return;
    const { key } = event;
    const typing = key.length === 1 && key !== " " && !event.ctrlKey && !event.metaKey && !event.altKey;
    if (typing || key === "Backspace") {
      // Typing on a choice goes to the search box (and not to the menu's jump-to-letter).
      event.preventDefault();
      setQuery((current) => (key === "Backspace" ? current.slice(0, -1) : current + key));
      searchRef.current.focus();
    } else if (key === "ArrowUp" && event.target === contentRef.current?.querySelector('[role^="menuitem"]')) {
      // Up from the first choice goes back to the search box.
      event.preventDefault();
      searchRef.current.focus();
    }
  };

  return (
    <DropdownMenu
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) setQuery("");
      }}
    >
      <DropdownMenuTrigger asChild>
        <Button
          id={id}
          variant="outline"
          // The whole list on hover, when the button cuts it short.
          title={selected.length > 1 ? selected.join(match?.value === "all" ? " and " : ", ") : undefined}
          className={cn("justify-between font-normal", selected.length === 0 && "text-muted-foreground", className)}
        >
          <span className="truncate">{label}</span>
          <ChevronDownIcon className="text-muted-foreground size-4 opacity-50" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent
        ref={contentRef}
        align="start"
        className="max-h-[min(28rem,var(--radix-dropdown-menu-content-available-height))] w-64 overflow-y-auto"
        onEscapeKeyDown={(event) => {
          // The first Escape clears the search; the next one closes the menu.
          if (!query) return;
          event.preventDefault();
          setQuery("");
          searchRef.current?.focus();
        }}
        onKeyDown={onMenuKeyDown}
      >
        {listed.length > 0 && (
          <div className="bg-popover sticky -top-1 z-10 -mx-1 -mt-1 mb-1 border-b p-1.5">
            <div className="relative">
              <SearchIcon className="text-muted-foreground pointer-events-none absolute top-1/2 left-2 size-3.5 -translate-y-1/2" />
              <Input
                ref={searchRef}
                type="search"
                aria-label={searchLabel}
                placeholder={`${searchLabel}…`}
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                onKeyDown={onSearchKeyDown}
                autoComplete="off"
                className="h-8 pl-7 text-sm"
              />
            </div>
          </div>
        )}
        {match && (
          <>
            <DropdownMenuLabel className="text-muted-foreground text-xs font-normal">Jobs with</DropdownMenuLabel>
            <DropdownMenuRadioGroup value={match.value} onValueChange={(value) => match.onChange(value as SkillMatch)}>
              <DropdownMenuRadioItem value="any" onSelect={stayOpen}>
                Any of the selected {match.plural}
              </DropdownMenuRadioItem>
              <DropdownMenuRadioItem value="all" onSelect={stayOpen}>
                All of the selected {match.plural}
              </DropdownMenuRadioItem>
            </DropdownMenuRadioGroup>
            <DropdownMenuSeparator />
          </>
        )}
        {listed.length === 0 ? (
          <DropdownMenuLabel className="text-muted-foreground font-normal">{emptyLabel}</DropdownMenuLabel>
        ) : shown.length === 0 ? (
          <DropdownMenuLabel className="text-muted-foreground font-normal" role="status">
            No matches for “{query.trim()}”.
          </DropdownMenuLabel>
        ) : (
          shown.map(({ value, count, match: found }) => (
            <DropdownMenuCheckboxItem
              key={value}
              checked={isSelected(value)}
              aria-label={`${value}, ${count} job${count === 1 ? "" : "s"}`}
              onCheckedChange={(checked) => toggle(value, checked === true)}
              onSelect={stayOpen}
            >
              <span className="flex-1 truncate">
                <Highlighted value={value} match={found} />
              </span>
              <span className="text-muted-foreground text-xs tabular-nums" aria-hidden>
                {count}
              </span>
            </DropdownMenuCheckboxItem>
          ))
        )}
        {selected.length > 0 && (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuItem onSelect={() => onChange([])}>{clearLabel}</DropdownMenuItem>
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
