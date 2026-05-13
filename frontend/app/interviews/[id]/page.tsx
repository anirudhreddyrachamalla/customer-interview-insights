"use client";

/**
 * Route: `/interviews/{id}` — the interview detail page.
 *
 * In Next 15+ the `params` prop is a Promise that has to be unwrapped
 * with React's `use()` hook in client components. We do that here, then
 * hand the resolved id to `<InterviewDetail />` which owns all the
 * fetching, polling, and rendering.
 *
 * Keeping the page component this thin makes it trivial to test the
 * detail UI in isolation (the tester teammate can mount
 * `<InterviewDetail interviewId="…"/>` without simulating the Next
 * params Promise).
 */

import { use } from "react";

import { InterviewDetail } from "@/components/interviews/InterviewDetail";

interface InterviewDetailPageProps {
  params: Promise<{ id: string }>;
}

export default function InterviewDetailPage({
  params,
}: InterviewDetailPageProps) {
  const { id } = use(params);
  return <InterviewDetail interviewId={id} />;
}
