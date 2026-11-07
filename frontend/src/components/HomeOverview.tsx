"use client";

import {
  ArrowRightIcon,
  BriefcaseBusinessIcon,
  HandshakeIcon,
  InboxIcon,
  MailWarningIcon,
  MessagesSquareIcon,
  SendIcon,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { formatDate, trackLabel } from "@/lib/jobs";
import { countJobs, jobsHref, latestMatches, recentActivity } from "@/lib/overview";
import type { Job, JobStatus, StoreInfo } from "@/lib/types";
import { ExternalLink } from "./ExternalLink";
import { RunSearchPanel } from "./RunSearchPanel";
import { StatusBadge } from "./StatusBadge";

interface Props {
  jobs: Job[];
  store: StoreInfo;
}

const STORE_LABEL = { local: "local file", firestore: "Firestore" } as const;

/** The home screen: run a search, see where things stand, and jump into the tracker. */
export function HomeOverview({ jobs, store }: Props) {
  const router = useRouter();
  const counts = countJobs(jobs);

  return (
    <div className="space-y-6">
      <div className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight">Your job search</h1>
        <p className="text-muted-foreground text-sm">
          {counts.total === 0 ? "Nothing tracked yet" : `${counts.total} job${counts.total === 1 ? "" : "s"} tracked`}
          {" · "}
          <span title={store.description}>
            reading the {store.emulator ? "Firestore emulator" : STORE_LABEL[store.backend]}
          </span>
        </p>
      </div>

      {/* Re-render this page from the server when a search finishes, so the counts include its matches. */}
      <RunSearchPanel onFinished={() => router.refresh()} />

      {counts.total === 0 ? (
        <GettingStarted />
      ) : (
        <>
          {counts.unemailed > 0 && (
            <Alert>
              <MailWarningIcon />
              <AlertTitle>
                {counts.unemailed} match{counts.unemailed === 1 ? " hasn't" : "es haven't"} been emailed
              </AlertTitle>
              <AlertDescription>
                <p>
                  They were saved, but the digest didn&apos;t go out, usually because Gmail isn&apos;t set up. They&apos;ll
                  be included in the next digest that sends.{" "}
                  <Link href={jobsHref("unemailed")} className="text-foreground font-medium underline underline-offset-4">
                    See them
                  </Link>
                </p>
              </AlertDescription>
            </Alert>
          )}

          <section aria-label="Totals" className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <StatCard status="emailed" label="To review" count={counts.toReview} hint="Emailed, not acted on yet" icon={InboxIcon} />
            <StatCard status="applied" label="Applied" count={counts.applied} hint="Waiting to hear back" icon={SendIcon} />
            <StatCard
              status="interviewing"
              label="Interviewing"
              count={counts.interviewing}
              hint="In the interview process"
              icon={MessagesSquareIcon}
            />
            <StatCard status="offer" label="Offers" count={counts.offers} hint="Offers received" icon={HandshakeIcon} />
          </section>

          {/* grid-cols-1 (not the implicit auto column) lets long titles truncate instead of widening the page. */}
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <JobListCard
              title="Latest matches"
              description="The newest jobs the search found."
              jobs={latestMatches(jobs)}
              dateOf={(job) => job.first_seen_at}
              datePrefix="Found"
              empty="No matches yet."
            />
            <JobListCard
              title="Recent activity"
              description="Your latest status changes."
              jobs={recentActivity(jobs)}
              dateOf={(job) => job.status_updated_at}
              datePrefix="Updated"
              empty="Nothing yet. Mark jobs applied, skipped, or interviewing in the tracker and they'll show up here."
            />
          </div>
        </>
      )}
    </div>
  );
}

function StatCard({
  status,
  label,
  count,
  hint,
  icon: Icon,
}: {
  status: JobStatus;
  label: string;
  count: number;
  hint: string;
  icon: LucideIcon;
}) {
  return (
    <Link
      href={jobsHref(status)}
      aria-label={`${label}: ${count}. Show these jobs`}
      className="group focus-visible:ring-ring rounded-xl focus-visible:ring-2 focus-visible:outline-none"
    >
      <Card className="group-hover:border-foreground/30 h-full gap-2 py-4 transition-colors">
        <CardHeader className="px-4">
          <CardDescription className="flex items-center gap-1.5">
            <Icon className="size-4" />
            {label}
          </CardDescription>
          <CardTitle className="text-3xl tabular-nums">{count}</CardTitle>
        </CardHeader>
        <CardContent className="text-muted-foreground px-4 text-xs">{hint}</CardContent>
      </Card>
    </Link>
  );
}

function JobListCard({
  title,
  description,
  jobs,
  dateOf,
  datePrefix,
  empty,
}: {
  title: string;
  description: string;
  jobs: Job[];
  dateOf: (job: Job) => string | null;
  datePrefix: string;
  empty: string;
}) {
  return (
    <Card className="gap-4">
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <CardDescription>{description}</CardDescription>
        <CardAction>
          <Button asChild variant="ghost" size="sm">
            <Link href={jobsHref()}>
              All jobs <ArrowRightIcon />
            </Link>
          </Button>
        </CardAction>
      </CardHeader>
      <CardContent>
        {jobs.length === 0 ? (
          <p className="text-muted-foreground text-sm">{empty}</p>
        ) : (
          <ul className="divide-y" aria-label={title}>
            {jobs.map((job) => (
              <li key={job.id} className="flex items-start justify-between gap-3 py-2.5 first:pt-0 last:pb-0">
                <div className="min-w-0 space-y-0.5">
                  {job.url ? (
                    <ExternalLink href={job.url} className="font-medium">
                      {job.title || job.id}
                    </ExternalLink>
                  ) : (
                    <span className="font-medium">{job.title || job.id}</span>
                  )}
                  <p className="text-muted-foreground truncate text-xs">
                    {[job.company, trackLabel(job.track), `${datePrefix} ${formatDate(dateOf(job))}`]
                      .filter(Boolean)
                      .join(" · ")}
                  </p>
                </div>
                <StatusBadge status={job.status} className="shrink-0" />
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

function GettingStarted() {
  const steps = [
    { title: "Run a search", text: "Use Run search above, or wait for the daily cron job." },
    { title: "Get the digest", text: "New matches are saved here and emailed to you." },
    { title: "Track them", text: "Mark jobs applied, skipped, or interviewing in Jobs, and keep notes." },
  ];
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <BriefcaseBusinessIcon className="size-5" />
          Welcome to Job Finder
        </CardTitle>
        <CardDescription>No jobs are tracked yet. Here&apos;s how it works:</CardDescription>
      </CardHeader>
      <CardContent>
        <ol className="grid gap-4 sm:grid-cols-3">
          {steps.map((step, index) => (
            <li key={step.title} className="flex gap-3">
              <span className="bg-secondary text-secondary-foreground flex size-7 shrink-0 items-center justify-center rounded-full text-sm font-semibold">
                {index + 1}
              </span>
              <div>
                <p className="font-medium">{step.title}</p>
                <p className="text-muted-foreground text-sm">{step.text}</p>
              </div>
            </li>
          ))}
        </ol>
      </CardContent>
    </Card>
  );
}
