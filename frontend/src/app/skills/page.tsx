import type { Metadata } from "next";
import { connection } from "next/server";
import { Suspense } from "react";
import { PageLoading, StoreProblem } from "@/components/PageStates";
import { SkillsEditor } from "@/components/SkillsEditor";
import { loadSkillSettings } from "@/lib/load-jobs";

export const metadata: Metadata = { title: "Skills" };

/** Edit the skills the search looks for in each posting. */
export default function SkillsPage() {
  return (
    <Suspense fallback={<PageLoading label="Loading skills" />}>
      <Skills />
    </Suspense>
  );
}

/** Server component: reads the saved skill list at request time. */
async function Skills() {
  // Never prerender this at build time; the list changes whenever you save it.
  await connection();
  const result = await loadSkillSettings();
  if (!result.ok) return <StoreProblem message={result.message} />;
  return <SkillsEditor initialSettings={result.settings} store={result.store} />;
}
