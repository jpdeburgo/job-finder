import type { Metadata } from "next";
import { BriefcaseBusinessIcon } from "lucide-react";
import { ThemeProvider } from "@/components/ThemeProvider";
import { ThemeToggle } from "@/components/ThemeToggle";
import "./globals.css";

export const metadata: Metadata = {
  title: "Job Tracker — Insight Global matches",
  description: "Track the Insight Global job matches found by the search script.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    // next-themes sets the theme class on <html> before hydration.
    <html lang="en" className="h-full antialiased" suppressHydrationWarning>
      <body className="flex min-h-full flex-col">
        <ThemeProvider>
          <header className="bg-background/95 supports-[backdrop-filter]:bg-background/60 sticky top-0 z-40 border-b backdrop-blur">
            <div className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-4 py-3">
              <div className="flex items-center gap-2">
                <BriefcaseBusinessIcon className="size-5" />
                <h1 className="text-lg font-semibold tracking-tight">Job Tracker</h1>
                <span className="text-muted-foreground hidden text-xs sm:inline">
                  · Insight Global matches, synced with the search script
                </span>
              </div>
              <ThemeToggle />
            </div>
          </header>
          <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-6">{children}</main>
        </ThemeProvider>
      </body>
    </html>
  );
}
