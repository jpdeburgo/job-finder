"use client";

import { ChevronDownIcon } from "lucide-react";
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
  className?: string;
}

const same = (a: string, b: string) => a.toLowerCase() === b.toLowerCase();

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
  className,
}: Props) {
  const missing = selected.filter((value) => !options.some((option) => same(option.value, value)));
  const listed = [...options, ...missing.map((value) => ({ value, count: 0 }))];
  const isSelected = (value: string) => selected.some((chosen) => same(chosen, value));
  const toggle = (value: string, checked: boolean) =>
    onChange(checked ? [...selected, value] : selected.filter((chosen) => !same(chosen, value)));
  // Keep the menu open, so several can be picked in a row.
  const stayOpen = (event: Event) => event.preventDefault();
  const label = multiSelectLabel(selected, noneLabel, match?.value);

  return (
    <DropdownMenu>
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
        align="start"
        className="max-h-[min(28rem,var(--radix-dropdown-menu-content-available-height))] w-64 overflow-y-auto"
      >
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
        ) : (
          listed.map(({ value, count }) => (
            <DropdownMenuCheckboxItem
              key={value}
              checked={isSelected(value)}
              aria-label={`${value}, ${count} job${count === 1 ? "" : "s"}`}
              onCheckedChange={(checked) => toggle(value, checked === true)}
              onSelect={stayOpen}
            >
              <span className="flex-1 truncate">{value}</span>
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
