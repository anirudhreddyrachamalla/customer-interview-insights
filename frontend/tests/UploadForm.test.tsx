/**
 * Component tests for `UploadForm`.
 *
 * Covers:
 *   - Submitting an empty form blocks the request and surfaces inline
 *     validation messages from Zod for the required fields.
 *   - A complete, valid form posts multipart/form-data to
 *     `/api/v1/projects/{id}/interviews` with `audio`, `type`, and a
 *     JSON-serialised `demographics` payload, then navigates to the new
 *     interview's detail page.
 *
 * The MSW server in `tests/msw/server.ts` intercepts the request; we
 * register a one-off handler in the success test so we can inspect the
 * exact FormData the form sent. `next/navigation` is mocked so we can
 * assert `router.push(...)` without a real Next runtime.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { UploadForm } from "@/components/interviews/UploadForm";
import { api } from "@/lib/api/client";
import { sampleInterview } from "@/tests/fixtures/sampleInterview";

// --- Mocks ------------------------------------------------------------

const pushMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: pushMock,
    replace: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    refresh: vi.fn(),
    prefetch: vi.fn(),
  }),
}));

// --- Helpers ----------------------------------------------------------

function renderForm() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <UploadForm projectId="proj-123" />
    </QueryClientProvider>,
  );
}

function makeAudioFile(
  name = "interview.m4a",
  bytes = new Uint8Array([1, 2, 3, 4]),
): File {
  return new File([bytes], name, { type: "audio/mp4" });
}

// --- Suite ------------------------------------------------------------

beforeEach(() => {
  pushMock.mockClear();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("UploadForm", () => {
  it("blocks submission and shows inline errors when required fields are empty", async () => {
    const user = userEvent.setup();
    renderForm();

    await user.click(screen.getByRole("button", { name: /upload interview/i }));

    // The audio field is required → message appears inline.
    expect(
      await screen.findByText(/please choose an audio file/i),
    ).toBeInTheDocument();

    // Name + country are required as well; both are zod-required strings.
    expect(screen.getByText(/name is required/i)).toBeInTheDocument();

    // Submission must not have navigated.
    expect(pushMock).not.toHaveBeenCalled();
  });

  it("rejects an audio file with the wrong extension", async () => {
    const user = userEvent.setup();
    renderForm();

    const wrongFile = makeAudioFile("notes.txt", new Uint8Array([1]));
    const fileInput = screen.getByLabelText(/audio file/i) as HTMLInputElement;
    await user.upload(fileInput, wrongFile);

    await user.click(screen.getByRole("button", { name: /upload interview/i }));

    expect(
      await screen.findByText(/must be \.mp3, \.wav, or \.m4a/i),
    ).toBeInTheDocument();
    expect(pushMock).not.toHaveBeenCalled();
  });

  it("rejects an audio file larger than the 100 MB cap", async () => {
    const user = userEvent.setup();
    renderForm();

    // The form caps uploads at 100 MB to match the server. We don't want
    // to allocate that many bytes in jsdom, so we lie about `.size`
    // through the prototype getter — react-hook-form / zod only inspect
    // `f.size`, not the underlying buffer.
    const oversized = new File([new Uint8Array([1, 2])], "big.m4a", {
      type: "audio/mp4",
    });
    Object.defineProperty(oversized, "size", {
      value: 101 * 1024 * 1024, // 101 MB
      configurable: true,
    });

    const fileInput = screen.getByLabelText(/audio file/i) as HTMLInputElement;
    await user.upload(fileInput, oversized);

    await user.click(screen.getByRole("button", { name: /upload interview/i }));

    // Match the zod refinement message: "File must be ≤ 100 MB".
    expect(
      await screen.findByText(/file must be .* 100 mb/i),
    ).toBeInTheDocument();
    expect(pushMock).not.toHaveBeenCalled();
  });

  it("renders a select trigger for every demographics enum and the interview type", () => {
    renderForm();

    // Each select renders a `<Label>` with the friendly label. We rely on
    // the labels here because the trigger button itself only carries the
    // placeholder until a value is chosen. This is the "demographics enum
    // dropdowns" coverage target from tester.md.
    const expectedLabels = [
      "Gender",
      "Income",
      "Marital status",
      "Job role",
      "Industry",
      "Interview type",
    ];
    for (const label of expectedLabels) {
      // exact label so a future "Gender (optional)" tweak doesn't
      // accidentally pass.
      expect(
        screen.getByText(label, { selector: "label" }),
      ).toBeInTheDocument();
    }

    // The hidden form inputs base-ui renders for each Select must be
    // present too — those are what carry the submitted value. Asserting
    // the wiring up-front means a regression that drops `name=...` from
    // the trigger gets caught here rather than in the (slower) submit
    // test below.
    const expectedNames = [
      "gender",
      "income",
      "marital_status",
      "job_role",
      "industry",
      "type",
    ];
    for (const name of expectedNames) {
      expect(
        document.querySelector(`input[name="${name}"]`),
      ).not.toBeNull();
    }
  });

  it("submits multipart form data and navigates to the new interview on success", async () => {
    const user = userEvent.setup();

    // Spy on the API client's `postFormData` so we can inspect the
    // exact FormData the component builds. Using a spy here (instead of
    // an MSW handler) sidesteps jsdom's lossy multipart round-trip,
    // which strips filenames during serialisation.
    const spy = vi
      .spyOn(api, "postFormData")
      .mockResolvedValue({
        ...sampleInterview,
        id: "new-interview-id",
        status: "uploaded",
        transcript_text: null,
        transcript_segments: null,
        processed_at: null,
        pain_points: [],
      });

    renderForm();

    // Audio
    const fileInput = screen.getByLabelText(/audio file/i) as HTMLInputElement;
    await user.upload(fileInput, makeAudioFile("chat.m4a"));

    // Name + age + country
    await user.type(screen.getByLabelText(/^name$/i), "Pat Researcher");
    await user.type(screen.getByLabelText(/^age$/i), "37");
    await user.type(screen.getByLabelText(/country/i), "us");

    // For the base-ui Select primitive, the popup uses portals and a
    // virtualised listbox that's awkward to drive via userEvent in jsdom.
    // Set values via a custom event the base-ui Select Root listens to
    // would be even more brittle, so instead we sidestep the popup by
    // dispatching a synthetic change through React Hook Form's hidden
    // input. We do that by interacting with the form's underlying state:
    // base-ui renders a hidden <input name=...> for form submission of
    // each Select. Find each and set its value programmatically.
    setHiddenSelectValue("gender", "female");
    setHiddenSelectValue("income", "50k_100k");
    setHiddenSelectValue("marital_status", "single");
    setHiddenSelectValue("job_role", "product_manager");
    setHiddenSelectValue("industry", "saas_software");
    setHiddenSelectValue("type", "problem_validation");

    await user.click(screen.getByRole("button", { name: /upload interview/i }));

    await waitFor(() => {
      expect(pushMock).toHaveBeenCalledWith("/interviews/new-interview-id");
    });

    // Inspect what the form actually posted.
    expect(spy).toHaveBeenCalledTimes(1);
    const [path, formData] = spy.mock.calls[0];
    expect(path).toBe("/projects/proj-123/interviews");

    const audio = (formData as FormData).get("audio");
    expect(audio).toBeTruthy();
    expect((audio as File).name).toBe("chat.m4a");

    expect((formData as FormData).get("type")).toBe("problem_validation");

    const demoRaw = (formData as FormData).get("demographics");
    expect(typeof demoRaw).toBe("string");
    expect(JSON.parse(demoRaw as string)).toEqual({
      name: "Pat Researcher",
      gender: "female",
      age: 37,
      income: "50k_100k",
      marital_status: "single",
      country: "US", // zod transform uppercases
      job_role: "product_manager",
      industry: "saas_software",
    });
  });

  it("submits meeting_notes when filled", async () => {
    const user = userEvent.setup();

    const spy = vi.spyOn(api, "postFormData").mockResolvedValue({
      ...sampleInterview,
      id: "new-interview-id",
      status: "uploaded",
      transcript_text: null,
      transcript_segments: null,
      meeting_notes: null,
      processed_at: null,
      pain_points: [],
    });

    renderForm();

    // Required fields so submission can proceed.
    const fileInput = screen.getByLabelText(/audio file/i) as HTMLInputElement;
    await user.upload(fileInput, makeAudioFile("chat.m4a"));
    await user.type(screen.getByLabelText(/^name$/i), "Pat Researcher");
    await user.type(screen.getByLabelText(/^age$/i), "37");
    await user.type(screen.getByLabelText(/country/i), "us");

    setHiddenSelectValue("gender", "female");
    setHiddenSelectValue("income", "50k_100k");
    setHiddenSelectValue("marital_status", "single");
    setHiddenSelectValue("job_role", "product_manager");
    setHiddenSelectValue("industry", "saas_software");
    setHiddenSelectValue("type", "problem_validation");

    // The textarea is the load-bearing assertion target for this test.
    const notesValue =
      "Recruited via Slack community.\nSwitched from a competitor 2 weeks ago.";
    await user.type(screen.getByLabelText(/meeting notes/i), notesValue);

    await user.click(screen.getByRole("button", { name: /upload interview/i }));

    await waitFor(() => {
      expect(pushMock).toHaveBeenCalledWith("/interviews/new-interview-id");
    });

    expect(spy).toHaveBeenCalledTimes(1);
    const [, formData] = spy.mock.calls[0];
    expect((formData as FormData).has("meeting_notes")).toBe(true);
    expect((formData as FormData).get("meeting_notes")).toBe(notesValue);
  });

  it("omits meeting_notes when empty", async () => {
    const user = userEvent.setup();

    const spy = vi.spyOn(api, "postFormData").mockResolvedValue({
      ...sampleInterview,
      id: "new-interview-id",
      status: "uploaded",
      transcript_text: null,
      transcript_segments: null,
      meeting_notes: null,
      processed_at: null,
      pain_points: [],
    });

    renderForm();

    const fileInput = screen.getByLabelText(/audio file/i) as HTMLInputElement;
    await user.upload(fileInput, makeAudioFile("chat.m4a"));
    await user.type(screen.getByLabelText(/^name$/i), "Pat Researcher");
    await user.type(screen.getByLabelText(/^age$/i), "37");
    await user.type(screen.getByLabelText(/country/i), "us");

    setHiddenSelectValue("gender", "female");
    setHiddenSelectValue("income", "50k_100k");
    setHiddenSelectValue("marital_status", "single");
    setHiddenSelectValue("job_role", "product_manager");
    setHiddenSelectValue("industry", "saas_software");
    setHiddenSelectValue("type", "problem_validation");

    // Intentionally do NOT touch the textarea.
    await user.click(screen.getByRole("button", { name: /upload interview/i }));

    await waitFor(() => {
      expect(pushMock).toHaveBeenCalledWith("/interviews/new-interview-id");
    });

    expect(spy).toHaveBeenCalledTimes(1);
    const [, formData] = spy.mock.calls[0];
    expect((formData as FormData).has("meeting_notes")).toBe(false);
  });
});

/**
 * Drive a base-ui Select without opening its portal popup.
 *
 * The Select primitive renders a hidden `<input name="...">` element to
 * participate in native form submission. Setting its value via the
 * native setter + dispatching `change` lets React Hook Form's
 * `Controller` pick up the new value. This avoids the portal/virtual
 * list complexity that jsdom struggles with.
 *
 * If base-ui's internals change, fall back to opening the popup with
 * `user.click(screen.getByRole('combobox', {name}))` and selecting the
 * option by role.
 */
function setHiddenSelectValue(name: string, value: string): void {
  const input = document.querySelector(
    `input[name="${name}"]`,
  ) as HTMLInputElement | null;
  if (!input) {
    throw new Error(
      `No hidden input found for select "${name}". Did the Select primitive change?`,
    );
  }
  const setter = Object.getOwnPropertyDescriptor(
    window.HTMLInputElement.prototype,
    "value",
  )?.set;
  setter?.call(input, value);
  input.dispatchEvent(new Event("input", { bubbles: true }));
  input.dispatchEvent(new Event("change", { bubbles: true }));
}
