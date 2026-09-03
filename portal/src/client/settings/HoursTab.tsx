import { IconPlus, IconTrash } from "@tabler/icons-react";

import { Button } from "../components/ui/button";
import { Card, CardContent } from "../components/ui/card";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { rootFields, type TabProps } from "./schemaFields";
import { SchemaInput } from "./SchemaInput";

/**
 * When the clinic is open, in the clinic's own timezone. Every due time the
 * ledger computes comes from these spans (CLAUDE.md non-negotiable 8), so an
 * empty day is a closed day, not a missing one.
 *
 * The form is the kit's: the registry's controls under their labels, laid out
 * on the kit's `space-y-8` rhythm, with each weekday its own card.
 */

const WEEKDAYS: [string, string][] = [
  ["mon", "Monday"],
  ["tue", "Tuesday"],
  ["wed", "Wednesday"],
  ["thu", "Thursday"],
  ["fri", "Friday"],
  ["sat", "Saturday"],
  ["sun", "Sunday"],
];

export function HoursTab({ config, schema, onChange, disabled }: TabProps) {
  const hours: Record<string, string[][]> = config.hours ?? {};

  function setSpans(day: string, spans: string[][]) {
    onChange({ ...config, hours: { ...hours, [day]: spans } });
  }

  return (
    <div className="space-y-8">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        {rootFields(schema, ["timezone", "jurisdiction", "retention_days"]).map(
          (field) => (
            <SchemaInput
              key={field.name}
              field={field}
              value={config[field.name]}
              disabled={disabled}
              testId={`config-${field.name}`}
              onChange={(value) => onChange({ ...config, [field.name]: value })}
            />
          ),
        )}
      </div>

      <div className="space-y-3">
        {WEEKDAYS.map(([day, label]) => {
          const spans = hours[day] ?? [];
          return (
            <Card key={day} className="py-3">
              <CardContent className="flex flex-wrap items-center gap-3 px-4">
                <span className="w-24 text-sm font-medium">{label}</span>
                {spans.length === 0 && (
                  <span className="text-muted-foreground text-sm">Closed</span>
                )}
                {spans.map((span, index) => (
                  <span key={index} className="flex items-center gap-2 text-sm">
                    <Input
                      type="time"
                      className="w-32"
                      aria-label={`${label} opens`}
                      data-testid={`hours-${day}-${index}-start`}
                      disabled={disabled}
                      value={span[0] ?? ""}
                      onChange={(event) =>
                        setSpans(
                          day,
                          spans.map((s, i) =>
                            i === index ? [event.target.value, s[1]] : s,
                          ),
                        )
                      }
                    />
                    <span className="text-muted-foreground">to</span>
                    <Input
                      type="time"
                      className="w-32"
                      aria-label={`${label} closes`}
                      data-testid={`hours-${day}-${index}-end`}
                      disabled={disabled}
                      value={span[1] ?? ""}
                      onChange={(event) =>
                        setSpans(
                          day,
                          spans.map((s, i) =>
                            i === index ? [s[0], event.target.value] : s,
                          ),
                        )
                      }
                    />
                    {!disabled && (
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        aria-label={`Remove ${label} hours`}
                        onClick={() =>
                          setSpans(
                            day,
                            spans.filter((_, i) => i !== index),
                          )
                        }
                      >
                        <IconTrash className="size-4" />
                      </Button>
                    )}
                  </span>
                ))}
                {!disabled && (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="ms-auto"
                    data-testid={`hours-${day}-add`}
                    onClick={() => setSpans(day, [...spans, ["09:00", "17:00"]])}
                  >
                    <IconPlus className="size-4" />
                    Add hours
                  </Button>
                )}
              </CardContent>
            </Card>
          );
        })}
      </div>

      <div className="flex flex-col gap-1.5">
        <Label
          htmlFor="config-holidays"
          className="text-muted-foreground text-xs uppercase"
        >
          Holidays (YYYY-MM-DD, comma separated)
        </Label>
        <Input
          id="config-holidays"
          data-testid="config-holidays"
          disabled={disabled}
          value={(config.holidays ?? []).join(", ")}
          onChange={(event) =>
            onChange({
              ...config,
              holidays: event.target.value
                .split(",")
                .map((part) => part.trim())
                .filter(Boolean),
            })
          }
        />
      </div>
    </div>
  );
}
