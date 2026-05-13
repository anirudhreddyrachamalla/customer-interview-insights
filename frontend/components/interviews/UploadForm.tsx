"use client";

/**
 * Upload form for creating a new interview inside a project.
 *
 * Mounted at `/projects/{id}/interviews/new`. Posts multipart/form-data
 * to `POST /api/v1/projects/{projectId}/interviews` and, on success,
 * navigates to the new interview's detail page where the polling lives
 * (task #4).
 *
 * Validation strategy:
 *   - Client-side (Zod) catches obvious shape problems immediately:
 *     missing fields, wrong extension, oversize file, bad country code.
 *   - The backend is the source of truth for enum values and content
 *     limits (100 MB / 90 minutes). When the server returns a 422 in
 *     either Pydantic shape, we surface each `loc`-matched message
 *     inline on its field. Anything we can't map back to a field
 *     becomes a toast so the user is never silently blocked.
 *
 * UX notes:
 *   - Submit is disabled while pending and shows an inline spinner so
 *     the user can't double-submit a slow upload.
 *   - The audio block displays the selected filename + size so the user
 *     can sanity-check what they picked before submitting.
 *   - All Select inputs render options from `lib/options.ts` so labels
 *     and values stay in lockstep with the backend enums.
 */

import { zodResolver } from "@hookform/resolvers/zod";
import { Loader2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useId, useState } from "react";
import {
  Controller,
  useForm,
  type Control,
  type FieldErrors,
  type Path,
  type SubmitHandler,
  type UseFormSetError,
} from "react-hook-form";
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
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ApiError, api } from "@/lib/api/client";
import type { Demographics, Interview } from "@/lib/api/types";
import {
  GENDER_OPTIONS,
  INCOME_OPTIONS,
  INDUSTRY_OPTIONS,
  INTERVIEW_TYPE_OPTIONS,
  JOB_ROLE_OPTIONS,
  MARITAL_STATUS_OPTIONS,
  type SelectOption,
} from "@/lib/options";
import { useMutation } from "@tanstack/react-query";

// --- Schema -----------------------------------------------------------

const MAX_FILE_BYTES = 100 * 1024 * 1024; // 100 MB — matches server cap.
const MAX_TRANSCRIPT_BYTES = 5 * 1024 * 1024; // 5 MB — matches server cap.
const ALLOWED_EXT_RE = /\.(mp3|wav|m4a)$/i;
const ALLOWED_TRANSCRIPT_EXT_RE = /\.vtt$/i;
const MAX_MEETING_NOTES_CHARS = 10_000; // matches server cap.

/** Which file tab the user is on. Controls which file field is required
 *  and which multipart key the body is POSTed under. */
export type UploadKind = "audio" | "transcript";

const genderValues = GENDER_OPTIONS.map((o) => o.value) as [
  (typeof GENDER_OPTIONS)[number]["value"],
  ...(typeof GENDER_OPTIONS)[number]["value"][],
];
const incomeValues = INCOME_OPTIONS.map((o) => o.value) as [
  (typeof INCOME_OPTIONS)[number]["value"],
  ...(typeof INCOME_OPTIONS)[number]["value"][],
];
const maritalValues = MARITAL_STATUS_OPTIONS.map((o) => o.value) as [
  (typeof MARITAL_STATUS_OPTIONS)[number]["value"],
  ...(typeof MARITAL_STATUS_OPTIONS)[number]["value"][],
];
const jobRoleValues = JOB_ROLE_OPTIONS.map((o) => o.value) as [
  (typeof JOB_ROLE_OPTIONS)[number]["value"],
  ...(typeof JOB_ROLE_OPTIONS)[number]["value"][],
];
const industryValues = INDUSTRY_OPTIONS.map((o) => o.value) as [
  (typeof INDUSTRY_OPTIONS)[number]["value"],
  ...(typeof INDUSTRY_OPTIONS)[number]["value"][],
];

/** Build the zod schema for a given upload kind. We swap the `audio`
 *  vs `transcript` validation in/out depending on the active tab so the
 *  audio-only rules don't fire while the user is on the transcript tab,
 *  and vice versa. */
