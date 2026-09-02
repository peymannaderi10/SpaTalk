import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { rootFields, type TabProps } from "./schemaFields";
import { SchemaInput } from "./SchemaInput";

/**
 * When the clinic is open, in the clinic's own timezone. Every due time the
 * ledger computes comes from these spans (CLAUDE.md non-negotiable 8), so an
 * empty day is a closed day, not a missing one.
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

      <div className="space-y-4">
        {WEEKDAYS.map(([day, label]) => {
          const spans = hours[day] ?? [];
          return (
            <div
              key={day}
              className="border-border flex flex-wrap items-center gap-3 rounded-lg border p-3"
            >
              <span className="w-28 text-sm font-medium">{label}</span>
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
                      variant="outline"
                      size="sm"
                      onClick={() =>
                        setSpans(
                          day,
                          spans.filter((_, i) => i !== index),
                        )
                      }
                    >
                      Remove
                    </Button>
                  )}
                </span>
              ))}
              {!disabled && (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  data-testid={`hours-${day}-add`}
                  onClick={() => setSpans(day, [...spans, ["09:00", "17:00"]])}
                >
                  Add hours
                </Button>
              )}
            </div>
          );
        })}
      </div>

      <label className="flex flex-col gap-1 text-sm">
        <span className="text-muted-foreground text-xs uppercase">
          Holidays (YYYY-MM-DD, comma separated)
        </span>
        <Input
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
      </label>
    </div>
  );
}
