/**
 * Select-option constants for the upload form.
 *
 * Each array is the canonical `{value, label}` list for one of the
 * backend's demographics enums (plus the interview type). The `value`
 * MUST match the backend's enum string byte-for-byte — the server
 * rejects anything else with a 422.
 *
 * Keep these in sync with:
 *   - `SPEC.md` → §"Data model" → Demographics
 *   - The backend's Pydantic schemas
 *
 * If the backend adds or removes an enum value, update this file and
 * the matching union type in `lib/api/types.ts`.
 */

import type {
  Gender,
  Income,
  Industry,
  InterviewType,
  JobRole,
  MaritalStatus,
} from "@/lib/api/types";

export interface SelectOption<TValue extends string> {
  value: TValue;
  label: string;
}

export const GENDER_OPTIONS: readonly SelectOption<Gender>[] = [
  { value: "male", label: "Male" },
  { value: "female", label: "Female" },
  { value: "non_binary", label: "Non-binary" },
  { value: "prefer_not_to_say", label: "Prefer not to say" },
] as const;

export const INCOME_OPTIONS: readonly SelectOption<Income>[] = [
  { value: "under_25k", label: "Under $25k" },
  { value: "25k_50k", label: "$25k – $50k" },
  { value: "50k_100k", label: "$50k – $100k" },
  { value: "100k_200k", label: "$100k – $200k" },
  { value: "over_200k", label: "Over $200k" },
  { value: "prefer_not_to_say", label: "Prefer not to say" },
] as const;

export const MARITAL_STATUS_OPTIONS: readonly SelectOption<MaritalStatus>[] = [
  { value: "single", label: "Single" },
  { value: "married", label: "Married" },
  { value: "divorced", label: "Divorced" },
  { value: "widowed", label: "Widowed" },
  { value: "prefer_not_to_say", label: "Prefer not to say" },
] as const;

export const JOB_ROLE_OPTIONS: readonly SelectOption<JobRole>[] = [
  { value: "engineer", label: "Engineer" },
  { value: "designer", label: "Designer" },
  { value: "product_manager", label: "Product manager" },
  { value: "marketing", label: "Marketing" },
  { value: "sales", label: "Sales" },
  { value: "operations", label: "Operations" },
  { value: "customer_support", label: "Customer support" },
  { value: "founder_executive", label: "Founder / executive" },
  { value: "student", label: "Student" },
  { value: "other", label: "Other" },
] as const;

export const INDUSTRY_OPTIONS: readonly SelectOption<Industry>[] = [
  { value: "saas_software", label: "SaaS / Software" },
  { value: "ecommerce_retail", label: "E-commerce / Retail" },
  { value: "finance_fintech", label: "Finance / Fintech" },
  { value: "healthcare", label: "Healthcare" },
  { value: "education", label: "Education" },
  { value: "media_entertainment", label: "Media / Entertainment" },
  { value: "manufacturing", label: "Manufacturing" },
  { value: "government_nonprofit", label: "Government / Nonprofit" },
  { value: "hospitality_travel", label: "Hospitality / Travel" },
  { value: "other", label: "Other" },
] as const;

export const INTERVIEW_TYPE_OPTIONS: readonly SelectOption<InterviewType>[] = [
  { value: "problem_validation", label: "Problem validation" },
] as const;

/** Convenience lookup so labels can be rendered from a stored value
 *  elsewhere in the UI without re-importing the array. */
export function labelFor<TValue extends string>(
  options: readonly SelectOption<TValue>[],
  value: TValue,
): string {
  return options.find((o) => o.value === value)?.label ?? value;
}