export function makeUploadFormSchema(kind: UploadKind) {
  const audioField =
    kind === "audio"
      ? z
          .instanceof(File, { message: "Please choose an audio file" })
          .refine((f) => f.size > 0, "Selected file is empty")
          .refine(
            (f) => f.size <= MAX_FILE_BYTES,
            "File must be ≤ 100 MB",
          )
          .refine(
            (f) => ALLOWED_EXT_RE.test(f.name),
            "Must be .mp3, .wav, or .m4a",
          )
      : z.instanceof(File).optional();
  const transcriptField =
    kind === "transcript"
      ? z
          .instanceof(File, { message: "Please choose a transcript file" })
          .refine((f) => f.size > 0, "Selected file is empty")
          .refine(
            (f) => f.size <= MAX_TRANSCRIPT_BYTES,
            "File must be ≤ 5 MB",
          )
          .refine(
            (f) => ALLOWED_TRANSCRIPT_EXT_RE.test(f.name),
            "Must be .vtt",
          )
      : z.instanceof(File).optional();
  return z.object({
    audio: audioField,
    transcript: transcriptField,
    type: z.literal("problem_validation"),
    name: z
      .string()
      .trim()
      .min(1, "Name is required")
      .max(200, "Name must be at most 200 characters"),
    gender: z.enum(genderValues),
    age: z
      .number({ message: "Age is required" })
      .int("Age must be a whole number")
      .min(13, "Age must be at least 13")
      .max(120, "Age must be at most 120"),
    income: z.enum(incomeValues),
    marital_status: z.enum(maritalValues),
    country: z
      .string()
      .trim()
      .length(2, "Use a 2-letter country code (e.g. US, IN)")
      .regex(/^[a-zA-Z]{2}$/, "Country code must be two letters")
      .transform((s) => s.toUpperCase()),
    job_role: z.enum(jobRoleValues),
    industry: z.enum(industryValues),
    meeting_notes: z
      .string()
      .max(
        MAX_MEETING_NOTES_CHARS,
        "Meeting notes must be 10,000 characters or fewer",
      )
      .optional()
      .or(z.literal("")),
  });
}

/** Backwards-compatible default schema — `audio` kind. Existing tests
 *  import this name. */
export const uploadFormSchema = makeUploadFormSchema("audio");

/** What the form fields hold before zod transforms (e.g. `country`
 *  before uppercasing). This is what RHF stores internally. */
export type UploadFormValues = z.input<typeof uploadFormSchema> & {
  /** Transcript file picker — only relevant when on the transcript tab.
   *  Declared on the input type so RHF's `register`/`setValue` typings
   *  accept it whichever schema is currently active. */
  transcript?: File;
};
/** What `handleSubmit` hands back to the submit handler (post-transform). */
export type UploadFormOutput = z.output<typeof uploadFormSchema> & {
  transcript?: File;
};

/** Fields the server may complain about. We expand demographic-prefixed
 *  loc paths back into our flat field names. The server's "exactly one
 *  of audio/transcript" rule returns `loc=["audio"]`, so we map that to
 *  whichever file picker is currently visible — see `applyServerError`. */
const KNOWN_FIELDS: ReadonlySet<keyof UploadFormValues> = new Set([
  "audio",
  "transcript",
  "type",
  "name",
  "gender",
  "age",
  "income",
  "marital_status",
  "country",
  "job_role",
  "industry",
  "meeting_notes",
]);

// --- Component --------------------------------------------------------

interface UploadFormProps {
  projectId: string;
}

