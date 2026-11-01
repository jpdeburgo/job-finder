"use client";

import { ThemeProvider as NextThemesProvider } from "next-themes";

/** Light/dark/system theming via a `class` on <html>, as shadcn/ui expects. */
export function ThemeProvider({ children }: { children: React.ReactNode }) {
  return (
    <NextThemesProvider attribute="class" defaultTheme="system" enableSystem disableTransitionOnChange>
      {children}
    </NextThemesProvider>
  );
}
