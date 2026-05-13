/**
 * TanStack Query hooks for the interview-insights API.
 *
 * Centralising the hooks here means each page imports a typed
 * `useFoo()` instead of re-deriving query keys / refetch intervals.
 *
 * Conventions:
 *
 * - Query keys: `["projects"]`, `["projects", id]`, `["interviews", id]`.
 * - `useInterview(id)` should set `refetchInterval: 3000` while the
 *   status is `uploaded | transcribing | analyzing`, then drop polling
 *   once `completed` or `failed`. (Added in task #7.)
 * - Mutations invalidate the matching list/detail query on success.
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import { api } from "./client";
import type {
  Interview,
  InterviewId,
  InterviewStatus,
  ListResponse,
  Project,
  ProjectCreate,
  ProjectId,
  ProjectInsight,
} from "./types";

/** Query key factory. Keep narrow + serialisable so cache invalidation
 *  is a one-liner from anywhere. */
export const queryKeys = {
  projects: () => ["projects"] as const,
  project: (id: ProjectId) => ["projects", id] as const,
  projectInterviews: (id: ProjectId) =>
    ["projects", id, "interviews"] as const,
  projectInsights: (id: ProjectId) =>
    ["projects", id, "insights"] as const,
  interview: (id: InterviewId) => ["interviews", id] as const,
};

/** Statuses where the pipeline is still running. While the interview is
 *  in one of these, the detail page polls `GET /interviews/{id}` every
 *  3 seconds; once it reaches `completed` or `failed`, polling stops. */
export const POLLABLE_STATUSES: ReadonlySet<InterviewStatus> = new Set([
  "uploaded",
  "transcribing",
  "analyzing",
]);

/** List all projects. */
export function useProjects() {
  return useQuery({
    queryKey: queryKeys.projects(),
    queryFn: () => api.get<ListResponse<Project>>("/projects"),
  });
}

/** Fetch a single project by id. */
export function useProject(id: ProjectId) {
  return useQuery({
    queryKey: queryKeys.project(id),
    queryFn: () => api.get<Project>(`/projects/${id}`),
    enabled: Boolean(id),
  });
}

/** Create a new project. Invalidates the projects list cache on success
 *  so the projects page reflects the new entry on return. */
export function useCreateProject() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: ProjectCreate) => api.post<Project>("/projects", body),
    onSuccess: (created) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.projects() });
      // Seed the per-project cache so the detail page doesn't need to
      // re-fetch immediately after a router.push.
      queryClient.setQueryData(queryKeys.project(created.id), created);
    },
  });
}

/** List interviews belonging to a project. */
export function useProjectInterviews(projectId: ProjectId) {
  return useQuery({
    queryKey: queryKeys.projectInterviews(projectId),
    queryFn: () =>
      api.get<ListResponse<Interview>>(`/projects/${projectId}/interviews`),
    enabled: Boolean(projectId),
  });
}

/** Fetch a single interview, polling while the pipeline is still
 *  running. Polling stops automatically once the status transitions to
 *  `completed` or `failed`. */
export function useInterview(id: InterviewId) {
  return useQuery({
    queryKey: queryKeys.interview(id),
    queryFn: () => api.get<Interview>(`/interviews/${id}`),
    enabled: Boolean(id),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      if (!status) return false;
      return POLLABLE_STATUSES.has(status) ? 3000 : false;
    },
  });
}

/** Retry a failed interview. On success, seeds the per-interview cache
 *  with the 202 response so polling can pick the pipeline back up
 *  immediately without an extra round-trip. */
export function useRetryInterview() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (interviewId: InterviewId) =>
      api.post<Interview>(`/interviews/${interviewId}/retry`),
    onSuccess: (data) => {
      queryClient.setQueryData(queryKeys.interview(data.id), data);
    },
  });
}

/** Fetch the project-level insight row. The backend returns a synthetic
 *  `status='idle'` payload when no row exists yet, so consumers don't
 *  have to handle a 404 for the "never generated" state.
 *
 *  Polls every 3s while `status === 'generating'` — same cadence as the
 *  interview-detail page so the two queries feel symmetric. */
export function useProjectInsights(projectId: ProjectId) {
  return useQuery({
    queryKey: queryKeys.projectInsights(projectId),
    queryFn: () =>
      api.get<ProjectInsight>(`/projects/${projectId}/insights`),
    enabled: Boolean(projectId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "generating" ? 3000 : false;
    },
  });
}

/** Kick off a (re)generation of the project insight summary. Returns the
 *  202 `generating` row, which we seed directly into the cache so the
 *  polling hook starts ticking without an extra refetch. */
export function useRefreshInsights(projectId: ProjectId) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () =>
      api.post<ProjectInsight>(`/projects/${projectId}/insights/refresh`),
    onSuccess: (data) => {
      queryClient.setQueryData(queryKeys.projectInsights(projectId), data);
    },
  });
}
