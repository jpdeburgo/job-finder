"use client";

import { FileTextIcon, PlusIcon, RefreshCwIcon, SparklesIcon, StarIcon, Trash2Icon, UploadIcon } from "lucide-react";
import Link from "next/link";
import { useRef, useState } from "react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { analyzeResume, deleteResume, reassessJobs, saveSkills, uploadResume } from "@/lib/client";
import { formatDate } from "@/lib/jobs";
import { describeReassess, reassessProblem, type ReassessNotice } from "@/lib/reassess";
import {
  MAX_RESUME_BYTES,
  METHOD_LABELS,
  RESUME_FILE_TYPES,
  RESUME_METHODS,
  canApply,
  describeReader,
  describeYearsBasis,
  formatMonth,
  formatYears,
  listedAs,
  ratingChange,
  withDetectedSkills,
  type DetectedSkill,
  type RatingChange,
  type Resume,
  type ResumeAnalysis,
  type ResumeMethod,
} from "@/lib/resume";
import { MAX_PROFICIENCY, MIN_PROFICIENCY, PROFICIENCY_LABELS, type SearchSkills, type SkillSettings } from "@/lib/skills";
import type { StoreInfo } from "@/lib/types";
import { cn } from "@/lib/utils";
import { ReassessNoticeAlert } from "./ReassessNoticeAlert";

interface Props {
  initialResume: Resume | null;
  initialSkills: SkillSettings;
  store: StoreInfo;
}

type Busy = "upload" | ResumeMethod | "remove" | "add" | null;
type Problem = { title: string; message: string } | null;
type Rescore = "running" | ReassessNotice | null;

const pick = ({ skills, core_skills, proficiency }: SearchSkills): SearchSkills => ({ skills, core_skills, proficiency });
const plural = (count: number, one: string, many = `${one}s`) => `${count} ${count === 1 ? one : many}`;
const message = (error: unknown) => (error instanceof Error ? error.message : String(error));
const LEVELS = Array.from({ length: MAX_PROFICIENCY - MIN_PROFICIENCY + 1 }, (_, i) => MIN_PROFICIENCY + i);
type Applied = { added: string[]; updated: RatingChange[]; problem: string | null };

/** "Add 2 skills, update 1 rating" for what's ticked. */
function applyLabel(picked: DetectedSkill[], list: SearchSkills): string {
  const adding = picked.filter((skill) => !listedAs(skill, list)).length;
  const updating = picked.length - adding;
  const parts = [adding > 0 && `add ${plural(adding, "skill")}`, updating > 0 && `update ${plural(updating, "rating")}`];
  const text = parts.filter(Boolean).join(", ") || "add to your list";
  return text[0].toUpperCase() + text.slice(1);
}

/**
 * The Resume page: upload your resume, see the skills and years of
 * experience read from it (by parsing, and by AI when it's set up), and add
 * the skills it found to your skill list.
 */
