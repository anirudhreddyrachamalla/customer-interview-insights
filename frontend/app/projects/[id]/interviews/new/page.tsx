"use client";

/**
 * New interview — route `/projects/{id}/interviews/new`.
 *
 * Client component. In Next 16's App Router the `params` prop is a
 * Promise that has to be unwrapped with React's `use()` hook from a
 * client component (the same pattern as `/projects/{id}/page.tsx`).
 *
 * The page itself is a thin shell: a breadcrumb, a header, and the
 * shared `UploadForm`. All of the form logic, validation, submission,
 * and post-upload navigation lives in `components/interviews/UploadForm.tsx`
 * so the form can be tested in isolation.
 */

import Link from "next/link";
import { use } from "react";

import { UploadForm } from "@/components/interviews/UploadForm";

interface NewInterviewPageProps {
  params: Promise<{ id: string }>;
}

export default function NewInterviewPage({ params }: NewInterviewPageProps) {
  const { id } = use(params);

  return (
    <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-6 px-8 py-12">
      <nav aria-label="Breadcrumb" className="text-xs text-muted-foreground">
        <Link href="/" className="hover:text-foreground">
          Projects
        </Link>{" "}
        /{" "}
        <Link href={`/projects/${id}`} className="hover:text-foreground">
          Project
        </Link>{" "}
        / <span className="text-foreground">New interview</span>
      </nav>

      <header className="flex flex-col gap-1">
        <h1 className="text-3xl font-semibold tracking-tight">New interview</h1>
        <p className="text-sm text-muted-foreground">
          Upload an audio recording and capture the interviewee&apos;s
          demographics. We&apos;ll transcribe it and extract pain points
          automatically.
        </p>
      </header>

      <UploadForm projectId={id} />
    </main>
  );
}
