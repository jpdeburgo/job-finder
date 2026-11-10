import type { Metadata } from "next";
import { BriefcaseBusinessIcon } from "lucide-react";
import Link from "next/link";
import { SiteNav } from "@/components/SiteNav";
import { ThemeProvider } from "@/components/ThemeProvider";
import { ThemeToggle } from "@/components/ThemeToggle";
import "./globals.css";

export const metadata: Metadata = {
  // Pages set their own title ("Jobs"); this fills in the rest.
  title: { default: "Job Finder", template: "%s · Job Finder" },
  description: "Run the job search and track the matches it finds.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    // next-themes sets the theme class on <html> before hydration.
    <html lang="en" className="h-full antialiased" suppressHydrationWarning>
      <body className="flex min-h-full flex-col">
        <ThemeProvider>
          <header className="bg-background/95 supports-[backdrop-filter]:bg-background/60 sticky top-0 z-40 border-b backdrop-blur">
            <div className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-4 py-3">
              <div className="flex items-center gap-2 sm:gap-4">
                <Link href="/" className="flex items-center gap-2 whitespace-nowrap">
                  <BriefcaseBusinessIcon className="size-5" />
                  {/* On phones the icon alone links home, so the nav still fits. */}
                  <span className="text-lg font-semibold tracking-tight max-[459px]:sr-only">Job Finder</span>
                </Link>
                <SiteNav />
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
