import type { Metadata } from "next";
import { connection } from "next/server";
import { Suspense } from "react";
import { PageLoading, StoreProblem } from "@/components/PageStates";
import { ResumePanel } from "@/components/ResumePanel";
import { loadResumePage } from "@/lib/load-jobs";

export const metadata: Metadata = { title: "Resume" };

/** Upload your resume and see the skills and years of experience it shows. */
export default function ResumePage() {
  return (
    <Suspense fallback={<PageLoading label="Loading your resume" />}>
      <ResumeContent />
    </Suspense>
  );
}

/** Server component: reads the saved resume (and your skill list) at request time. */
async function ResumeContent() {
  await connection();
  const result = await loadResumePage();
  if (!result.ok) return <StoreProblem message={result.message} />;
  return <ResumePanel initialResume={result.resume} initialSkills={result.skills} store={result.store} />;
}
