import { IconPlus, IconTrash } from "@tabler/icons-react";

import { EmptyState } from "../components/empty-state";
import { Button } from "../components/ui/button";
import { Card, CardContent } from "../components/ui/card";
import { fieldsOf, type Draft, type TabProps } from "./schemaFields";
import { SchemaInput } from "./SchemaInput";

/**
 * The catalog. The ids here become the only services a tool call may name, so
 * a treatment that is not on this list cannot be booked, quoted or linked to.
 *
 * Each service is one of the kit's cards with the schema's fields inside it.
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
      {services.length === 0 && (
        <EmptyState
          title="No service yet"
          description="Until a service is on this list the assistant cannot name it, quote it or link to it."
          icon={IconPlus}
          testId="services-empty"
        />
      )}

      {services.map((service, index) => (
        <Card key={index} data-testid={`service-${index}`}>
          <CardContent className="space-y-3">
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
                onClick={() =>
                  setServices(services.filter((_, i) => i !== index))
                }
              >
                <IconTrash className="size-4" />
                Remove this service
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
          <IconPlus className="size-4" />
          Add a service
        </Button>
      )}
    </div>
  );
}
