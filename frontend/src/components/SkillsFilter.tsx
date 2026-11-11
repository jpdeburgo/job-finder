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
import type { SkillCount, SkillMatch } from "@/lib/jobs";
import { cn } from "@/lib/utils";

interface Props {
  id?: string;
  /** Every skill the jobs matched, with counts (see `distinctSkills`). */
  options: SkillCount[];
  selected: string[];
  match: SkillMatch;
  onChange: (selected: string[], match: SkillMatch) => void;
}

const same = (a: string, b: string) => a.toLowerCase() === b.toLowerCase();

/** What the closed menu says: "Any skill", "Python", "Python or React", "Python + 2 more". */
export function skillsFilterLabel(selected: string[], match: SkillMatch): string {
  if (selected.length === 0) return "Any skill";
  if (selected.length === 1) return selected[0];
  if (selected.length === 2) return selected.join(match === "all" ? " and " : " or ");
  return `${selected[0]} ${match === "all" ? "+" : "or"} ${selected.length - 1} more`;
}

/**
 * The tracker's skills filter: pick any number of skills, and whether a job
 * needs any or all of them. The menu stays open while you pick.
 */
export function SkillsFilter({ id, options, selected, match, onChange }: Props) {
  // A skill you picked stays listed even if a refresh removed its last job.
  const missing = selected.filter((skill) => !options.some((option) => same(option.skill, skill)));
  const listed = [...options, ...missing.map((skill) => ({ skill, count: 0 }))];
  const isSelected = (skill: string) => selected.some((chosen) => same(chosen, skill));

  const toggle = (skill: string, checked: boolean) =>
    onChange(checked ? [...selected, skill] : selected.filter((chosen) => !same(chosen, skill)), match);

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          id={id}
          variant="outline"
          className={cn(
            "w-[200px] justify-between font-normal",
            selected.length === 0 && "text-muted-foreground",
          )}
        >
          <span className="truncate">{skillsFilterLabel(selected, match)}</span>
          <ChevronDownIcon className="text-muted-foreground size-4 opacity-50" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="max-h-[min(28rem,var(--radix-dropdown-menu-content-available-height))] w-64 overflow-y-auto">
        <DropdownMenuLabel className="text-muted-foreground text-xs font-normal">Jobs with</DropdownMenuLabel>
        <DropdownMenuRadioGroup value={match} onValueChange={(value) => onChange(selected, value as SkillMatch)}>
          <DropdownMenuRadioItem value="any" onSelect={(event) => event.preventDefault()}>
            Any of the selected skills
          </DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="all" onSelect={(event) => event.preventDefault()}>
            All of the selected skills
          </DropdownMenuRadioItem>
        </DropdownMenuRadioGroup>
        <DropdownMenuSeparator />
        {listed.length === 0 ? (
          <DropdownMenuLabel className="text-muted-foreground font-normal">No skills matched yet.</DropdownMenuLabel>
        ) : (
          listed.map(({ skill, count }) => (
            <DropdownMenuCheckboxItem
              key={skill}
              checked={isSelected(skill)}
              aria-label={`${skill}, ${count} job${count === 1 ? "" : "s"}`}
              onCheckedChange={(checked) => toggle(skill, checked === true)}
              // Keep the menu open, so several can be picked in a row.
              onSelect={(event) => event.preventDefault()}
            >
              <span className="flex-1 truncate">{skill}</span>
              <span className="text-muted-foreground text-xs tabular-nums" aria-hidden>
                {count}
              </span>
            </DropdownMenuCheckboxItem>
          ))
        )}
        {selected.length > 0 && (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuItem onSelect={() => onChange([], match)}>Clear skills</DropdownMenuItem>
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
