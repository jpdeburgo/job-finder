"use client";

import { ArrowDownIcon, ArrowUpIcon, PlusIcon, RotateCcwIcon, StarIcon, XIcon } from "lucide-react";
import Link from "next/link";
import { useId, useRef, useState } from "react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { reassessJobs, resetSkills, saveSkills } from "@/lib/client";
import { formatDate } from "@/lib/jobs";
import { describeReassess, reassessProblem, type ReassessNotice } from "@/lib/reassess";
import {
  DEFAULT_PROFICIENCY,
  MAX_PROFICIENCY,
  MIN_PROFICIENCY,
  MIN_SKILL_MATCHES,
  PROFICIENCY_LABELS,
  addSkills,
  removeSkill,
  sameSkills,
  setCore,
  setProficiency,
  skillsProblem,
  type SearchSkills,
  type SkillSettings,
} from "@/lib/skills";
import type { StoreInfo } from "@/lib/types";
import { cn } from "@/lib/utils";
import { ReassessNoticeAlert } from "./ReassessNoticeAlert";

interface Props {
  initialSettings: SkillSettings;
  store: StoreInfo;
}

const STORE_LABEL = { local: "the local file", firestore: "Firestore" } as const;
const LEVELS = Array.from({ length: MAX_PROFICIENCY - MIN_PROFICIENCY + 1 }, (_, i) => MIN_PROFICIENCY + i);

type Outcome = { kind: "saved" | "reset" } | { kind: "error"; message: string } | null;
/** Re-scoring the saved jobs after a save: running, or what it did. */
type Rescore = "running" | ReassessNotice | null;

const pick = ({ skills, core_skills, proficiency }: SearchSkills): SearchSkills => ({ skills, core_skills, proficiency });
const starsText = (stars: number) => `${stars} star${stars === 1 ? "" : "s"}`;

/**
 * The Skills page: add, remove, and rank (core or other) the skills the
 * search looks for, rate how well you know each (1-5 stars), then save them.
 * Saving re-scores the jobs you've already saved (through the search API).
 */
