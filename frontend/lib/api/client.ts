/**
 * Single fetch wrapper for the interview-insights backend.
 *
 * - Base URL comes from `NEXT_PUBLIC_API_URL`, falling back to the dev
 *   default of `http://localhost:8000/api/v1`.
 * - Errors are parsed as RFC 7807 problem details (`{type, title, status,
 *   detail, errors?}`) and re-thrown as `ApiError` so callers can render
 *   server-side validation messages inline.
 * - Generic typed methods: `get<T>`, `post<T>`, `postFormData<T>`.
 *
 * No state, no auth (v0 is unauthenticated). Used directly by the
 * TanStack Query hooks in `./hooks.ts`.
 */

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

/** RFC 7807 problem details, plus an optional per-field `errors`
 *  payload. The backend may surface field errors in either shape:
 *
 *  - `{ name: ["Name is required"] }` — a field→messages map (used by
 *    project create today).
 *  - `[ { loc: ["body", "demographics", "country"], msg: "...", type: "..." } ]`
 *    — the Pydantic/FastAPI 422 array shape (used by interview upload).
 *
 *  Callers should narrow on `Array.isArray(problem.errors)` to handle
 *  both. */
export interface ValidationErrorItem {
  loc?: (string | number)[];
  msg: string;
  type?: string;
}

export interface ProblemDetails {
  type?: string;
  title?: string;
  status?: number;
  detail?: string;
  errors?: Record<string, string[]> | ValidationErrorItem[];
}

export class ApiError extends Error {
  readonly status: number;
  readonly problem: ProblemDetails;

  constructor(status: number, problem: ProblemDetails) {
    super(problem.detail ?? problem.title ?? `Request failed (${status})`);
    this.name = "ApiError";
    this.status = status;
    this.problem = problem;
  }
}

function joinUrl(path: string): string {
  if (/^https?:\/\//.test(path)) return path;
  const base = API_BASE_URL.replace(/\/$/, "");
  const suffix = path.startsWith("/") ? path : `/${path}`;
  return `${base}${suffix}`;
}

async function parseError(res: Response): Promise<ApiError> {
  let problem: ProblemDetails = { status: res.status, title: res.statusText };
  try {
    const body = (await res.json()) as ProblemDetails;
    problem = { status: res.status, ...body };
  } catch {
    // body wasn't JSON; keep status/statusText as the problem.
  }
  return new ApiError(res.status, problem);
}

async function handle<T>(res: Response): Promise<T> {
  if (!res.ok) throw await parseError(res);
  if (res.status === 204) return undefined as T;
  // 202s in our API still return a JSON body; only branch on 204.
  return (await res.json()) as T;
}

export const api = {
  baseUrl: API_BASE_URL,

  async get<T>(path: string, init?: RequestInit): Promise<T> {
    const res = await fetch(joinUrl(path), {
      ...init,
      method: "GET",
      headers: { Accept: "application/json", ...(init?.headers ?? {}) },
    });
    return handle<T>(res);
  },

  async post<T>(
    path: string,
    body?: unknown,
    init?: RequestInit,
  ): Promise<T> {
    const res = await fetch(joinUrl(path), {
      ...init,
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
        ...(init?.headers ?? {}),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    return handle<T>(res);
  },

  async postFormData<T>(
    path: string,
    form: FormData,
    init?: RequestInit,
  ): Promise<T> {
    const res = await fetch(joinUrl(path), {
      ...init,
      method: "POST",
      // NOTE: do NOT set Content-Type — the browser sets the multipart
      // boundary automatically when given a FormData body.
      headers: { Accept: "application/json", ...(init?.headers ?? {}) },
      body: form,
    });
    return handle<T>(res);
  },
};
