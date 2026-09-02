import { Button } from "../components/ui/button";
import { fieldsOf, type Draft, type TabProps } from "./schemaFields";
import { SchemaInput } from "./SchemaInput";

/**
 * The catalog. The ids here become the only services a tool call may name, so
 * a treatment that is not on this list cannot be booked, quoted or linked to.
 */
export function ServicesTab({
  config,
  schema,
  onChange,
  disabled,
}: TabProps) {
  const fields = fieldsOf(schema, "Service");
  const services: Draft[] = config.services ?? [];

  function setServices(next: Draft[]) {
    onChange({ ...config, services: next });
  }

  return (
    <div className="space-y-4">
      {services.map((service, index) => (
        <div
          key={index}
          className="border-border rounded-lg border p-4"
          data-testid={`service-${index}`}
        >
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            {fields.map((field) => (
              <SchemaInput
                key={field.name}
                field={field}
                value={service[field.name]}
                disabled={disabled}
                long={field.name === "description"}
                testId={`service-${index}-${field.name}`}
                onChange={(value) =>
                  setServices(
                    services.map((entry, i) =>
                      i === index ? { ...entry, [field.name]: value } : entry,
                    ),
                  )
                }
              />
            ))}
          </div>
          {!disabled && (
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="mt-3"
              onClick={() =>
                setServices(services.filter((_, i) => i !== index))
              }
            >
              Remove this service
            </Button>
          )}
        </div>
      ))}

      {!disabled && (
        <Button
          type="button"
          variant="outline"
          size="sm"
          data-testid="add-service"
          onClick={() =>
            setServices([
              ...services,
              Object.fromEntries(
                fields.map((field) => [
                  field.name,
                  field.kind === "boolean" ? false : "",
                ]),
              ),
            ])
          }
        >
          Add a service
        </Button>
      )}
    </div>
  );
}
