"use client";

/**
 * Project detail — route `/projects/{id}`.
 *
 * Client component. In Next 15+ the `params` prop is a Promise that
 * must be unwrapped with React's `use()` hook in client components.
 *
 * Renders:
 *   1. loading  → skeleton header + skeleton interview rows
 *   2. 404      → "Project not found" with a back link
 *   3. error    → generic error card with retry
 *   4. data     → project header, then an "Interviews" section that
 *                  lists each interview as a demographics-only card.
 *                  Clicking a card routes the user to /interviews/{id}
 *                  where the full transcript + pain points live.
 */

import Link from "next/link";
import { use } from "react";

import { Badge } from "@/components/ui/badge";
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
import type { Demographics, Interview } from "@/lib/api/types";
import {
  GENDER_OPTIONS,
  INCOME_OPTIONS,
  INDUSTRY_OPTIONS,
  JOB_ROLE_OPTIONS,
  MARITAL_STATUS_OPTIONS,
  labelFor,
} from "@/lib/options";
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
      <main className="mx-auto flex w-full max-w-4xl flex-1 flex-col gap-6 px-8 py-12">
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
    <main className="mx-auto flex w-full max-w-4xl flex-1 flex-col gap-6 px-8 py-12">
      <nav aria-label="Breadcrumb" className="text-xs text-muted-foreground">
        <Link href="/" className="hover:text-foreground">
          Projects
        </Link>{" "}
        / <span className="text-foreground">{data.name}</span>
      </nav>

      <Card>
        <CardHeader>
          <CardTitle className="text-2xl">{data.name}</CardTitle>
          {data.description ? (
            <CardDescription className="whitespace-pre-line">
              {data.description}
            </CardDescription>
          ) : (
            <CardDescription className="italic">No description</CardDescription>
          )}
        </CardHeader>
        {created ? (
          <CardContent className="text-xs text-muted-foreground">
            Created {created}
          </CardContent>
        ) : null}
      </Card>

      <section className="flex flex-col gap-3">
        <header className="flex items-center justify-between gap-4">
          <h2 className="text-xl font-semibold tracking-tight">Interviews</h2>
          <Button
            render={
              <Link href={`/projects/${data.id}/interviews/new`}>
                New Interview
              </Link>
            }
          />
        </header>

        <InterviewsSection
          projectId={data.id}
          interviews={interviewsData?.items ?? null}
          isLoading={interviewsLoading}
          isError={interviewsError}
        />
      </section>
    </main>
  );
}

interface InterviewsSectionProps {
  projectId: string;
  interviews: Interview[] | null;
  isLoading: boolean;
  isError: boolean;
}

function InterviewsSection({
  projectId,
  interviews,
  isLoading,
  isError,
}: InterviewsSectionProps) {
  if (isLoading) {
    return (
      <div className="flex flex-col gap-3">
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-24 w-full" />
      </div>
    );
  }

  if (isError) {
    return (
      <Card role="alert" className="items-center text-center">
        <CardHeader className="items-center">
          <CardTitle>Couldn&apos;t load interviews</CardTitle>
          <CardDescription>
            Refresh the page to try again.
          </CardDescription>
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
            Upload an audio recording to add the first interview to this
            project.
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
    <ul className="flex flex-col gap-3">
      {interviews.map((interview) => (
        <li key={interview.id}>
          <InterviewDemographicsCard interview={interview} />
        </li>
      ))}
    </ul>
  );
}

interface InterviewDemographicsCardProps {
  interview: Interview;
}

function InterviewDemographicsCard({
  interview,
}: InterviewDemographicsCardProps) {
  const d: Demographics = interview.demographics;
  const chips: { key: string; label: string }[] = [
    { key: "age", label: `${d.age} yrs` },
    { key: "gender", label: labelFor(GENDER_OPTIONS, d.gender) },
    { key: "country", label: d.country },
    {
      key: "marital_status",
      label: labelFor(MARITAL_STATUS_OPTIONS, d.marital_status),
    },
    { key: "job_role", label: labelFor(JOB_ROLE_OPTIONS, d.job_role) },
    { key: "industry", label: labelFor(INDUSTRY_OPTIONS, d.industry) },
    { key: "income", label: labelFor(INCOME_OPTIONS, d.income) },
  ];

  return (
    <Link
      href={`/interviews/${interview.id}`}
      className="block rounded-xl outline-none transition-colors focus-visible:ring-3 focus-visible:ring-ring/50"
    >
      <Card className="hover:bg-muted/40">
        <CardHeader>
          <CardTitle className="text-base">{d.name}</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-1.5 pb-4">
          {chips.map((chip) => (
            <Badge key={chip.key} variant="secondary">
              {chip.label}
            </Badge>
          ))}
        </CardContent>
      </Card>
    </Link>
  );
}
