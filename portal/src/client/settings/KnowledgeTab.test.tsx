import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { KnowledgeTab } from "./KnowledgeTab";

/**
 * The FAQ rows on the Knowledge page. They live in `config.faq`, edited
 * through the tab's `onChange` like every other field, and their bounds come
 * from the runtime's own `FaqItem` model rather than from a number typed here.
 */

/** A trimmed copy of what `GET /internal/schema/tenant-config` serves. */
const schema = {
  $defs: {
    FaqItem: {
      properties: {
        question: {
          maxLength: 200,
          minLength: 1,
          title: "Question",
          type: "string",
        },
        answer: {
          maxLength: 600,
          minLength: 1,
          title: "Answer",
          type: "string",
        },
      },
      required: ["question", "answer"],
      title: "FaqItem",
      type: "object",
    },
  },
  properties: {
    knowledge: { title: "Knowledge", type: "string" },
    faq: { items: { $ref: "#/$defs/FaqItem" }, title: "Faq", type: "array" },
  },
  title: "TenantConfig",
  type: "object",
};

const config = {
  knowledge: "A medspa in Mississauga.",
  faq: [
    { question: "Where do I park?", answer: "Behind the building, free." },
    { question: "Do you take walk-ins?", answer: "No, every visit is booked." },
  ],
};

function mount(overrides: Partial<Parameters<typeof KnowledgeTab>[0]> = {}) {
  const onChange = vi.fn();
  render(
    <KnowledgeTab
      config={config}
      schema={schema}
      onChange={onChange}
      disabled={false}
      {...overrides}
    />,
  );
  return onChange;
}

describe("the Knowledge tab's FAQ rows", () => {
  it("renders one row per entry of config.faq", () => {
    mount();
    expect(screen.getByTestId("faq-0-question")).toHaveValue(
      "Where do I park?",
    );
    expect(screen.getByTestId("faq-0-answer")).toHaveValue(
      "Behind the building, free.",
    );
    expect(screen.getByTestId("faq-1-question")).toHaveValue(
      "Do you take walk-ins?",
    );
    expect(screen.queryByTestId("faq-2")).toBeNull();
    expect(
      screen.getByText(
        "Answers the assistant may phrase in its own words. Facts, not scripts.",
      ),
    ).toBeInTheDocument();
  });

  it("adds an empty row on Add a question", () => {
    const onChange = mount();
    fireEvent.click(screen.getByTestId("add-faq"));
    expect(onChange).toHaveBeenCalledTimes(1);
    const next = onChange.mock.calls[0][0];
    expect(next.faq).toHaveLength(3);
    expect(next.faq[2]).toEqual({ question: "", answer: "" });
    expect(next.knowledge).toBe(config.knowledge);
  });

  it("edits an answer through onChange", () => {
    const onChange = mount();
    fireEvent.change(screen.getByTestId("faq-1-answer"), {
      target: { value: "Yes, when a room is free." },
    });
    const next = onChange.mock.calls[0][0];
    expect(next.faq[1]).toEqual({
      question: "Do you take walk-ins?",
      answer: "Yes, when a room is free.",
    });
    expect(next.faq[0]).toEqual(config.faq[0]);
  });

  it("drops a row on Remove", () => {
    const onChange = mount();
    fireEvent.click(screen.getByTestId("remove-faq-0"));
    const next = onChange.mock.calls[0][0];
    expect(next.faq).toEqual([config.faq[1]]);
  });

  it("takes the length limits from the schema's FaqItem", () => {
    mount();
    expect(screen.getByTestId("faq-0-answer").tagName).toBe("TEXTAREA");
    expect(screen.getByTestId("faq-0-answer")).toHaveAttribute(
      "maxlength",
      "600",
    );
    expect(screen.getByTestId("faq-0-question")).toHaveAttribute(
      "maxlength",
      "200",
    );
  });

  it("marks the field a refused save named, and no other", () => {
    mount({ errors: [{ path: ["faq", "1", "answer"] }] });
    expect(screen.getByTestId("faq-1-answer")).toHaveAttribute(
      "aria-invalid",
      "true",
    );
    expect(screen.getByTestId("faq-1-question")).not.toHaveAttribute(
      "aria-invalid",
    );
    expect(screen.getByTestId("faq-0-answer")).not.toHaveAttribute(
      "aria-invalid",
    );
  });

  it("offers no add or remove control when the page is read only", () => {
    mount({ disabled: true });
    expect(screen.queryByTestId("add-faq")).toBeNull();
    expect(screen.queryByTestId("remove-faq-0")).toBeNull();
    expect(screen.getByTestId("faq-0-answer")).toBeDisabled();
  });

  it("still edits the prose knowledge above the rows", () => {
    const onChange = mount();
    fireEvent.change(screen.getByTestId("config-knowledge"), {
      target: { value: "New prose." },
    });
    expect(onChange.mock.calls[0][0]).toEqual({
      ...config,
      knowledge: "New prose.",
    });
  });
});
