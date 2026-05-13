/**
 * Frontend test fixtures.
 *
 * These mirror the canned backend fixtures under
 * `backend/tests/fixtures/`. If you change them here, change them there
 * too (or vice versa) so backend ↔ frontend tests agree on shapes.
 *
 * Types are intentionally loose (`unknown`-free, no generated OpenAPI
 * types yet). Once the frontend teammate generates types into
 * `src/lib/api/types.ts` via `openapi-typescript`, we can tighten these.
 */

export interface SampleDemographics {
  name: string;
  gender:
    | 'male'
    | 'female'
    | 'non_binary'
    | 'prefer_not_to_say';
  age: number;
  income:
    | 'under_25k'
    | '25k_50k'
    | '50k_100k'
    | '100k_200k'
    | 'over_200k'
    | 'prefer_not_to_say';
  marital_status: 'single' | 'married' | 'divorced' | 'widowed' | 'prefer_not_to_say';
  country: string;
  job_role:
    | 'engineer'
    | 'designer'
    | 'product_manager'
    | 'marketing'
    | 'sales'
    | 'operations'
    | 'customer_support'
    | 'founder_executive'
    | 'student'
    | 'other';
  industry:
    | 'saas_software'
    | 'ecommerce_retail'
    | 'finance_fintech'
    | 'healthcare'
    | 'education'
    | 'media_entertainment'
    | 'manufacturing'
    | 'government_nonprofit'
    | 'hospitality_travel'
    | 'other';
}

export const sampleDemographics: SampleDemographics = {
  name: 'Sample Interviewee',
  gender: 'non_binary',
  age: 34,
  income: '100k_200k',
  marital_status: 'married',
  country: 'US',
  job_role: 'product_manager',
  industry: 'saas_software',
};

export const sampleProject = {
  id: '11111111-1111-1111-1111-111111111111',
  name: 'Onboarding research Q2',
  description: 'Interviews with new signups in the last 30 days.',
  created_at: '2026-05-01T10:00:00Z',
  updated_at: '2026-05-01T10:00:00Z',
};

export const sampleTranscriptSegments = [
  {
    speaker: 'A',
    start: 0.0,
    end: 6.2,
    text: 'Thanks for taking the time today. Can you walk me through how you currently track customer feedback?',
  },
  {
    speaker: 'B',
    start: 6.5,
    end: 24.1,
    text: "Honestly, it's a mess. We have feedback coming in from intercom, from sales calls, from support tickets, and nobody puts it in one place. I spend probably four hours a week just copying notes between Notion and a spreadsheet.",
  },
  {
    speaker: 'A',
    start: 24.5,
    end: 27.0,
    text: "That sounds painful. What's the worst part?",
  },
  {
    speaker: 'B',
    start: 27.3,
    end: 46.9,
    text: "The worst part is that by the time I've aggregated everything, the insight is stale. Last quarter we shipped a feature based on feedback that was two months old and three customers had already churned over it. I felt sick about that.",
  },
  {
    speaker: 'A',
    start: 47.2,
    end: 49.4,
    text: 'Have you tried any tools to help?',
  },
  {
    speaker: 'B',
    start: 49.7,
    end: 61.1,
    text: "We tried Dovetail for a month but the team wouldn't actually use it. The upload step was too slow and tagging interviews took forever. We churned off it.",
  },
  {
    speaker: 'A',
    start: 61.4,
    end: 63.6,
    text: 'Anything else that gets in the way?',
  },
  {
    speaker: 'B',
    start: 63.9,
    end: 78.4,
    text: "Yeah, our PM team is small, just me and one other person, and we don't have time to do proper research synthesis. So a lot of decisions get made on vibes. That scares me as we grow.",
  },
] as const;

export const sampleTranscriptText = sampleTranscriptSegments
  .map((s) => `Speaker ${s.speaker}: ${s.text}`)
  .join(' ');

export const samplePainPoints = [
  {
    id: '22222222-2222-2222-2222-222222222201',
    interview_id: '33333333-3333-3333-3333-333333333333',
    text: 'Feedback is fragmented across multiple tools, requiring manual aggregation.',
    supporting_quote:
      'We have feedback coming in from intercom, from sales calls, from support tickets, and nobody puts it in one place. I spend probably four hours a week just copying notes between Notion and a spreadsheet.',
    timestamp_start_sec: 6.5,
    timestamp_end_sec: 24.1,
    severity: 4,
    type: 'workaround' as const,
    created_at: '2026-05-01T10:01:00Z',
  },
  {
    id: '22222222-2222-2222-2222-222222222202',
    interview_id: '33333333-3333-3333-3333-333333333333',
    text: 'Slow synthesis means decisions are based on stale insights and customers churn.',
    supporting_quote:
      'Last quarter we shipped a feature based on feedback that was two months old and three customers had already churned over it. I felt sick about that.',
    timestamp_start_sec: 27.3,
    timestamp_end_sec: 46.9,
    severity: 5,
    type: 'pain_point' as const,
    created_at: '2026-05-01T10:01:01Z',
  },
  {
    id: '22222222-2222-2222-2222-222222222203',
    interview_id: '33333333-3333-3333-3333-333333333333',
    text: 'Existing research tools have too much friction for the team to actually use.',
    supporting_quote:
      "We tried Dovetail for a month but the team wouldn't actually use it. The upload step was too slow and tagging interviews took forever. We churned off it.",
    timestamp_start_sec: 49.7,
    timestamp_end_sec: 61.1,
    severity: 3,
    type: 'suggestion' as const,
    created_at: '2026-05-01T10:01:02Z',
  },
  {
    id: '22222222-2222-2222-2222-222222222204',
    interview_id: '33333333-3333-3333-3333-333333333333',
    text: 'Small PM team lacks bandwidth for proper synthesis, so decisions are made on vibes.',
    supporting_quote:
      "our PM team is small, just me and one other person, and we don't have time to do proper research synthesis. So a lot of decisions get made on vibes.",
    timestamp_start_sec: 63.9,
    timestamp_end_sec: 78.4,
    severity: 4,
    type: 'pain_point' as const,
    created_at: '2026-05-01T10:01:03Z',
  },
];

const baseInterview = {
  id: '33333333-3333-3333-3333-333333333333',
  project_id: sampleProject.id,
  audio_filename: 'sample_interview.m4a',
  audio_duration_sec: 78.4,
  source_kind: 'audio' as const,
  type: 'problem_validation' as const,
  demographics: sampleDemographics,
  error_message: null as string | null,
  created_at: '2026-05-01T10:00:00Z',
};

export const sampleInterview = {
  ...baseInterview,
  status: 'completed' as const,
  transcript_text: sampleTranscriptText,
  transcript_segments: sampleTranscriptSegments,
  meeting_notes:
    'User mentioned they switched from a competitor 2 weeks ago. Mood: frustrated but engaged.',
  processed_at: '2026-05-01T10:02:00Z',
  pain_points: samplePainPoints,
};

export const sampleInterviewProcessing = {
  ...baseInterview,
  status: 'transcribing' as const,
  transcript_text: null,
  transcript_segments: null,
  meeting_notes: null as string | null,
  processed_at: null,
  pain_points: [] as typeof samplePainPoints,
};

export const sampleInterviewFailed = {
  ...baseInterview,
  status: 'failed' as const,
  transcript_text: null,
  transcript_segments: null,
  meeting_notes: null as string | null,
  processed_at: null,
  pain_points: [] as typeof samplePainPoints,
  error_message: 'AssemblyAI returned 503; please retry.',
};
