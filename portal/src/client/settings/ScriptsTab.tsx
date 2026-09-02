import { fieldsOf, type TabProps } from "./schemaFields";
import { SchemaInput } from "./SchemaInput";

/**
 * The fixed wording. Every sentence the system can say that was not written by
 * the model lives here, one field per script, generated from the runtime's own
 * `Scripts` model so a script added there appears here without an edit.
 *
 * The runtime refuses wording that claims something was booked, confirmed or
 * scheduled, and refuses a clinical script that has lost its emergency
 * sentence: a save that breaks either comes back named.
 */
export function ScriptsTab({ config, schema, onChange, disabled }: TabProps) {
  const fields = fieldsOf(schema, "Scripts");
  const scripts: Record<string, unknown> = config.scripts ?? {};

  return (
    <div className="space-y-4">
      <p className="text-muted-foreground text-sm">
        Placeholders: {"{name}"} the business, {"{confirm_by}"} the promised
        time, {"{service}"}, {"{url}"}, {"{booking_url}"}, {"{phone}"},{" "}
        {"{sms_number}"}. A script that mentions the team keeps{" "}
        {"{confirm_by}"}, so the caller always hears a time.
      </p>
      {fields.map((field) => (
        <SchemaInput
          key={field.name}
          field={field}
          long
          value={scripts[field.name]}
          disabled={disabled}
          testId={`script-${field.name}`}
          onChange={(value) =>
            onChange({
              ...config,
              scripts: { ...scripts, [field.name]: value },
            })
          }
        />
      ))}
    </div>
  );
}
