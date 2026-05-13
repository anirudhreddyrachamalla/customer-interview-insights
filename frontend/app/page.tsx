"use client";

/**
 * Projects list — route `/`.
 *
 * Client component because TanStack Query needs the React tree. Fetches
 * `GET /projects` via `useProjects()` and renders one of four states:
 *
 *   1. loading  → skeleton grid (3 placeholder cards)
 *   2. error    → RFC 7807 `detail` + retry button
 *   3. empty    → centred "Create your first project" card
 *   4. data     → responsive grid of project cards
 *
 * Each card links to `/projects/{id}` via `next/link`. The footer line
 * shows a relative timestamp computed with `Intl.RelativeTimeFormat`.
 *
 * TODO(backend): when `ProjectRead` gains an `interview_count` field,
 * render it next to the "—" placeholder below. Tracked against task
 * #10 follow-up.
 */

import Link from "next/link";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useProjects } from "@/lib/api/hooks";
import { ApiError } from "@/lib/api/client";
import { formatRelativeTime } from "@/lib/utils";
import type { Project } from "@/lib/api/types";

export default function ProjectsPage() {
  const { data, isLoading, isError, error, refetch, isFetching } =
    useProjects();

  return (
    <main className="mx-auto flex w-full max-w-5xl flex-1 flex-col gap-6 px-8 py-12">
      <header className="flex items-center justify-between gap-4">
        <h1 className="text-3xl font-semibold tracking-tight">Projects</h1>
        <Button render={<Link href="/projects/new">New Project</Link>} />
      </header>

      {isLoading ? (
        <ProjectsSkeleton />
      ) : isError ? (
        <ProjectsError
          error={error}
          onRetry={() => {
            void refetch();
          }}
          retrying={isFetching}
        />
      ) : !data || data.items.length === 0 ? (
        <ProjectsEmpty />
      ) : (
        <ProjectsGrid items={data.items} />
      )}
    </main>
  );
}

function ProjectsSkeleton() {
  return (
    <div
      data-testid="projects-loading"
      className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3"
    >
      {Array.from({ length: 3 }).map((_, i) => (
        <Card key={i}>
          <CardHeader>
            <Skeleton className="h-5 w-3/4" />
            <Skeleton className="mt-2 h-4 w-full" />
          </CardHeader>
          <CardContent>
            <Skeleton className="h-4 w-1/2" />
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

function ProjectsError({
  error,
  onRetry,
  retrying,
}: {
  error: unknown;
  onRetry: () => void;
  retrying: boolean;
}) {
  const detail =
    error instanceof ApiError
      ? error.problem.detail ?? error.problem.title ?? error.message
      : error instanceof Error
        ? error.message
        : "Something went wrong fetching projects.";
  return (
    <Card
      role="alert"
      className="mx-auto w-full max-w-md items-center text-center"
    >
      <CardHeader className="items-center">
        <CardTitle>Couldn&apos;t load projects</CardTitle>
        <CardDescription>{detail}</CardDescription>
      </CardHeader>
      <CardContent className="flex justify-center pb-4">
        <Button onClick={onRetry} disabled={retrying}>
          {retrying ? "Retrying…" : "Retry"}
        </Button>
      </CardContent>
    </Card>
  );
}

function ProjectsEmpty() {
  return (
    <Card className="mx-auto w-full max-w-md items-center text-center">
      <CardHeader className="items-center">
        <CardTitle>Create your first project</CardTitle>
        <CardDescription>
          Projects group related interviews. Start by creating one.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex justify-center pb-4">
        <Button render={<Link href="/projects/new">New Project</Link>} />
      </CardContent>
    </Card>
  );
}

function ProjectsGrid({ items }: { items: Project[] }) {
  return (
    <ul className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {items.map((p) => (
        <li key={p.id}>
          <ProjectCard project={p} />
        </li>
      ))}
    </ul>
  );
}

function ProjectCard({ project }: { project: Project }) {
  const created = formatRelativeTime(project.created_at);
  return (
    <Link
      href={`/projects/${project.id}`}
      className="block rounded-xl outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring/50"
    >
      <Card className="h-full transition-shadow hover:shadow-md">
        <CardHeader>
          <CardTitle>{project.name}</CardTitle>
          {project.description ? (
            <CardDescription className="line-clamp-2">
              {project.description}
            </CardDescription>
          ) : (
            <CardDescription className="italic text-muted-foreground/70">
              No description
            </CardDescription>
          )}
        </CardHeader>
        <CardContent className="flex items-center justify-between text-xs text-muted-foreground">
          {/* TODO(backend): replace "—" with `project.interview_count`
              once ProjectRead exposes it. Until then we keep the slot
              so the layout is stable. */}
          <span>
            <span className="font-medium text-foreground">—</span> interviews
          </span>
        </CardContent>
        <CardFooter className="text-xs text-muted-foreground">
          {created ? `created ${created}` : "created recently"}
        </CardFooter>
      </Card>
    </Link>
  );
}