export function UploadForm({ projectId }: UploadFormProps) {
  const router = useRouter();
  const formId = useId();
  const [kind, setKind] = useState<UploadKind>("audio");

  const {
    register,
    handleSubmit,
    setError,
    setValue,
    watch,
    control,
    clearErrors,
    formState: { errors, isSubmitting },
  } = useForm<UploadFormValues, unknown, UploadFormOutput>({
    resolver: zodResolver(makeUploadFormSchema(kind)),
    defaultValues: {
      type: "problem_validation",
      name: "",
      country: "",
      meeting_notes: "",
      // The other enums are intentionally left unset so the user sees
      // the placeholder and can't accidentally submit a default. Zod
      // surfaces "Required" for whichever they skip.
    } as Partial<UploadFormValues> as UploadFormValues,
  });

  const audioFile = watch("audio") as File | undefined;
  const transcriptFile = watch("transcript") as File | undefined;
  const meetingNotesValue = watch("meeting_notes") ?? "";
  const meetingNotesLength = meetingNotesValue.length;
  const meetingNotesOverLimit = meetingNotesLength > MAX_MEETING_NOTES_CHARS;

  const uploadMutation = useMutation<Interview, unknown, FormData>({
    mutationFn: (formData) =>
      api.postFormData<Interview>(
        `/projects/${projectId}/interviews`,
        formData,
      ),
  });

  const submitting = isSubmitting || uploadMutation.isPending;

  function handleKindChange(next: UploadKind) {
    if (next === kind) return;
    setKind(next);
    // Drop the inactive file + any stale error so the user starts the
    // new tab with a clean picker. RHF won't auto-clear cross-schema
    // residue otherwise.
    if (next === "audio") {
      setValue("transcript", undefined as unknown as File, {
        shouldValidate: false,
        shouldDirty: false,
      });
      clearErrors("transcript");
    } else {
      setValue("audio", undefined as unknown as File, {
        shouldValidate: false,
        shouldDirty: false,
      });
      clearErrors("audio");
    }
  }

  const onSubmit: SubmitHandler<UploadFormOutput> = (values) => {
    const demographics: Demographics = {
      name: values.name,
      gender: values.gender,
      age: values.age,
      income: values.income,
      marital_status: values.marital_status,
      country: values.country, // already uppercased by the zod transform
      job_role: values.job_role,
      industry: values.industry,
    };

    const formData = new FormData();
    // Pass the filename explicitly. Most browsers infer it from
    // `File.name`, but some environments (and jsdom under Vitest) fall
    // back to `"blob"`, which would make the server reject the file.
    //
    // The server's contract is exactly-one-of: post EITHER `audio` OR
    // `transcript`, never both (see SPEC_v1.1 §2 API contract).
    if (kind === "audio" && values.audio) {
      formData.append("audio", values.audio, values.audio.name);
    } else if (kind === "transcript" && values.transcript) {
      formData.append(
        "transcript",
        values.transcript,
        values.transcript.name,
      );
    }
    formData.append("type", values.type);
    formData.append("demographics", JSON.stringify(demographics));

    // Only forward meeting notes when the user actually typed something.
    // The server treats trimmed-empty as NULL anyway, but skipping the
    // field keeps the multipart body cleaner and avoids round-tripping
    // pointless whitespace.
    const trimmedNotes = (values.meeting_notes ?? "").trim();
    if (trimmedNotes.length > 0) {
      formData.append("meeting_notes", values.meeting_notes ?? "");
    }

    uploadMutation.mutate(formData, {
      onSuccess: (interview) => {
        router.push(`/interviews/${interview.id}`);
      },
      onError: (err) => {
        applyServerError(err, setError, kind);
      },
    });
  };

  return (
    <form
      id={formId}
      noValidate
      onSubmit={handleSubmit(onSubmit)}
      className="flex flex-col gap-6"
      aria-busy={submitting}
    >
      {/* --- Source-file section ------------------------------------- */}
      <Card>
        <CardHeader>
          <CardTitle>Source</CardTitle>
          <CardDescription>
            {kind === "audio"
              ? "Upload the interview recording. .mp3, .wav, or .m4a, up to 100 MB and 90 minutes."
              : "Upload a .vtt transcript file. Up to 5 MB."}
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <Tabs
            value={kind}
            onValueChange={(v) => handleKindChange(v as UploadKind)}
            data-testid="upload-kind-tabs"
          >
            <TabsList>
              <TabsTrigger value="audio" data-testid="upload-kind-audio-tab">
                Upload audio
              </TabsTrigger>
              <TabsTrigger
                value="transcript"
                data-testid="upload-kind-transcript-tab"
              >
                Upload transcript
              </TabsTrigger>
            </TabsList>
          </Tabs>

          {kind === "audio" ? (
            <div className="flex flex-col gap-1.5">
              <Label htmlFor={`${formId}-audio`}>Audio file</Label>
              <Input
                id={`${formId}-audio`}
                type="file"
                accept=".mp3,.wav,.m4a,audio/mpeg,audio/mp3,audio/wav,audio/x-wav,audio/wave,audio/x-m4a,audio/mp4,audio/aac"
                aria-invalid={errors.audio ? true : undefined}
                aria-describedby={
                  errors.audio ? `${formId}-audio-error` : undefined
                }
                disabled={submitting}
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) {
                    setValue("audio", file, {
                      shouldDirty: true,
                      shouldValidate: true,
                    });
                  }
                }}
              />
              {audioFile ? (
                <p className="text-xs text-muted-foreground">
                  Selected:{" "}
                  <span className="font-medium">{audioFile.name}</span>{" "}
                  ({formatBytes(audioFile.size)})
                </p>
              ) : null}
              {errors.audio ? (
                <p
                  id={`${formId}-audio-error`}
                  role="alert"
                  className="text-xs text-destructive"
                >
                  {errors.audio.message as string}
                </p>
              ) : null}
            </div>
          ) : (
            <div className="flex flex-col gap-1.5">
              <Label htmlFor={`${formId}-transcript`}>Transcript file</Label>
              <Input
                id={`${formId}-transcript`}
                type="file"
                accept=".vtt,text/vtt,text/plain"
                aria-invalid={errors.transcript ? true : undefined}
                aria-describedby={
                  errors.transcript
                    ? `${formId}-transcript-error`
                    : undefined
                }
                disabled={submitting}
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) {
                    setValue("transcript", file, {
                      shouldDirty: true,
                      shouldValidate: true,
                    });
                  }
                }}
              />
              {transcriptFile ? (
                <p className="text-xs text-muted-foreground">
                  Selected:{" "}
                  <span className="font-medium">{transcriptFile.name}</span>{" "}
                  ({formatBytes(transcriptFile.size)})
                </p>
              ) : null}
              {errors.transcript ? (
                <p
                  id={`${formId}-transcript-error`}
                  role="alert"
                  className="text-xs text-destructive"
                >
                  {errors.transcript.message as string}
                </p>
              ) : null}
            </div>
          )}
        </CardContent>
      </Card>

      {/* --- Meeting notes ------------------------------------------- */}
      <Card>
        <CardHeader>
          <CardTitle>Meeting notes</CardTitle>
          <CardDescription>
            Optional — any context the analyst noted before or during the
            interview.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor={`${formId}-meeting-notes`} className="sr-only">
              Meeting notes
            </Label>
            <Textarea
              id={`${formId}-meeting-notes`}
              rows={5}
              maxLength={undefined}
              aria-invalid={errors.meeting_notes ? true : undefined}
              aria-describedby={
                errors.meeting_notes
                  ? `${formId}-meeting-notes-error`
                  : `${formId}-meeting-notes-counter`
              }
              disabled={submitting}
              placeholder="e.g. Recruited via Slack community. Mentioned switching from a competitor 2 weeks ago."
              {...register("meeting_notes")}
            />
            <div className="flex items-center justify-between gap-2">
              {errors.meeting_notes ? (
                <p
                  id={`${formId}-meeting-notes-error`}
                  role="alert"
                  className="text-xs text-destructive"
                >
                  {errors.meeting_notes.message as string}
                </p>
              ) : (
                <span aria-hidden className="text-xs text-muted-foreground" />
              )}
              <p
                id={`${formId}-meeting-notes-counter`}
                className={
                  meetingNotesOverLimit
                    ? "text-xs text-destructive"
                    : "text-xs text-muted-foreground"
                }
              >
                {meetingNotesLength}/{MAX_MEETING_NOTES_CHARS}
              </p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* --- Interviewee details ------------------------------------- */}
      <Card>
        <CardHeader>
          <CardTitle>Interviewee details</CardTitle>
          <CardDescription>
            Use a pseudonym if you need to keep this person anonymous.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid grid-cols-1 gap-5 md:grid-cols-2">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor={`${formId}-name`}>Name</Label>
            <Input
              id={`${formId}-name`}
              type="text"
              autoComplete="off"
              aria-invalid={errors.name ? true : undefined}
              aria-describedby={
                errors.name ? `${formId}-name-error` : undefined
              }
              disabled={submitting}
              placeholder="Jane Doe"
              {...register("name")}
            />
            {errors.name ? (
              <p
                id={`${formId}-name-error`}
                role="alert"
                className="text-xs text-destructive"
              >
                {errors.name.message}
              </p>
            ) : null}
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor={`${formId}-age`}>Age</Label>
            <Input
              id={`${formId}-age`}
              type="number"
              inputMode="numeric"
              min={13}
              max={120}
              aria-invalid={errors.age ? true : undefined}
              aria-describedby={errors.age ? `${formId}-age-error` : undefined}
              disabled={submitting}
              placeholder="34"
              {...register("age", { valueAsNumber: true })}
            />
            {errors.age ? (
              <p
                id={`${formId}-age-error`}
                role="alert"
                className="text-xs text-destructive"
              >
                {errors.age.message}
              </p>
            ) : null}
          </div>

          <FormSelect
            name="gender"
            label="Gender"
            options={GENDER_OPTIONS}
            placeholder="Select gender"
            control={control}
            errors={errors}
            formId={formId}
            disabled={submitting}
          />

          <div className="flex flex-col gap-1.5">
            <Label htmlFor={`${formId}-country`}>
              Country{" "}
              <span className="text-xs font-normal text-muted-foreground">
                (ISO code, e.g. US)
              </span>
            </Label>
            <Input
              id={`${formId}-country`}
              type="text"
              maxLength={2}
              autoComplete="country"
              aria-invalid={errors.country ? true : undefined}
              aria-describedby={
                errors.country ? `${formId}-country-error` : undefined
              }
              disabled={submitting}
              placeholder="US"
              className="uppercase"
              {...register("country", {
                // Live-uppercase what the user types so they see the
                // canonical form immediately (matches server normalisation).
                onChange: (e) => {
                  e.target.value = e.target.value.toUpperCase();
                },
              })}
            />
            {errors.country ? (
              <p
                id={`${formId}-country-error`}
                role="alert"
                className="text-xs text-destructive"
              >
                {errors.country.message}
              </p>
            ) : null}
          </div>
        </CardContent>
      </Card>

      {/* --- Background ---------------------------------------------- */}
      <Card>
        <CardHeader>
          <CardTitle>Background</CardTitle>
          <CardDescription>
            These segments help filter and group pain points later.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid grid-cols-1 gap-5 md:grid-cols-2">
          <FormSelect
            name="income"
            label="Income"
            options={INCOME_OPTIONS}
            placeholder="Select income bracket"
            control={control}
            errors={errors}
            formId={formId}
            disabled={submitting}
          />

          <FormSelect
            name="marital_status"
            label="Marital status"
            options={MARITAL_STATUS_OPTIONS}
            placeholder="Select marital status"
            control={control}
            errors={errors}
            formId={formId}
            disabled={submitting}
          />

          <FormSelect
            name="job_role"
            label="Job role"
            options={JOB_ROLE_OPTIONS}
            placeholder="Select job role"
            control={control}
            errors={errors}
            formId={formId}
            disabled={submitting}
          />

          <FormSelect
            name="industry"
            label="Industry"
            options={INDUSTRY_OPTIONS}
            placeholder="Select industry"
            control={control}
            errors={errors}
            formId={formId}
            disabled={submitting}
          />

          <FormSelect
            name="type"
            label="Interview type"
            options={INTERVIEW_TYPE_OPTIONS}
            placeholder="Problem validation"
            control={control}
            errors={errors}
            formId={formId}
            disabled={submitting}
          />
        </CardContent>
      </Card>

      <div className="flex items-center justify-end gap-2">
        <Button
          type="button"
          variant="secondary"
          disabled={submitting}
          render={<Link href={`/projects/${projectId}`}>Cancel</Link>}
        />
        <Button type="submit" disabled={submitting}>
          {submitting ? (
            <>
              <Loader2 className="size-4 animate-spin" aria-hidden />
              Uploading…
            </>
          ) : (
            "Upload interview"
          )}
        </Button>
      </div>
    </form>
  );
}

