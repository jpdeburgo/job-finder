"use client";

import { CheckIcon, ExternalLinkIcon, MailIcon, SearchIcon, XIcon } from "lucide-react";
import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Textarea } from "@/components/ui/textarea";
import {
  formatDate,
  formatLocation,
  formatSalary,
  formatYears,
  gmailMessageUrl,
  insightGlobalSearchUrl,
} from "@/lib/jobs";
import type { Job, JobStatus } from "@/lib/types";
import { ExternalLink } from "./ExternalLink";
import { RemoteLabel } from "./RemoteLabel";
import { StatusBadge } from "./StatusBadge";

interface Props {
  job: Job;
  busy: boolean;
  onStatusChange: (status: JobStatus) => void;
  onNotesSave: (notes: string) => Promise<void>;
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-muted-foreground text-xs font-medium tracking-wide uppercase">{label}</dt>
      <dd className="text-sm break-words">{children}</dd>
    </div>
  );
}

function Timestamp({ value }: { value: string | null }) {
  if (!value) return <span className="text-muted-foreground">—</span>;
  return (
    <time dateTime={value} title={value}>
      {value.replace("T", " ").slice(0, 16)} UTC
    </time>
  );
}

/**
 * Contents of the details drawer: every field, all links, quick actions, and
 * a notes editor. Rendered inside a `Sheet` by `JobsDashboard`.
 */
export function JobDetails({ job, busy, onStatusChange, onNotesSave }: Props) {
  // JobsDashboard keys this component by the saved notes, so a server-side
  // change remounts it with fresh state instead of needing an effect.
  const [notes, setNotes] = useState(job.notes ?? "");
  const [saving, setSaving] = useState(false);

  const dirty = notes.trim() !== (job.notes ?? "").trim();
  const gmail = gmailMessageUrl(job.gmail_message_id);
  const search = insightGlobalSearchUrl(job.title);

  const save = async () => {
    setSaving(true);
    try {
      await onNotesSave(notes.trim());
    } finally {
      setSaving(false);
    }
  };

  return (
    <SheetContent className="w-full overflow-y-auto sm:max-w-xl" data-testid={`job-details-${job.id}`}>
      <SheetHeader>
        <div className="flex items-center gap-2 pr-6">
          <StatusBadge status={job.status} />
          <RemoteLabel job={job} badge />
        </div>
        <SheetTitle className="text-lg leading-snug">
          {job.url ? (
            <ExternalLink href={job.url} className="text-foreground">
              {job.title ?? job.job_id}
            </ExternalLink>
          ) : (
            (job.title ?? job.job_id)
          )}
        </SheetTitle>
        <SheetDescription>
          {[job.company, formatLocation(job), job.job_type, formatSalary(job)].filter(Boolean).join(" · ")}
        </SheetDescription>
      </SheetHeader>

      <div className="space-y-6 px-4 pb-6">
        <div className="flex flex-wrap gap-2">
          {job.url && (
            <Button asChild>
              <a href={job.url} target="_blank" rel="noopener noreferrer">
                <ExternalLinkIcon />
                Open &amp; apply
              </a>
            </Button>
          )}
          <Button
            variant="outline"
            disabled={busy || job.status === "applied"}
            onClick={() => onStatusChange("applied")}
          >
            <CheckIcon />
            Mark applied
          </Button>
          <Button
            variant="outline"
            disabled={busy || job.status === "interviewing"}
            onClick={() => onStatusChange("interviewing")}
          >
            Interviewing
          </Button>
          <Button variant="ghost" disabled={busy || job.status === "skipped"} onClick={() => onStatusChange("skipped")}>
            <XIcon />
            Skip
          </Button>
        </div>

        <Separator />

        <dl className="grid grid-cols-2 gap-x-4 gap-y-3">
          <Field label="Job ID">
            <code className="text-xs">{job.job_id}</code>
          </Field>
          <Field label="Track">{job.track ?? "—"}</Field>
          <Field label="Location">{formatLocation(job)}</Field>
          <Field label="Job type">{job.job_type ?? "—"}</Field>
          <Field label="Salary">{formatSalary(job)}</Field>
          <Field label="Experience">{formatYears(job.min_years)}</Field>
          <Field label="Posted">{formatDate(job.posted_date)}</Field>
          <Field label="First seen">
            <Timestamp value={job.first_seen_at} />
          </Field>
          <Field label="Last seen">
            <Timestamp value={job.last_seen_at} />
          </Field>
          <Field label="Emailed">
            <Timestamp value={job.emailed_at} />
          </Field>
          <Field label="Applied">
            <Timestamp value={job.applied_at} />
          </Field>
          <Field label="Status updated">
            <Timestamp value={job.status_updated_at} />
          </Field>
        </dl>

        {job.matched_skills.length > 0 && (
          <div>
            <div className="text-muted-foreground text-xs font-medium tracking-wide uppercase">
              Matched skills ({job.score ?? job.matched_skills.length})
            </div>
            <ul className="mt-1.5 flex flex-wrap gap-1.5">
              {job.matched_skills.map((skill) => (
                <li key={skill}>
                  <Badge variant="secondary">{skill}</Badge>
                </li>
              ))}
            </ul>
          </div>
        )}

        <div>
          <div className="text-muted-foreground text-xs font-medium tracking-wide uppercase">Links</div>
          {!job.url && !gmail && !search ? (
            <p className="text-muted-foreground mt-1.5 text-sm">No links were captured for this job.</p>
          ) : (
            <ul className="mt-1.5 space-y-1.5 text-sm">
              {job.url && (
                <li>
                  <ExternalLink href={job.url}>
                    <ExternalLinkIcon className="size-3.5" />
                    Job posting
                  </ExternalLink>
                </li>
              )}
              {gmail && (
                <li>
                  <ExternalLink href={gmail}>
                    <MailIcon className="size-3.5" />
                    Digest email
                  </ExternalLink>
                </li>
              )}
              {search && (
                <li>
                  <ExternalLink href={search}>
                    <SearchIcon className="size-3.5" />
                    Search Insight Global
                  </ExternalLink>
                </li>
              )}
            </ul>
          )}
        </div>

        <Separator />

        <div className="space-y-2">
          <Label htmlFor={`notes-${job.id}`}>Notes</Label>
          <Textarea
            id={`notes-${job.id}`}
            aria-label={`Notes for job ${job.id}`}
            value={notes}
            onChange={(event) => setNotes(event.target.value)}
            rows={4}
            placeholder="Recruiter name, where you applied, follow-up dates…"
          />
          <div className="flex items-center gap-3">
            <Button size="sm" onClick={save} disabled={!dirty || saving || busy}>
              {saving ? "Saving…" : "Save notes"}
            </Button>
            {dirty && !saving && <span className="text-muted-foreground text-xs">Unsaved changes</span>}
          </div>
        </div>
      </div>
    </SheetContent>
  );
}
