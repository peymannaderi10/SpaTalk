import { IconPlus, IconTrash } from "@tabler/icons-react";

import { Button } from "../components/ui/button";
import { Card, CardContent } from "../components/ui/card";
import { Label } from "../components/ui/label";
import { Textarea } from "../components/ui/textarea";
import {
  definition,
  fieldsOf,
  invalidAt,
  type Draft,
  type TabProps,
} from "./schemaFields";
import { SchemaInput } from "./SchemaInput";

/**
 * The prose the assistant may answer from. It goes into the cached system
 * prompt verbatim, so anything that promises an outcome does not belong here.
 *
 * Under it, the questions the clinic answers in its own words: `config.faq`,
 * one row per question, bounded by the runtime's own `FaqItem` model. The
 * runtime renders them into the prompt's facts ahead of the prose and the
 * assistant answers from them first, phrased — they are facts, not scripts,
 * which is why they are edited here and not on the Scripts page.
 *
 * The prose is in the kit's form idiom: a label, the control, and the
 * description under it (`FormDescription` in
 * `src/features/settings/profile/profile-form.tsx`). The rows are the
 * Services page's cards, with the same add and remove controls.
 */
export function KnowledgeTab({
  config,
  schema,
  onChange,
  disabled,
  errors,
}: TabProps) {
  const words = String(config.knowledge ?? "")
    .trim()
    .split(/\s+/)
    .filter(Boolean).length;

  // The runtime's schema decides whether there is an FAQ to edit at all, and
  // how long a question or an answer may be.
  const faqFields = definition(schema, "FaqItem")
    ? fieldsOf(schema, "FaqItem")
    : [];
  const faq: Draft[] = config.faq ?? [];

  function setFaq(next: Draft[]) {
    onChange({ ...config, faq: next });
  }

  return (
    <div className="space-y-8">
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="config-knowledge">What the clinic is</Label>
        <Textarea
          id="config-knowledge"
          rows={24}
          aria-label="Knowledge"
          data-testid="config-knowledge"
          aria-invalid={invalidAt(errors, ["knowledge"]) || undefined}
          disabled={disabled}
          value={String(config.knowledge ?? "")}
          onChange={(event) =>
            onChange({ ...config, knowledge: event.target.value })
          }
        />
        <p className="text-muted-foreground text-sm">
          Facts about the clinic in plain prose. Keep it under 4,000 words; no
          promises, no medical claims. {words} words at the moment.
        </p>
      </div>

      {faqFields.length > 0 && (
        <section className="space-y-3" data-testid="faq-section">
          <div>
            <h3 className="text-sm font-medium">Frequently asked</h3>
            <p className="text-muted-foreground text-sm">
              Answers the assistant may phrase in its own words. Facts, not
              scripts.
            </p>
          </div>

          {faq.map((row, index) => (
            <Card key={index} data-testid={`faq-${index}`}>
              <CardContent className="space-y-3">
                {faqFields.map((field) => (
                  <SchemaInput
                    key={field.name}
                    field={field}
                    value={row[field.name]}
                    disabled={disabled}
                    long={field.name === "answer"}
                    invalid={invalidAt(errors, ["faq", index, field.name])}
                    testId={`faq-${index}-${field.name}`}
                    onChange={(value) =>
                      setFaq(
                        faq.map((entry, i) =>
                          i === index
                            ? { ...entry, [field.name]: value }
                            : entry,
                        ),
                      )
                    }
                  />
                ))}
                {!disabled && (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    data-testid={`remove-faq-${index}`}
                    onClick={() => setFaq(faq.filter((_, i) => i !== index))}
                  >
                    <IconTrash className="size-4" />
                    Remove this question
                  </Button>
                )}
              </CardContent>
            </Card>
          ))}

          {!disabled && (
            <Button
              type="button"
              variant="outline"
              size="sm"
              data-testid="add-faq"
              onClick={() =>
                setFaq([
                  ...faq,
                  Object.fromEntries(
                    faqFields.map((field) => [field.name, ""]),
                  ),
                ])
              }
            >
              <IconPlus className="size-4" />
              Add a question
            </Button>
          )}
        </section>
      )}
    </div>
  );
}