export function ResumePanel({ initialResume, initialSkills, store }: Props) {
  const [resume, setResume] = useState(initialResume);
  const [skills, setSkills] = useState(initialSkills);
  const [view, setView] = useState<ResumeMethod>(initialResume?.analyses.ai ? "ai" : "parse");
  const [busy, setBusy] = useState<Busy>(null);
  const [problem, setProblem] = useState<Problem>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [applied, setApplied] = useState<Applied | null>(null);
  const [rescore, setRescore] = useState<Rescore>(null);

  const run = async (kind: Exclude<Busy, null>, title: string, action: () => Promise<void>) => {
    setBusy(kind);
    setProblem(null);
    try {
      await action();
    } catch (error) {
      setProblem({ title, message: message(error) });
    } finally {
      setBusy(null);
    }
  };

  const showResume = (next: Resume | null, method: ResumeMethod = "parse") => {
    setResume(next);
    setView(method);
    setSelected(new Set());
    setApplied(null);
  };

  const upload = (source: File | string) =>
    run("upload", "Couldn't read your resume", async () => {
      if (typeof source !== "string" && source.size > MAX_RESUME_BYTES) {
        throw new Error(`The file is too big: a resume can be at most ${MAX_RESUME_BYTES / (1024 * 1024)} MB.`);
      }
      showResume(await uploadResume(source));
    });

  const analyze = (method: ResumeMethod) =>
    run(method, method === "ai" ? "Couldn't read it with AI" : "Couldn't parse it again", async () => {
      showResume(await analyzeResume(method), method);
    });

  const remove = () =>
    run("remove", "Couldn't remove your resume", async () => {
      await deleteResume();
      showResume(null);
    });

  const applySelected = (analysis: ResumeAnalysis) =>
    run("add", "Couldn't update your skills", async () => {
      const result = withDetectedSkills(pick(skills), analysis.skills.filter((skill) => selected.has(skill.name)));
      if (result.added.length + result.updated.length === 0) {
        throw new Error(result.problem ?? "They're all on your list already, with those stars");
      }
      setSkills(await saveSkills(result.list));
      setSelected(new Set());
      setApplied({ added: result.added, updated: result.updated, problem: result.problem });
      // Re-score saved jobs against the new list, like saving on the Skills page.
      setRescore("running");
      reassessJobs()
        .then((summary) => setRescore(describeReassess(summary)))
        .catch((error) => setRescore(reassessProblem(error, "save")));
    });

  const analysis = resume?.analyses[view] ?? null;

  return (
    <div className="space-y-6">
      <div className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight">Resume</h1>
        <p className="text-muted-foreground text-sm">
          Upload your resume to see the skills and years of experience it shows. Parsing reads it with rules, instantly;
          AI reads it with a language model, which copes better with unusual layouts. Add the skills it finds to the{" "}
          <Link href="/skills" className="text-foreground font-medium underline underline-offset-4">
            skills
          </Link>{" "}
          the search looks for.
        </p>
      </div>

      <UploadCard resume={resume} busy={busy} store={store} onUpload={upload} onRemove={remove} />

      {problem && (
        <Alert variant="destructive" role="alert">
          <AlertTitle>{problem.title}</AlertTitle>
          <AlertDescription>{problem.message}</AlertDescription>
        </Alert>
      )}

      {applied && (
        <Alert role="status" data-testid="skills-added">
          <AlertTitle>
            {[
              applied.added.length > 0 && `Added ${plural(applied.added.length, "skill")} to your list`,
              applied.updated.length > 0 && `${applied.added.length > 0 ? "updated" : "Updated"} the stars for ${plural(applied.updated.length, "skill")}`,
            ]
              .filter(Boolean)
              .join(" and ")}
          </AlertTitle>
          <AlertDescription>
            {applied.added.length > 0 && <p>Added as core skills: {applied.added.join(", ")}.</p>}
            {applied.updated.length > 0 && (
              <p>New stars: {applied.updated.map((change) => `${change.name} ${change.from}★ → ${change.to}★`).join(", ")}.</p>
            )}
            {applied.problem && <p>{applied.problem}.</p>}
            <p>
              New skills get the stars your resume suggests. Adjust them, and move any that aren&apos;t your main stack
              (tools, cloud, CI) down to other skills, on the{" "}
              <Link href="/skills" className="text-foreground font-medium underline underline-offset-4">
                Skills
              </Link>{" "}
              page.
            </p>
          </AlertDescription>
        </Alert>
      )}
      {rescore === "running" && (
        <p className="text-muted-foreground text-sm" aria-live="polite">
          Re-scoring your saved jobs against your skills…
        </p>
      )}
      {rescore && rescore !== "running" && <ReassessNoticeAlert notice={rescore} onDismiss={() => setRescore(null)} />}

      {resume && (
        <Card>
          <CardHeader>
            <CardTitle>What your resume shows</CardTitle>
            <CardDescription className="col-start-1">
              {analysis ? `${describeReader(analysis)}${analysis.analyzed_at ? `, ${formatDate(analysis.analyzed_at)}` : ""}.` : null}
            </CardDescription>
            {/* Under the title on phones, beside it from sm up. */}
            <CardAction className="col-start-1 row-span-1 row-start-3 flex flex-wrap items-center gap-2 justify-self-start sm:col-start-2 sm:row-span-2 sm:row-start-1 sm:justify-self-end">
              <ToggleGroup
                type="single"
                variant="outline"
                size="sm"
                aria-label="Reading"
                value={view}
                onValueChange={(value) => value && setView(value as ResumeMethod)}
              >
                {RESUME_METHODS.map((method) => (
                  <ToggleGroupItem key={method} value={method} className="px-3">
                    {METHOD_LABELS[method]}
                  </ToggleGroupItem>
                ))}
              </ToggleGroup>
              {analysis && (
                <Button variant="ghost" size="sm" disabled={busy !== null} onClick={() => analyze(view)}>
                  <RefreshCwIcon className={busy === view ? "animate-spin" : undefined} />
                  {busy === view ? "Reading…" : "Read again"}
                </Button>
              )}
            </CardAction>
          </CardHeader>
          <CardContent className="space-y-6">
            {analysis ? (
              <AnalysisView
                analysis={analysis}
                list={skills}
                selected={selected}
                busy={busy}
                onSelect={setSelected}
                onAdd={() => applySelected(analysis)}
              />
            ) : (
              <NotReadYet method={view} busy={busy} onRead={() => analyze(view)} />
            )}
            <details className="group">
              <summary className="text-muted-foreground hover:text-foreground cursor-pointer text-sm">
                Text read from {resume.filename}
              </summary>
              <pre className="bg-muted mt-2 max-h-96 overflow-auto rounded-md p-3 text-xs whitespace-pre-wrap">
                {resume.text}
              </pre>
            </details>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

interface UploadProps {
  resume: Resume | null;
  busy: Busy;
  store: StoreInfo;
  onUpload: (source: File | string) => void;
  onRemove: () => void;
}

/** Choose a file (or paste the text) to upload; shows the resume saved now. */
function UploadCard({ resume, busy, store, onUpload, onRemove }: UploadProps) {
  const input = useRef<HTMLInputElement>(null);
  const [pasting, setPasting] = useState(false);
  const [text, setText] = useState("");
  const [confirming, setConfirming] = useState(false);
  const where = store.emulator ? "the Firestore emulator" : store.backend === "local" ? "the local file" : "Firestore";

  return (
    <Card>
      <CardHeader>
        <CardTitle>{resume ? "Your resume" : "Upload your resume"}</CardTitle>
        <CardDescription>
          {resume ? (
            <span className="inline-flex flex-wrap items-center gap-x-1.5">
              <FileTextIcon className="size-4" aria-hidden />
              <span className="text-foreground font-medium">{resume.filename}</span>
              {resume.uploaded_at && <span>uploaded {formatDate(resume.uploaded_at)},</span>}
              <span title={store.description}>saved in {where}.</span>
              <span>Uploading another replaces it.</span>
            </span>
          ) : (
            <>PDF, Word (.docx), or plain text, up to {MAX_RESUME_BYTES / (1024 * 1024)} MB. Or paste the text.</>
          )}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <input
            ref={input}
            type="file"
            accept={RESUME_FILE_TYPES}
            className="sr-only"
            aria-label="Resume file"
            tabIndex={-1}
            onChange={(event) => {
              const file = event.target.files?.[0];
              event.target.value = ""; // choosing the same file again still uploads it
              if (file) onUpload(file);
            }}
          />
          <Button disabled={busy !== null} onClick={() => input.current?.click()}>
            <UploadIcon />
            {busy === "upload" ? "Reading…" : resume ? "Upload a new resume" : "Choose a file"}
          </Button>
          <Button variant="outline" disabled={busy !== null} onClick={() => setPasting((open) => !open)} aria-expanded={pasting}>
            Paste text
          </Button>
          {resume &&
            (confirming ? (
              <span className="flex items-center gap-2 sm:ml-auto">
                <span className="text-sm">Remove your resume? Your skills stay as they are.</span>
                <Button variant="destructive" size="sm" disabled={busy !== null} onClick={() => { setConfirming(false); onRemove(); }}>
                  Remove
                </Button>
                <Button variant="ghost" size="sm" onClick={() => setConfirming(false)}>
                  Cancel
                </Button>
              </span>
            ) : (
              <Button variant="ghost" size="sm" className="sm:ml-auto" disabled={busy !== null} onClick={() => setConfirming(true)}>
                <Trash2Icon />
                {busy === "remove" ? "Removing…" : "Remove"}
              </Button>
            ))}
        </div>
        {pasting && (
          <form
            className="space-y-2"
            onSubmit={(event) => {
              event.preventDefault();
              if (!text.trim()) return;
              onUpload(text);
              setPasting(false);
              setText("");
            }}
          >
            <Textarea
              aria-label="Resume text"
              value={text}
              onChange={(event) => setText(event.target.value)}
              placeholder="Paste your resume here"
              className="min-h-48 font-mono text-xs"
              disabled={busy !== null}
            />
            <Button type="submit" size="sm" disabled={busy !== null || !text.trim()}>
              Use this text
            </Button>
          </form>
        )}
      </CardContent>
    </Card>
  );
}

/** A reading that hasn't been done yet (only AI: every upload is parsed). */
function NotReadYet({ method, busy, onRead }: { method: ResumeMethod; busy: Busy; onRead: () => void }) {
  return (
    <div className="space-y-3 rounded-md border border-dashed p-6 text-center">
      <p className="text-sm">
        {method === "ai"
          ? "Not read with AI yet. It sends the resume's text to the AI provider set up in backend/.env and takes up to a minute."
          : "Not parsed yet."}
      </p>
      <Button onClick={onRead} disabled={busy !== null}>
        <SparklesIcon />
        {busy === method ? "Reading…" : method === "ai" ? "Read with AI" : "Parse it"}
      </Button>
    </div>
  );
}

interface AnalysisProps {
  analysis: ResumeAnalysis;
  list: SearchSkills;
  selected: Set<string>;
  busy: Busy;
  onSelect: (selected: Set<string>) => void;
  onAdd: () => void;
}

function AnalysisView({ analysis, list, selected, busy, onSelect, onAdd }: AnalysisProps) {
  const fresh = analysis.skills.filter((skill) => !listedAs(skill, list));
  const actionable = analysis.skills.filter((skill) => canApply(skill, list));
  const picked = analysis.skills.filter((skill) => selected.has(skill.name));
  const toggle = (name: string, on: boolean) => {
    const next = new Set(selected);
    if (on) next.add(name);
    else next.delete(name);
    onSelect(next);
  };

  return (
    <>
      <dl className="grid gap-4 sm:grid-cols-3">
        <Stat label="Years of experience" value={formatYears(analysis.years_experience)} hint={describeYearsBasis(analysis)} />
        <Stat
          label="Skills found"
          value={String(analysis.skills.length)}
          hint={`${plural(analysis.skills.length - fresh.length, "is", "are")} on your list already`}
        />
        <Stat
          label="Jobs in your work history"
          value={String(analysis.positions.length)}
          hint={analysis.stated_years !== null ? `The resume itself says ${analysis.stated_years} years` : "Education and projects don't count"}
        />
      </dl>

      {analysis.notes.length > 0 && (
        <ul className="text-muted-foreground list-disc space-y-1 pl-5 text-sm" aria-label="Notes">
          {analysis.notes.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      )}

      <section className="space-y-2" aria-labelledby="resume-skills">
        <div className="flex flex-wrap items-center gap-2">
          <h2 id="resume-skills" className="text-sm font-medium">
            Skills
          </h2>
          <span className="text-muted-foreground text-xs">
            Stars are how well your resume suggests you know each skill, with the reason under them. Years come from the
            jobs that mention a skill; a skill only listed (in a Skills section, say) has none.
          </span>
          <div className="flex flex-wrap items-center gap-2 sm:ml-auto">
            {actionable.length > 0 && (
              <Button
                variant="ghost"
                size="sm"
                disabled={busy !== null}
                onClick={() =>
                  onSelect(picked.length === actionable.length ? new Set() : new Set(actionable.map((s) => s.name)))
                }
              >
                {picked.length === actionable.length ? "Clear" : `Select all ${actionable.length}`}
              </Button>
            )}
            <Button size="sm" disabled={busy !== null || picked.length === 0} onClick={onAdd}>
              <PlusIcon />
              {busy === "add" ? "Saving…" : applyLabel(picked, list)}
            </Button>
          </div>
        </div>
        {analysis.skills.length === 0 ? (
          <p className="text-muted-foreground text-sm italic">No skills found.</p>
        ) : (
          <SkillsTable skills={analysis.skills} list={list} selected={selected} disabled={busy !== null} onToggle={toggle} />
        )}
      </section>

      <section className="space-y-2" aria-labelledby="resume-jobs">
        <h2 id="resume-jobs" className="text-sm font-medium">
          Jobs counted
        </h2>
        {analysis.positions.length === 0 ? (
          <p className="text-muted-foreground text-sm italic">No jobs with dates found.</p>
        ) : (
          <Table aria-labelledby="resume-jobs">
            <TableHeader>
              <TableRow>
                <TableHead>Job</TableHead>
                <TableHead>Dates</TableHead>
                <TableHead>Length</TableHead>
                <TableHead>Skills</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {analysis.positions.map((position, index) => (
                <TableRow key={`${position.start}-${index}`}>
                  <TableCell className="max-w-80 whitespace-normal">
                    <span className="font-medium">{position.title || "Untitled"}</span>
                    {position.company && <span className="text-muted-foreground"> · {position.company}</span>}
                  </TableCell>
                  <TableCell className="whitespace-nowrap">
                    {formatMonth(position.start)} – {formatMonth(position.end)}
                  </TableCell>
                  <TableCell className="whitespace-nowrap">{formatYears(position.months / 12)}</TableCell>
                  <TableCell className="text-muted-foreground max-w-96 text-xs whitespace-normal">
                    {position.skills.join(", ") || "—"}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </section>
    </>
  );
}

function Stat({ label, value, hint }: { label: string; value: string; hint: string }) {
  return (
    <div className="rounded-md border p-4">
      <dt className="text-muted-foreground text-xs">{label}</dt>
      <dd className="text-2xl font-semibold tracking-tight">{value}</dd>
      <dd className="text-muted-foreground text-xs">{hint}</dd>
    </div>
  );
}

interface SkillsTableProps {
  skills: DetectedSkill[];
  list: SearchSkills;
  selected: Set<string>;
  disabled: boolean;
  onToggle: (name: string, on: boolean) => void;
}

function SkillsTable({ skills, list, selected, disabled, onToggle }: SkillsTableProps) {
  return (
    <Table aria-label="Skills found">
      <TableHeader>
        <TableRow>
          <TableHead className="w-8">
            <span className="sr-only">Add</span>
          </TableHead>
          <TableHead>Skill</TableHead>
          <TableHead>Level</TableHead>
          <TableHead>Years</TableHead>
          <TableHead>Last used</TableHead>
          <TableHead>Mentions</TableHead>
          <TableHead>Category</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {skills.map((skill) => {
          const listed = listedAs(skill, list);
          const change = ratingChange(skill, list);
          return (
            <TableRow key={skill.name} data-skill={skill.name}>
              <TableCell>
                {(!listed || change) && (
                  <input
                    type="checkbox"
                    className="accent-primary size-4 cursor-pointer align-middle disabled:cursor-default"
                    aria-label={
                      change ? `Update ${change.name} to ${change.to} stars` : `Add ${skill.name} to your skills`
                    }
                    checked={selected.has(skill.name)}
                    disabled={disabled}
                    onChange={(event) => onToggle(skill.name, event.target.checked)}
                  />
                )}
              </TableCell>
              <TableCell className="font-medium">
                <span className="flex flex-wrap items-center gap-2">
                  {skill.name}
                  {listed && (
                    <Badge variant="secondary" title={listed === skill.name ? undefined : `On your list as ${listed}`}>
                      On your list{listed === skill.name ? "" : ` (${listed})`}
                    </Badge>
                  )}
                </span>
              </TableCell>
              <TableCell className="min-w-56 whitespace-normal">
                <Stars level={skill.level} />
                {skill.level_reason && <p className="text-muted-foreground text-xs">{skill.level_reason}</p>}
                {change && <p className="text-xs">You rated it {change.from}★</p>}
              </TableCell>
              <TableCell title={skill.years === null ? "No job on the resume mentions it" : undefined}>
                {skill.years === null ? <span className="text-muted-foreground">Listed</span> : formatYears(skill.years)}
              </TableCell>
              <TableCell>{skill.last_used ? formatMonth(skill.last_used) : "—"}</TableCell>
              <TableCell>
                {skill.mentions > 0 ? (
                  `${skill.mentions}×`
                ) : (
                  <span className="text-muted-foreground" title="The AI named it, but the resume doesn't use that word">
                    Inferred
                  </span>
                )}
              </TableCell>
              <TableCell className="text-muted-foreground">{skill.category}</TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}

/** 1-5 stars, read-only, with the Skills page's label ("Advanced"). */
function Stars({ level }: { level: number | null }) {
  if (level === null) return <span className="text-muted-foreground">—</span>;
  return (
    <span className="inline-flex items-center gap-1.5" role="img" aria-label={`${level} of 5 stars: ${PROFICIENCY_LABELS[level]}`}>
      <span className="flex" aria-hidden>
        {LEVELS.map((stars) => (
          <StarIcon
            key={stars}
            className={cn("size-3.5", stars <= level ? "fill-amber-400 text-amber-500" : "text-muted-foreground/40")}
          />
        ))}
      </span>
      <span className="text-xs font-medium" aria-hidden>
        {PROFICIENCY_LABELS[level]}
      </span>
    </span>
  );
}
