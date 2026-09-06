import { useId } from "react";

import { Checkbox } from "../components/ui/checkbox";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../components/ui/select";
import { Textarea } from "../components/ui/textarea";
import { type SchemaField } from "./schemaFields";

/**
 * One control, decided by the runtime's schema rather than by a hand-written
 * list here: a boolean is a checkbox, a `Literal` is a select, an int is a
 * number, everything else is text.
 *
 * Every control is the kit's — the registry's `Label`, `Input`, `Textarea`,
 * `Checkbox` and `Select` — so a form built from the schema looks like the
 * kit's own forms (`src/features/settings/profile/profile-form.tsx` in
 * `satnaing/shadcn-admin`) rather than like the browser's defaults.
 */

/**
 * Radix will not take an empty string as a value, and a nullable field has to
 * be able to say "not set", so the empty choice carries this sentinel between
 * the select and the draft. It never reaches the runtime.
 */
const UNSET = "__unset__";

export function SchemaInput({
  field,
  value,
  onChange,
  disabled,
  testId,
  long,
  invalid,
}: {
  field: SchemaField;
  value: unknown;
  onChange: (value: unknown) => void;
  disabled?: boolean;
  testId?: string;
  /** Render a string on several lines: knowledge and the fixed scripts. */
  long?: boolean;
  /** The last save was refused for this field: the kit paints it destructive. */
  invalid?: boolean;
}) {
  const id = useId();
  const ariaInvalid = invalid ? true : undefined;
  const label = (
    <Label htmlFor={id} className="text-muted-foreground text-xs uppercase">
      {field.title}
      {field.required && " *"}
    </Label>
  );

  if (field.kind === "boolean") {
    return (
      <div className="flex items-center gap-2">
        <Checkbox
          id={id}
          data-testid={testId}
          aria-invalid={ariaInvalid}
          disabled={disabled}
          checked={Boolean(value)}
          onCheckedChange={(checked) => onChange(checked === true)}
        />
        {label}
      </div>
    );
  }

  if (field.kind === "enum") {
    const current = String(value ?? "");
    return (
      <div className="flex flex-col gap-1.5">
        {label}
        <Select
          disabled={disabled}
          value={current === "" ? UNSET : current}
          onValueChange={(next) => onChange(next === UNSET ? null : next)}
        >
          <SelectTrigger
            id={id}
            data-testid={testId}
            aria-label={field.title}
            aria-invalid={ariaInvalid}
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {field.nullable && <SelectItem value={UNSET}>not set</SelectItem>}
            {(field.options ?? []).map((option) => (
              <SelectItem key={option} value={option}>
                {option}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    );
  }

  if (field.kind === "integer" || field.kind === "number") {
    return (
      <div className="flex flex-col gap-1.5">
        {label}
        <Input
          id={id}
          type="number"
          data-testid={testId}
          aria-label={field.title}
          aria-invalid={ariaInvalid}
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
      </div>
    );
  }

  if (long) {
    return (
      <div className="flex flex-col gap-1.5">
        {label}
        <Textarea
          id={id}
          rows={3}
          data-testid={testId}
          aria-label={field.title}
          aria-invalid={ariaInvalid}
          maxLength={field.maxLength}
          disabled={disabled}
          value={String(value ?? "")}
          onChange={(event) => onChange(event.target.value)}
        />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-1.5">
      {label}
      <Input
        id={id}
        data-testid={testId}
        aria-label={field.title}
        aria-invalid={ariaInvalid}
        maxLength={field.maxLength}
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
    </div>
  );
}