export function SkillsEditor({ initialSettings, store }: Props) {
  const [saved, setSaved] = useState(initialSettings);
  const [draft, setDraft] = useState<SearchSkills>(() => pick(initialSettings));
  const [busy, setBusy] = useState(false);
  const [confirmingReset, setConfirmingReset] = useState(false);
  const [outcome, setOutcome] = useState<Outcome>(null);
  const [rescore, setRescore] = useState<Rescore>(null);
  // Bumped on save, reset, and discard so the Add boxes start over (no stale "already listed").
  const [version, setVersion] = useState(0);

  const rescoring = rescore === "running";
  const dirty = !sameSkills(draft, saved);
  const problem = skillsProblem(draft);
  const core = new Set(draft.core_skills);
  const coreSkills = draft.skills.filter((name) => core.has(name));
  const otherSkills = draft.skills.filter((name) => !core.has(name));
  const where = store.emulator ? "the Firestore emulator" : STORE_LABEL[store.backend];

  const edit = (next: SearchSkills) => {
    setDraft(next);
    setOutcome(null);
  };

  /** Re-score the saved jobs against what was just saved (fit scores and matches). */
  const rescoreJobs = async () => {
    setRescore("running");
    try {
      setRescore(describeReassess(await reassessJobs()));
    } catch (caught) {
      setRescore(reassessProblem(caught, "save"));
    }
  };

  const apply = async (request: () => Promise<SkillSettings>, kind: "saved" | "reset") => {
    setBusy(true);
    let ok = false;
    try {
      const settings = await request();
      setSaved(settings);
      setDraft(pick(settings));
      setVersion((v) => v + 1);
      setOutcome({ kind });
      ok = true;
    } catch (error) {
      setOutcome({ kind: "error", message: (error as Error).message });
    } finally {
      setBusy(false);
      setConfirmingReset(false);
    }
    if (ok) await rescoreJobs();
  };

  const groupProps = {
    proficiency: draft.proficiency,
    disabled: busy,
    onRemove: (name: string) => edit(removeSkill(draft, name)),
    onRate: (name: string, stars: number) => edit(setProficiency(draft, name, stars)),
  };

  return (
    <div className="space-y-6">
      <div className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight">Skills</h1>
        <p className="text-muted-foreground text-sm">
          What the search looks for in each posting, and how well you know it.{" "}
          {saved.source === "saved" ? (
            <>
              Your list, saved {saved.updated_at ? `on ${formatDate(saved.updated_at)} ` : ""}in{" "}
              <span title={store.description}>{where}</span>.
            </>
          ) : (
            <>
              These are the defaults from <code>backend/job_search.py</code>; save to use your own.
            </>
          )}
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Skills you&apos;re searching for</CardTitle>
          <CardDescription className="space-y-2">
            <span className="block">
              A Core-track job needs at least {MIN_SKILL_MATCHES} of these in its title or description, including at
              least one core skill. Matching ignores case and whole words only, so &ldquo;Java&rdquo; doesn&apos;t match
              &ldquo;JavaScript&rdquo;.
            </span>
            <span className="block">
              <strong className="text-foreground font-medium">Stars</strong> say how well you know each skill. They
              don&apos;t change which jobs match, only the fit score: a core skill counts twice as much as any other, and
              stars scale that. {starsText(DEFAULT_PROFICIENCY)} ({PROFICIENCY_LABELS[DEFAULT_PROFICIENCY]}, where new
              skills start) counts as is; fewer counts less, more counts more.
            </span>
          </CardDescription>
          <CardAction>
            <Badge variant={saved.source === "saved" ? "default" : "secondary"}>
              {saved.source === "saved" ? "Your list" : "Defaults"}
            </Badge>
          </CardAction>
        </CardHeader>

        <CardContent className="space-y-6">
          <SkillGroup
            key={`core-${version}`}
            title="Core skills"
            hint="Your main stack. Every Core-track match needs at least one of these."
            names={coreSkills}
            core
            empty="No core skills yet. Add one, or move one of your other skills up."
            onAdd={(text) => {
              const result = addSkills(draft, text, true);
              edit(result.list);
              return result;
            }}
            onMove={(name) => edit(setCore(draft, name, false))}
            {...groupProps}
          />
          <SkillGroup
            key={`other-${version}`}
            title="Other skills"
            hint="Tools and platforms that support your main stack: databases, cloud, CI, and so on."
            names={otherSkills}
            core={false}
            empty="No other skills."
            onAdd={(text) => {
              const result = addSkills(draft, text, false);
              edit(result.list);
              return result;
            }}
            onMove={(name) => edit(setCore(draft, name, true))}
            {...groupProps}
          />
        </CardContent>

        <CardFooter className="flex-wrap gap-3 border-t">
          <Button
            onClick={() => apply(() => saveSkills(draft), "saved")}
            disabled={!dirty || !!problem || busy || rescoring}
          >
            {busy && !confirmingReset ? "Saving…" : "Save skills"}
          </Button>
          <Button
            variant="outline"
            onClick={() => {
              edit(pick(saved));
              setVersion((v) => v + 1);
            }}
            disabled={!dirty || busy}
          >
            Discard changes
          </Button>
          <p className="text-muted-foreground text-xs" role="status" data-testid="save-status">
            {dirty && problem ? (
              <span className="text-destructive">{problem}.</span>
            ) : dirty ? (
              "Unsaved changes"
            ) : outcome?.kind === "saved" ? (
              "Saved. The next search will use these skills."
            ) : outcome?.kind === "reset" ? (
              "Back to the defaults. The next search will use them."
            ) : null}
          </p>

          {saved.source === "saved" && (
            <div className="flex items-center gap-2 sm:ml-auto">
              {confirmingReset ? (
                <>
                  <span className="text-sm">Forget your list and use the defaults?</span>
                  <Button variant="destructive" size="sm" disabled={busy} onClick={() => apply(resetSkills, "reset")}>
                    {busy ? "Resetting…" : "Reset"}
                  </Button>
                  <Button variant="ghost" size="sm" disabled={busy} onClick={() => setConfirmingReset(false)}>
                    Cancel
                  </Button>
                </>
              ) : (
                <Button variant="ghost" size="sm" disabled={busy || rescoring} onClick={() => setConfirmingReset(true)}>
                  <RotateCcwIcon />
                  Reset to defaults
                </Button>
              )}
            </div>
          )}
        </CardFooter>
      </Card>

      {outcome?.kind === "error" && (
        <Alert variant="destructive">
          <AlertTitle>Couldn&apos;t save your skills</AlertTitle>
          <AlertDescription>{outcome.message}</AlertDescription>
        </Alert>
      )}

      {rescoring && (
        <p className="text-muted-foreground text-sm" aria-live="polite">
          Re-scoring your saved jobs against these skills… The first time, each job&apos;s description is loaded from its
          site, which can take a minute.
        </p>
      )}
      {rescore && rescore !== "running" && (
        <ReassessNoticeAlert notice={rescore} onDismiss={() => setRescore(null)}>
          {rescore.tone === "info" && (
            <p>
              <Link href="/jobs" className="text-foreground font-medium underline underline-offset-4">
                See your jobs
              </Link>
            </p>
          )}
        </ReassessNoticeAlert>
      )}

      <p className="text-muted-foreground text-sm">
        Saving re-scores the jobs you&apos;ve already saved (this needs the search API running; otherwise click{" "}
        <strong>Refresh</strong> on the{" "}
        <Link href="/jobs" className="text-foreground font-medium underline underline-offset-4">
          Jobs
        </Link>{" "}
        page later). Jobs that no longer match are marked, not removed. New jobs are found with these skills from the
        next search: the daily run, or{" "}
        <Link href="/" className="text-foreground font-medium underline underline-offset-4">
          Run search
        </Link>{" "}
        on the home screen.
      </p>
    </div>
  );
}

