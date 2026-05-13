"use client";

/**
 * Project detail — route `/projects/{id}`.
 *
 * v1.1 layout:
 *   - 12-col grid on `lg+`; stacks on smaller screens.
 *   - Left (col-4): compact list of interview rows showing only name,
 *     gender, and StatusBadge. Each row is a `<Link>` to
 *     `/interviews/{id}`.
 *   - Right (col-8): the new `<ProjectInsightsPanel>` centerpane that
 *     fetches + renders the Claude cross-interview summary.
 *
 * Loading / error / 404 states for the project itself are unchanged
 * from v0; only the body has been reshuffled (see SPEC_v1.1 §3+4).
 */

import Link from "next/link";
import { use } from "react";

import { StatusBadge } from "@/components/interviews/StatusBadge";
import { ProjectInsightsPanel } from "@/components/projects/ProjectInsightsPanel";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError } from "@/lib/api/client";
import { useProject, useProjectInterviews } from "@/lib/api/hooks";
import type { Interview } from "@/lib/api/types";
import { GENDER_OPTIONS, labelFor } from "@/lib/options";
import { formatRelativeTime } from "@/lib/utils";

interface ProjectDetailPageProps {
  params: Promise<{ id: string }>;
}

export default function ProjectDetailPage({ params }: ProjectDetailPageProps) {
  const { id } = use(params);
  const { data, isLoading, isError, error, refetch, isFetching } =
    useProject(id);
  const {
    data: interviewsData,
    isLoading: interviewsLoading,
    isError: interviewsError,
  } = useProjectInterviews(id);

  if (isLoading) {
    return (
      <main className="mx-auto flex w-full max-w-7xl flex-1 flex-col gap-6 px-8 py-12">
        <Skeleton className="h-9 w-1/2" />
        <Skeleton className="h-4 w-3/4" />
        <Card>
          <CardHeader>
            <Skeleton className="h-5 w-32" />
          </CardHeader>
          <CardContent>
            <Skeleton className="h-16 w-full" />
          </CardContent>
        </Card>
      </main>
    );
  }

  if (isError) {
    const status = error instanceof ApiError ? error.status : undefined;
    if (status === 404) {
      return (
        <main className="mx-auto flex w-full max-w-md flex-1 flex-col items-center gap-6 px-8 py-24 text-center">
          <h1 className="text-2xl font-semibold tracking-tight">
            Project not found
          </h1>
          <p className="text-sm text-muted-foreground">
            The project you&apos;re looking for doesn&apos;t exist or has been
            deleted.
          </p>
          <Button render={<Link href="/">Back to projects</Link>} />
        </main>
      );
    }

    const detail =
      error instanceof ApiError
        ? error.problem.detail ?? error.problem.title ?? error.message
        : error instanceof Error
          ? error.message
          : "Something went wrong loading this project.";
    return (
      <main className="mx-auto flex w-full max-w-md flex-1 flex-col gap-6 px-8 py-24">
        <Card role="alert" className="items-center text-center">
          <CardHeader className="items-center">
            <CardTitle>Couldn&apos;t load project</CardTitle>
            <CardDescription>{detail}</CardDescription>
          </CardHeader>
          <CardContent className="flex justify-center pb-4">
            <Button
              onClick={() => {
                void refetch();
              }}
              disabled={isFetching}
            >
              {isFetching ? "Retrying…" : "Retry"}
            </Button>
          </CardContent>
        </Card>
      </main>
    );
  }

  if (!data) {
    // Defensive: react-query shouldn't reach `success` with no data,
    // but keep the user out of an undefined-state crash.
    return null;
  }

  const created = formatRelativeTime(data.created_at);

  return (
    <main className="mx-auto flex w-full max-w-7xl flex-1 flex-col gap-6 px-8 py-12">
      <nav aria-label="Breadcrumb" className="text-xs text-muted-foreground">
        <Link href="/" className="hover:text-foreground">
          Projects
        </Link>{" "}
        / <span className="text-foreground">{data.name}</span>
      </nav>

      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="flex flex-col gap-1">
              <CardTitle className="text-2xl">{data.name}</CardTitle>
              {data.description ? (
                <CardDescription className="whitespace-pre-line">
                  {data.description}
                </CardDescription>
              ) : (
                <CardDescription className="italic">
                  No description
                </CardDescription>
              )}
            </div>
            <Button
              render={
                <Link href={`/projects/${data.id}/interviews/new`}>
                  New Interview
                </Link>
              }
            />
          </div>
        </CardHeader>
        {created ? (
          <CardContent className="text-xs text-muted-foreground">
            Created {created}
          </CardContent>
        ) : null}
      </Card>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
        {/* Left: compact interview list */}
        <section
          aria-label="Interviews"
          className="flex flex-col gap-3 lg:col-span-4"
        >
          <header className="flex items-center justify-between gap-4">
            <h2 className="text-base font-semibold tracking-tight">
              Interviews
            </h2>
          </header>
          <InterviewsList
            projectId={data.id}
            interviews={interviewsData?.items ?? null}
            isLoading={interviewsLoading}
            isError={interviewsError}
          />
        </section>

        {/* Right: insights centerpane */}
        <section
          aria-label="Project insights"
          className="lg:col-span-8"
        >
          <ProjectInsightsPanel projectId={data.id} />
        </section>
      </div>
    </main>
  );
}

interface InterviewsListProps {
  projectId: string;
  interviews: Interview[] | null;
  isLoading: boolean;
  isError: boolean;
}

function InterviewsList({
  projectId,
  interviews,
  isLoading,
  isError,
}: InterviewsListProps) {
  if (isLoading) {
    return (
      <Card>
        <CardContent className="flex flex-col gap-3 py-4">
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
        </CardContent>
      </Card>
    );
  }

  if (isError) {
    return (
      <Card role="alert" className="items-center text-center">
        <CardHeader className="items-center">
          <CardTitle>Couldn&apos;t load interviews</CardTitle>
          <CardDescription>Refresh the page to try again.</CardDescription>
        </CardHeader>
      </Card>
    );
  }

  if (!interviews || interviews.length === 0) {
    return (
      <Card className="items-center text-center">
        <CardHeader className="items-center">
          <CardTitle>No interviews yet</CardTitle>
          <CardDescription>
            Upload an audio recording or a transcript to add the first
            interview.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex justify-center pb-4">
          <Button
            render={
              <Link href={`/projects/${projectId}/interviews/new`}>
                New Interview
              </Link>
            }
          />
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <ul
        className="flex flex-col divide-y divide-border"
        data-testid="interview-list"
      >
        {interviews.map((interview) => (
          <li key={interview.id}>
            <CompactInterviewRow interview={interview} />
          </li>
        ))}
      </ul>
    </Card>
  );
}

interface CompactInterviewRowProps {
  interview: Interview;
}

function CompactInterviewRow({ interview }: CompactInterviewRowProps) {
  const d = interview.demographics;
  const genderLabel = labelFor(GENDER_OPTIONS, d.gender);
  return (
    <Link
      href={`/interviews/${interview.id}`}
      className="flex items-center justify-between gap-3 px-4 py-3 outline-none transition-colors hover:bg-muted/40 focus-visible:bg-muted/60"
      data-testid={`interview-row-${interview.id}`}
    >
      <div className="flex min-w-0 flex-col gap-0.5">
        <span className="truncate text-sm font-medium text-foreground">
          {d.name}
        </span>
        <span className="text-xs text-muted-foreground">{genderLabel}</span>
      </div>
      <StatusBadge status={interview.status} />
    </Link>
  );
}
