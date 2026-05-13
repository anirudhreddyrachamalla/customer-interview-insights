/**
 * Curated API types — the app-facing names (`Project`, `Interview`,
 * `PainPoint`, etc.) that components and hooks import.
 *
 * These were validated against the regenerated OpenAPI schema in
 * `./openapi-schema.ts` during the v1.1 gate-keeper pass. To regenerate
 * the raw schema run `npm run gen:api` (requires `localhost:8000`) or
 * use `backend/dump_openapi.py` + `npx openapi-typescript`.
 *
 * If a backend schema field changes, update the matching interface
 * below to match the corresponding `components["schemas"][...]` entry
 * in `./openapi-schema.ts`. The two files are intentionally kept
 * in sync — the curated names give component code a stable surface,
 * and the generated schema gives a machine-checkable contract.
 */

export type ProjectId = string;
export type InterviewId = string;
export type PainPointId = string;

export type InterviewStatus =
  | "uploaded"
  | "transcribing"
  | "analyzing"
  | "completed"
  | "failed";

export type InterviewType = "problem_validation";

/** Pain-point classification — added in v1.1. Claude tags each extracted
 *  pain point with one of these three values. See SPEC_v1.1 §1. */
export type PainPointType = "pain_point" | "workaround" | "suggestion";

/** What the interview was created from — audio file vs. transcript file.
 *  Added in v1.1 (see SPEC_v1.1 §2). Server-set at upload time. */
export type InterviewSourceKind = "audio" | "transcript";

/** Project-level Claude summary status. Added in v1.1 (see SPEC_v1.1 §3). */
export type InsightStatus = "idle" | "generating" | "failed";

export type Gender = "male" | "female" | "non_binary" | "prefer_not_to_say";

export type IncomeBracket =
  | "under_25k"
  | "25k_50k"
  | "50k_100k"
  | "100k_200k"
  | "over_200k"
  | "prefer_not_to_say";

/** Alias for the income enum that matches the name the backend / spec
 *  uses (`Income`). `IncomeBracket` is kept for backwards compatibility
 *  with earlier task scaffolding. */
export type Income = IncomeBracket;

export type MaritalStatus =
  | "single"
  | "married"
  | "divorced"
  | "widowed"
  | "prefer_not_to_say";

export type JobRole =
  | "engineer"
  | "designer"
  | "product_manager"
  | "marketing"
  | "sales"
  | "operations"
  | "customer_support"
  | "founder_executive"
  | "student"
  | "other";

export type Industry =
  | "saas_software"
  | "ecommerce_retail"
  | "finance_fintech"
  | "healthcare"
  | "education"
  | "media_entertainment"
  | "manufacturing"
  | "government_nonprofit"
  | "hospitality_travel"
  | "other";

export interface Demographics {
  name: string;
  gender: Gender;
  age: number;
  income: IncomeBracket;
  marital_status: MaritalStatus;
  country: string;
  job_role: JobRole;
  industry: Industry;
}

export interface Project {
  id: ProjectId;
  name: string;
  description: string | null;
  created_at: string;
  updated_at: string;
}

/** Request body for `POST /projects`. Mirrors the backend's
 *  `ProjectCreate` Pydantic schema. */
export interface ProjectCreate {
  name: string;
  description?: string | null;
}

export interface TranscriptSegment {
  start: number;
  end: number;
  speaker: string;
  text: string;
}

export interface PainPoint {
  id: PainPointId;
  interview_id: InterviewId;
  text: string;
  supporting_quote: string;
  timestamp_start_sec: number;
  timestamp_end_sec: number;
  severity: 1 | 2 | 3 | 4 | 5;
  /** Classification of the pain point — added in v1.1. Existing rows
   *  backfilled to `pain_point`; new rows are Claude-set. */
  type: PainPointType;
  created_at: string;
}

export interface Interview {
  id: InterviewId;
  project_id: ProjectId;
  audio_filename: string;
  audio_duration_sec: number | null;
  /** v1.1 — `"audio"` for the existing flow, `"transcript"` when the
   *  interview was created from an uploaded transcript file. */
  source_kind: InterviewSourceKind;
  type: InterviewType;
  demographics: Demographics;
  transcript_text: string | null;
  transcript_segments: TranscriptSegment[] | null;
  meeting_notes: string | null;
  status: InterviewStatus;
  error_message: string | null;
  pain_points: PainPoint[];
  created_at: string;
  processed_at: string | null;
}

/** Response body for `GET /projects/{id}/insights` and `POST .../refresh`.
 *  Added in v1.1 (see SPEC_v1.1 §3). */
export interface ProjectInsight {
  project_id: ProjectId;
  status: InsightStatus;
  summary_markdown: string | null;
  /** Number of interviews that were included the last time a summary
   *  was generated. `0` before the first run. */
  interview_count_summarised: number;
  /** Current count of `completed` interviews on the project. */
  interview_count_completed: number;
  /** True when the set of completed interviews now differs from the
   *  set that was summarised (count or ids). */
  is_stale: boolean;
  error_message: string | null;
  model: string | null;
  generated_at: string | null;
  updated_at: string;
}

export interface ListResponse<T> {
  items: T[];
}