interface GroupProps {
  title: string;
  hint: string;
  names: string[];
  core: boolean;
  proficiency: Record<string, number>;
  disabled: boolean;
  empty: string;
  onAdd: (text: string) => { added: string[]; problem: string | null };
  onRemove: (name: string) => void;
  onMove: (name: string) => void;
  onRate: (name: string, stars: number) => void;
}

/** One group of skills (core or other): each with its stars, and a box to add more. */
function SkillGroup({ title, hint, names, core, proficiency, disabled, empty, onAdd, onRemove, onMove, onRate }: GroupProps) {
  const id = useId();
  const [text, setText] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const label = core ? "Add a core skill" : "Add another skill";

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    if (!text.trim()) return;
    const { added, problem } = onAdd(text);
    setMessage(problem);
    if (added.length > 0 || !problem) setText("");
  };

  return (
    <section aria-labelledby={`${id}-title`} className="space-y-2">
      <div>
        <h2 id={`${id}-title`} className="flex items-center gap-2 text-sm font-medium">
          {title}
          <span className="text-muted-foreground font-normal">({names.length})</span>
        </h2>
        <p className="text-muted-foreground text-xs">{hint}</p>
      </div>

      {names.length === 0 ? (
        <p className="text-muted-foreground text-sm italic">{empty}</p>
      ) : (
        <ul aria-label={title} className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
          {names.map((name) => {
            const stars = proficiency[name] ?? DEFAULT_PROFICIENCY;
            return (
              <li
                key={name}
                data-skill={name}
                className="bg-secondary/60 text-secondary-foreground flex min-w-0 items-center gap-1.5 rounded-md border py-1 pr-1 pl-3"
              >
                <span className="min-w-0 flex-1 truncate text-sm font-medium" title={name}>
                  {name}
                </span>
                <StarRating skill={name} value={stars} disabled={disabled} onChange={(value) => onRate(name, value)} />
                <span className="text-muted-foreground hidden w-[4.75rem] text-xs sm:inline" aria-hidden>
                  {PROFICIENCY_LABELS[stars]}
                </span>
                <Button
                  variant="ghost"
                  size="icon-xs"
                  disabled={disabled}
                  onClick={() => onMove(name)}
                  aria-label={core ? `Move ${name} to other skills` : `Make ${name} a core skill`}
                  title={core ? "Move to other skills" : "Make it a core skill"}
                >
                  {core ? <ArrowDownIcon /> : <ArrowUpIcon />}
                </Button>
                <Button
                  variant="ghost"
                  size="icon-xs"
                  disabled={disabled}
                  onClick={() => onRemove(name)}
                  aria-label={`Remove ${name}`}
                  title="Remove"
                >
                  <XIcon />
                </Button>
              </li>
            );
          })}
        </ul>
      )}

      <form onSubmit={submit} className="flex max-w-md gap-2">
        <Input
          aria-label={label}
          aria-describedby={message ? `${id}-message` : undefined}
          aria-invalid={message ? true : undefined}
          value={text}
          onChange={(event) => {
            setText(event.target.value);
            setMessage(null);
          }}
          placeholder={core ? "e.g. Go, Kotlin" : "e.g. Kubernetes, PostgreSQL"}
          disabled={disabled}
          className="h-8"
        />
        <Button type="submit" size="sm" variant="outline" disabled={disabled || !text.trim()}>
          <PlusIcon />
          Add
        </Button>
      </form>
      {message && (
        <p id={`${id}-message`} className="text-destructive text-xs">
          {message}.
        </p>
      )}
    </section>
  );
}

