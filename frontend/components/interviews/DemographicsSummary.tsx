"use client";

/**
 * Read-only summary of the interviewee's demographics on the interview
 * detail page. Renders one label/value row per field, using the
 * `labelFor()` helper to translate the backend's stringly-typed enum
 * values into something a human can read.
 *
 * The `country` field is shown verbatim — it's an ISO 3166-1 alpha-2
 * code (e.g. `US`, `IN`). A nicer rendering with full country names is
 * out of scope for v0.
 */

import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import type { Demographics } from "@/lib/api/types";
import {
  GENDER_OPTIONS,
  INCOME_OPTIONS,
  INDUSTRY_OPTIONS,
  JOB_ROLE_OPTIONS,
  MARITAL_STATUS_OPTIONS,
  labelFor,
} from "@/lib/options";

interface DemographicsSummaryProps {
  demographics: Demographics;
}

export function DemographicsSummary({ demographics }: DemographicsSummaryProps) {
  const rows: { label: string; value: string }[] = [
    { label: "Name", value: demographics.name },
    { label: "Age", value: String(demographics.age) },
    {
      label: "Gender",
      value: labelFor(GENDER_OPTIONS, demographics.gender),
    },
    { label: "Country", value: demographics.country },
    {
      label: "Income",
      value: labelFor(INCOME_OPTIONS, demographics.income),
    },
    {
      label: "Marital status",
      value: labelFor(MARITAL_STATUS_OPTIONS, demographics.marital_status),
    },
    {
      label: "Job role",
      value: labelFor(JOB_ROLE_OPTIONS, demographics.job_role),
    },
    {
      label: "Industry",
      value: labelFor(INDUSTRY_OPTIONS, demographics.industry),
    },
  ];

  return (
    <Card className="shrink-0">
      <CardHeader>
        <CardTitle>Interviewee</CardTitle>
      </CardHeader>
      <CardContent>
        <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-2 text-sm">
          {rows.map((row) => (
            <div key={row.label} className="contents">
              <dt className="text-muted-foreground">{row.label}</dt>
              <dd className="font-medium text-foreground">{row.value}</dd>
            </div>
          ))}
        </dl>
      </CardContent>
    </Card>
  );
}
