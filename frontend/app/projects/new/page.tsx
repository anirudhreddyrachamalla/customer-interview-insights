"use client";

/**
 * Create a new project — route `/projects/new`.
 *
 * Pure client component (React Hook Form + Zod + TanStack Query
 * mutation). The Zod schema mirrors the backend's `ProjectCreate`
 * Pydantic schema (name 1..200, optional description ≤2000).
 *
 * Server-side validation errors arrive as RFC 7807 with an `errors`
 * map keyed by field name. We surface each into the matching form
 * field via `setError` so the user sees inline messages instead of a
 * generic toast.
 *
 * On success we navigate to the new project's detail page; the mutation
 * hook seeds the per-project cache so that page renders immediately.
 */

import { zodResolver } from "@hookform/resolvers/zod";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { ApiError } from "@/lib/api/client";
import { useCreateProject } from "@/lib/api/hooks";
import type { ProjectCreate } from "@/lib/api/types";

const projectFormSchema = z.object({
  name: z
    .string()
    .min(1, "Name is required")
    .max(200, "Name must be at most 200 characters"),
  description: z
    .string()
    .max(2000, "Description must be at most 2000 characters")
    .optional()
    .or(z.literal("")),
});

type ProjectFormValues = z.infer<typeof projectFormSchema>;

/** Fields we know how to surface inline. Anything else falls back to a
 *  toast so the user isn't blocked by an unknown contract drift. */
const KNOWN_FIELDS = new Set<keyof ProjectFormValues>(["name", "description"]);

export default function NewProjectPage() {
  const router = useRouter();
  const createProject = useCreateProject();
  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<ProjectFormValues>({
    resolver: zodResolver(projectFormSchema),
    defaultValues: { name: "", description: "" },
  });

  const submitting = isSubmitting || createProject.isPending;

  const onSubmit = handleSubmit((values) => {
    const payload: ProjectCreate = {
      name: values.name.trim(),
      description: values.description?.trim() ? values.description.trim() : null,
    };

    createProject.mutate(payload, {
      onSuccess: (project) => {
        router.push(`/projects/${project.id}`);
      },
      onError: (err) => {
        if (err instanceof ApiError && err.status === 422 && err.problem.errors) {
          let assignedAnyField = false;
          const errs = err.problem.errors;
          if (Array.isArray(errs)) {
            // FastAPI 422 array shape: { loc: ["body", "name"], msg, type }.
            for (const item of errs) {
              const field = item.loc?.[item.loc.length - 1];
              if (
                typeof field === "string" &&
                (KNOWN_FIELDS as Set<string>).has(field)
              ) {
                setError(field as keyof ProjectFormValues, {
                  type: "server",
                  message: item.msg,
                });
                assignedAnyField = true;
              }
            }
          } else {
            for (const [field, messages] of Object.entries(errs)) {
              if ((KNOWN_FIELDS as Set<string>).has(field)) {
                setError(field as keyof ProjectFormValues, {
                  type: "server",
                  message: messages.join(", "),
                });
                assignedAnyField = true;
              }
            }
          }
          if (!assignedAnyField) {
            toast.error(err.problem.detail ?? "Validation failed");
          }
          return;
        }
        const msg =
          err instanceof ApiError
            ? err.problem.detail ?? err.problem.title ?? err.message
            : err instanceof Error
              ? err.message
              : "Failed to create project";
        toast.error(msg);
      },
    });
  });

  return (
    <main className="mx-auto flex w-full max-w-2xl flex-1 flex-col gap-6 px-8 py-12">
      <header className="flex flex-col gap-1">
        <h1 className="text-3xl font-semibold tracking-tight">New project</h1>
        <p className="text-sm text-muted-foreground">
          Projects group related interviews. You can rename them later.
        </p>
      </header>

      <Card>
        <CardHeader>
          <CardTitle>Project details</CardTitle>
          <CardDescription>
            A short, descriptive name helps you find this project again.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form
            noValidate
            onSubmit={onSubmit}
            className="flex flex-col gap-5"
            aria-busy={submitting}
          >
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="project-name">Name</Label>
              <Input
                id="project-name"
                type="text"
                autoComplete="off"
                aria-invalid={errors.name ? true : undefined}
                aria-describedby={errors.name ? "project-name-error" : undefined}
                disabled={submitting}
                placeholder="e.g. Onboarding research Q2"
                {...register("name")}
              />
              {errors.name ? (
                <p
                  id="project-name-error"
                  role="alert"
                  className="text-xs text-destructive"
                >
                  {errors.name.message}
                </p>
              ) : null}
            </div>

            <div className="flex flex-col gap-1.5">
              <Label htmlFor="project-description">
                Description{" "}
                <span className="text-xs font-normal text-muted-foreground">
                  (optional)
                </span>
              </Label>
              <Textarea
                id="project-description"
                rows={4}
                aria-invalid={errors.description ? true : undefined}
                aria-describedby={
                  errors.description ? "project-description-error" : undefined
                }
                disabled={submitting}
                placeholder="Notes on the goals, scope, or audience for this batch of interviews."
                {...register("description")}
              />
              {errors.description ? (
                <p
                  id="project-description-error"
                  role="alert"
                  className="text-xs text-destructive"
                >
                  {errors.description.message}
                </p>
              ) : null}
            </div>

            <div className="mt-2 flex items-center justify-end gap-2">
              <Button
                type="button"
                variant="secondary"
                disabled={submitting}
                render={<Link href="/">Cancel</Link>}
              />
              <Button type="submit" disabled={submitting}>
                {submitting ? "Creating…" : "Create project"}
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>
    </main>
  );
}