interface StarRatingProps {
  skill: string;
  value: number;
  disabled: boolean;
  onChange: (stars: number) => void;
}

/**
 * 1-5 stars, as a radio group: click a star (hovering previews it), or focus
 * the group and use the arrow keys, Home, and End.
 */
function StarRating({ skill, value, disabled, onChange }: StarRatingProps) {
  const [hover, setHover] = useState<number | null>(null);
  const buttons = useRef<(HTMLButtonElement | null)[]>([]);
  const shown = hover ?? value;

  const choose = (stars: number) => {
    const next = Math.min(MAX_PROFICIENCY, Math.max(MIN_PROFICIENCY, stars));
    onChange(next);
    buttons.current[next - MIN_PROFICIENCY]?.focus();
  };

  const onKeyDown = (event: React.KeyboardEvent) => {
    const next = {
      ArrowRight: value + 1,
      ArrowUp: value + 1,
      ArrowLeft: value - 1,
      ArrowDown: value - 1,
      Home: MIN_PROFICIENCY,
      End: MAX_PROFICIENCY,
    }[event.key];
    if (next === undefined) return;
    event.preventDefault();
    choose(next);
  };

  return (
    <div
      role="radiogroup"
      aria-label={`How well you know ${skill}`}
      className="flex shrink-0"
      onMouseLeave={() => setHover(null)}
    >
      {LEVELS.map((stars) => (
        <button
          key={stars}
          ref={(element) => {
            buttons.current[stars - MIN_PROFICIENCY] = element;
          }}
          type="button"
          role="radio"
          aria-checked={stars === value}
          aria-label={`${starsText(stars)}: ${PROFICIENCY_LABELS[stars]}`}
          title={`${PROFICIENCY_LABELS[stars]} (${starsText(stars)})`}
          // One tab stop for the group: the chosen star. Arrows move from there.
          tabIndex={stars === value ? 0 : -1}
          disabled={disabled}
          onMouseEnter={() => setHover(stars)}
          onClick={() => choose(stars)}
          onKeyDown={onKeyDown}
          className="focus-visible:ring-ring/50 cursor-pointer rounded-sm p-0.5 outline-none focus-visible:ring-[3px] disabled:cursor-default disabled:opacity-50"
        >
          <StarIcon
            className={cn(
              "size-4 transition-colors",
              stars <= shown ? "fill-amber-400 text-amber-500" : "text-muted-foreground/40",
            )}
          />
        </button>
      ))}
    </div>
  );
}