// --- Helpers ----------------------------------------------------------

interface FormSelectProps<TValue extends string> {
  name: keyof UploadFormValues;
  label: string;
  options: readonly SelectOption<TValue>[];
  placeholder: string;
  control: Control<UploadFormValues>;
  errors: FieldErrors<UploadFormValues>;
  formId: string;
  disabled: boolean;
}

function FormSelect<TValue extends string>({
  name,
  label,
  options,
  placeholder,
  control,
  errors,
  formId,
  disabled,
}: FormSelectProps<TValue>) {
  const errorMsg = (errors[name]?.message as string | undefined) ?? undefined;
  const fieldId = `${formId}-${String(name)}`;
  const errorId = `${fieldId}-error`;
  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={fieldId}>{label}</Label>
      <Controller
        control={control}
        name={name as Path<UploadFormValues>}
        render={({ field }) => (
          <Select
            // Passing `name` makes base-ui render a hidden form input
            // for this field — useful for native form submission and for
            // test code that wants to drive the value without opening
            // the portal popup.
            name={String(name)}
            value={(field.value as TValue | undefined) ?? null}
            onValueChange={(v) => field.onChange(v)}
            disabled={disabled}
          >
            <SelectTrigger
              id={fieldId}
              className="w-full"
              aria-invalid={errorMsg ? true : undefined}
              aria-describedby={errorMsg ? errorId : undefined}
            >
              <SelectValue placeholder={placeholder} />
            </SelectTrigger>
            <SelectContent>
              {options.map((opt) => (
                <SelectItem key={opt.value} value={opt.value}>
                  {opt.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
      />
      {errorMsg ? (
        <p id={errorId} role="alert" className="text-xs text-destructive">
          {errorMsg}
        </p>
      ) : null}
    </div>
  );
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** Map a server-side validation error back onto a RHF field where
 *  possible, otherwise toast. Handles both the FastAPI 422 array shape
 *  and the project-create-style field map. Exported only for tests.
 *
 *  `kind` is the currently active upload tab. The v1.1 server returns
 *  the either-or rule with `loc=["audio"]` regardless of which file the
 *  user actually meant to submit; when we're on the transcript tab we
 *  route that message to the visible transcript field so the user sees
 *  it inline rather than in a hidden picker. */
export function applyServerError(
  err: unknown,
  setError: UseFormSetError<UploadFormValues>,
  kind: UploadKind = "audio",
): void {
  if (!(err instanceof ApiError)) {
    const msg = err instanceof Error ? err.message : "Upload failed";
    toast.error(msg);
    return;
  }

  if (err.status === 422 && err.problem.errors) {
    let assignedAnyField = false;
    const errs = err.problem.errors;
    if (Array.isArray(errs)) {
      for (const item of errs) {
        const field = routeFileField(locToField(item.loc), kind);
        if (field) {
          setError(field, { type: "server", message: item.msg });
          assignedAnyField = true;
        }
      }
    } else {
      for (const [field, messages] of Object.entries(errs)) {
        const mapped = routeFileField(locToField([field]), kind);
        if (mapped) {
          setError(mapped, {
            type: "server",
            message: messages.join(", "),
          });
          assignedAnyField = true;
        }
      }
    }
    if (!assignedAnyField) {
      toast.error(err.problem.detail ?? err.problem.title ?? "Validation failed");
    }
    return;
  }

  // Non-422 errors (413 file too large, 415 bad mime, 404 missing project,
  // 5xx): toast the most specific message we can find.
  toast.error(err.problem.detail ?? err.problem.title ?? err.message);
}

/** Route a mapped field name to the visible file picker. The server's
 *  either-or-required rule always returns `loc=["audio"]`, so when we're
 *  on the transcript tab we rewrite that to the transcript field. */
function routeFileField(
  field: keyof UploadFormValues | undefined,
  kind: UploadKind,
): keyof UploadFormValues | undefined {
  if (!field) return undefined;
  if (field === "audio" && kind === "transcript") return "transcript";
  if (field === "transcript" && kind === "audio") return "audio";
  return field;
}

/** Walk a Pydantic `loc` path (e.g. `["body", "demographics", "country"]`)
 *  back to the matching flat form field. Returns `undefined` if the
 *  field isn't one we render. */
function locToField(
  loc: (string | number)[] | undefined,
): keyof UploadFormValues | undefined {
  if (!loc?.length) return undefined;
  // Walk from the end — the last string segment is the field name.
  for (let i = loc.length - 1; i >= 0; i -= 1) {
    const seg = loc[i];
    if (typeof seg === "string" && (KNOWN_FIELDS as Set<string>).has(seg)) {
      return seg as keyof UploadFormValues;
    }
  }
  return undefined;
}
