"use client";

import { CircleAlertIcon, CircleCheckIcon, Loader2Icon, PlayIcon, TerminalIcon } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { fetchLatestRun, fetchRun, runFromError, startRun } from "@/lib/client";
import { describeSites, describeSummary, formatRunTime } from "@/lib/runs";
import type { SearchRun } from "@/lib/types";

interface Props {
  /** Called when a run this panel was following finishes, e.g. to reload the jobs. */
  onFinished?: (run: SearchRun) => void;
  /** How often to check on a running search. */
  pollIntervalMs?: number;
}

const errorMessage = (error: unknown) => (error instanceof Error ? error.message : String(error));

/**
 * "Run search" button plus the state of the newest run: starts
 * backend/job_search.py through the search API (backend/api.py), follows it
 * until it finishes, and shows what it printed.
 */
export function RunSearchPanel({ onFinished, pollIntervalMs = 2000 }: Props) {
  const [run, setRun] = useState<SearchRun | null>(null);
  const [starting, setStarting] = useState(false);
  // Why the API couldn't be reached when the page loaded (a hint, not an error).
  const [unavailable, setUnavailable] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lostTrack, setLostTrack] = useState(false);
  const [showOutput, setShowOutput] = useState(false);
  const outputRef = useRef<HTMLPreElement>(null);
  const onFinishedRef = useRef(onFinished);

  useEffect(() => {
    onFinishedRef.current = onFinished;
  }, [onFinished]);

  // Pick up the newest run on load, including one started in another tab.
  useEffect(() => {
    let cancelled = false;
    fetchLatestRun()
      .then((latest) => !cancelled && setRun(latest))
      .catch((caught) => !cancelled && setUnavailable(errorMessage(caught)));
    return () => {
      cancelled = true;
    };
  }, []);

  const running = run?.status === "running" && !lostTrack;

  // While a run is going, check on it every pollIntervalMs.
  useEffect(() => {
    if (!run || !running) return;
    let cancelled = false;
    const timer = setTimeout(async () => {
      try {
        const next = await fetchRun(run.id);
        if (cancelled) return;
        setRun(next);
        if (next.status !== "running") onFinishedRef.current?.(next);
      } catch (caught) {
        if (cancelled) return;
        setLostTrack(true);
        setError(`Lost track of the search: ${errorMessage(caught)}`);
      }
    }, pollIntervalMs);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [run, running, pollIntervalMs]);

  // Keep the newest output line in view.
  const lineCount = run?.output?.length ?? 0;
  useEffect(() => {
    const pre = outputRef.current;
    if (pre) pre.scrollTop = pre.scrollHeight;
  }, [lineCount, showOutput]);

  const start = async () => {
    setStarting(true);
    setError(null);
    setUnavailable(null);
    try {
      setRun(await startRun());
      setLostTrack(false);
    } catch (caught) {
      // 409: a search is already going (another tab, or a double click); follow that one.
      const current = runFromError(caught);
      if (current) {
        setRun(current);
        setLostTrack(false);
      } else {
        setError(`Could not start the search: ${errorMessage(caught)}`);
      }
    } finally {
      setStarting(false);
    }
  };

  const output = run?.output ?? [];

  return (
    <section aria-label="Job search" className="bg-card space-y-3 rounded-lg border px-4 py-3 text-sm">
      <div className="flex flex-wrap items-center gap-3">
        <div className="min-w-0 flex-1 basis-64 break-words" aria-live="polite">
          <RunState run={run} running={running} />
          {!run && unavailable && (
            <p className="text-muted-foreground mt-1 text-xs" data-testid="run-unavailable">
              {unavailable}
            </p>
          )}
          {error && (
            <p role="alert" className="text-destructive mt-1 text-xs">
              {error}
            </p>
          )}
        </div>
        {output.length > 0 && (
          <Button variant="ghost" size="sm" onClick={() => setShowOutput((shown) => !shown)} aria-expanded={showOutput}>
            <TerminalIcon />
            {showOutput ? "Hide output" : "Show output"}
          </Button>
        )}
        <Button onClick={start} disabled={starting || running}>
          {starting || running ? <Loader2Icon className="animate-spin" /> : <PlayIcon />}
          {running ? "Searching…" : starting ? "Starting…" : "Run search"}
        </Button>
      </div>

      {showOutput && output.length > 0 && (
        <pre
          ref={outputRef}
          aria-label="Search output"
          className="bg-muted max-h-72 overflow-auto rounded-md p-3 font-mono text-xs leading-relaxed whitespace-pre-wrap"
        >
          {run?.output_truncated ? `… ${run.output_truncated} earlier line(s) not shown\n` : ""}
          {output.join("\n")}
        </pre>
      )}
    </section>
  );
}

function RunState({ run, running }: { run: SearchRun | null; running: boolean }) {
  if (!run) {
    return (
      <p className="text-muted-foreground">
        Run the job search now instead of waiting for the daily cron job. New matches show up as soon as it
        finishes.
      </p>
    );
  }
  const started = formatRunTime(run.started_at);
  if (running) {
    return (
      <p className="flex items-center gap-2">
        <Loader2Icon className="size-4 shrink-0 animate-spin" />
        <span>
          Searching {describeSites(run)} (started {started})… This can take several minutes.
        </span>
      </p>
    );
  }
  if (run.status === "running") {
    // We stopped hearing from the API mid-run (see the error below).
    return <p className="text-muted-foreground">A search started at {started} may still be running.</p>;
  }
  const finished = formatRunTime(run.finished_at);
  if (run.status === "failed") {
    return (
      <p className="text-destructive flex items-start gap-2">
        <CircleAlertIcon className="mt-0.5 size-4 shrink-0" />
        <span>
          Last search failed ({finished}): {run.error}
        </span>
      </p>
    );
  }
  return (
    <p className="flex items-start gap-2">
      <CircleCheckIcon className="mt-0.5 size-4 shrink-0 text-green-600 dark:text-green-500" />
      <span>
        Last search finished at {finished}. {run.summary ? describeSummary(run.summary) : ""}
      </span>
    </p>
  );
}
