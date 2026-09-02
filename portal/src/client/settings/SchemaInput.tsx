import { Input } from "../components/ui/input";
import { Textarea } from "../components/ui/textarea";
import { type SchemaField } from "./schemaFields";

/**
 * One control, decided by the runtime's schema rather than by a hand-written
 * list here: a boolean is a checkbox, a `Literal` is a select, an int is a
 * number, everything else is text.
 */
export function SchemaInput({
  field,
  value,
  onChange,
  disabled,
  testId,
  long,
}: {
  field: SchemaField;
  value: unknown;
  onChange: (value: unknown) => void;
  disabled?: boolean;
  testId?: string;
  /** Render a string on several lines: knowledge and the fixed scripts. */
  long?: boolean;
}) {
  const label = (
    <span className="text-muted-foreground text-xs uppercase">
      {field.title}
      {field.required && " *"}
    </span>
  );

  if (field.kind === "boolean") {
    return (
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          data-testid={testId}
          disabled={disabled}
          checked={Boolean(value)}
          onChange={(event) => onChange(event.target.checked)}
        />
        {label}
      </label>
    );
  }

  if (field.kind === "enum") {
    return (
      <label className="flex flex-col gap-1 text-sm">
        {label}
        <select
          data-testid={testId}
          aria-label={field.title}
          disabled={disabled}
          className="border-border bg-background text-foreground rounded-md border px-2 py-1 text-sm disabled:opacity-60"
          value={String(value ?? "")}
          onChange={(event) => onChange(event.target.value)}
        >
          {field.nullable && <option value="">not set</option>}
          {(field.options ?? []).map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </select>
      </label>
    );
  }

  if (field.kind === "integer" || field.kind === "number") {
    return (
      <label className="flex flex-col gap-1 text-sm">
        {label}
        <Input
          type="number"
          data-testid={testId}
          aria-label={field.title}
          disabled={disabled}
          value={value === null || value === undefined ? "" : String(value)}
          onChange={(event) => {
            const raw = event.target.value;
            if (raw === "") {
              onChange(field.nullable ? null : "");
              return;
            }
            onChange(Number(raw));
          }}
        />
      </label>
    );
  }

  if (long) {
    return (
      <label className="flex flex-col gap-1 text-sm">
        {label}
        <Textarea
          rows={3}
          data-testid={testId}
          aria-label={field.title}
          disabled={disabled}
          value={String(value ?? "")}
          onChange={(event) => onChange(event.target.value)}
        />
      </label>
    );
  }

  return (
    <label className="flex flex-col gap-1 text-sm">
      {label}
      <Input
        data-testid={testId}
        aria-label={field.title}
        disabled={disabled}
        value={String(value ?? "")}
        onChange={(event) =>
          onChange(
            event.target.value === "" && field.nullable
              ? null
              : event.target.value,
          )
        }
      />
    </label>
  );
}
