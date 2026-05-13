/**
 * Generated API types.
 *
 * TODO: regenerate via `npm run gen:api` once the backend is running on
 * http://localhost:8000. Until then, the hand-written types below are
 * enough for the API client + hooks + pages to typecheck.
 *
 * Keep these in sync with `SPEC.md`'s data model + the backend's
 * Pydantic schemas. When the real types are generated they'll fully
 * replace this file — code that imports `Project`, `Interview`, etc.
 * should keep working as long as the backend's OpenAPI schema names
 * match.
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
  created_at: string;
}

export interface Interview {
  id: InterviewId;
  project_id: ProjectId;
  audio_filename: string;
  audio_duration_sec: number | null;
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

export interface ListResponse<T> {
  items: T[];
}
