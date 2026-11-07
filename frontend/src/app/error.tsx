"use client";

import { AlertCircleIcon } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";

/** Last-resort error boundary for every page (home and jobs). */
export default function ErrorPage({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <Alert variant="destructive">
      <AlertCircleIcon />
      <AlertTitle>Something went wrong</AlertTitle>
      <AlertDescription>
        <p className="font-mono text-xs">{error.message}</p>
        <Button variant="outline" size="sm" onClick={reset} className="mt-2">
          Try again
        </Button>
      </AlertDescription>
    </Alert>
  );
}
