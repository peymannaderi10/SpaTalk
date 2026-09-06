import { IconPlus, IconTrash } from "@tabler/icons-react";
import { useState } from "react";

import { EmptyState } from "../components/empty-state";
import { Button } from "../components/ui/button";
import { Card, CardContent } from "../components/ui/card";
import { displayCategory, uniqueServiceId } from "./catalog";
import { fieldsOf, invalidAt, type Draft, type TabProps } from "./schemaFields";
import { SchemaInput } from "./SchemaInput";

/**
 * The catalog. The ids here become the only services a tool call may name, so
 * a treatment that is not on this list cannot be booked, quoted or linked to.
 *
 * The id is the runtime's closed key — the tool enums, `items.service_id`, the
 * booking links — so it must exist and must never change once a service has
 * one, and the clinic never sees it. A row added here takes its id from its
 * name as the name is typed, made unique among the tenant's ids; the id
 * freezes when the person moves on from the name, and a saved service keeps
 * its id whatever it is renamed to.
 *
 * A category is stored lowercase, because the runtime matches categories
 * lowercase, and read with a capital: the control shows `displayCategory` of
 * the draft and writes the draft lowercase, so the saved config never carries
 * a capital and the person never sees the lack of one.
 *
 * Each service is one of the kit's cards with the schema's fields inside it.
 */
export function ServicesTab({
  config,
  schema,
  onChange,
  disabled,
  errors,
}: TabProps) {
  const allFields = fieldsOf(schema, "Service");
  const fields = allFields.filter((field) => field.name !== "id");
  const services: Draft[] = config.services ?? [];

  // The rows added on this page whose id still follows their name, by index.
  // A row leaves the set when the person moves on from its name; clicking
  // Save moves on from it too, so a saved row is never in it.
  const [naming, setNaming] = useState<number[]>([]);

  function setServices(next: Draft[]) {
    onChange({ ...config, services: next });
  }

  function update(index: number, name: string, value: unknown) {
    setServices(
      services.map((entry, i) => {
        if (i !== index) return entry;
        const stored =
          name === "category" ? String(value ?? "").toLowerCase() : value;
        const changed = { ...entry, [name]: stored };
        if (name === "name" && naming.includes(index)) {
          const taken = services
            .filter((_, j) => j !== index)
            .map((other) => String(other.id ?? ""));
          changed.id = uniqueServiceId(String(value ?? ""), taken);
        }
        return changed;
      }),
    );
  }

  function settle(index: number) {
    setNaming(naming.filter((i) => i !== index));
  }

  function remove(index: number) {
    setServices(services.filter((_, i) => i !== index));
    setNaming(
      naming.filter((i) => i !== index).map((i) => (i > index ? i - 1 : i)),
    );
  }

  function add() {
    setNaming([...naming, services.length]);
    setServices([
      ...services,
      Object.fromEntries(
        allFields.map((field) => [
          field.name,
          field.kind === "boolean" ? false : "",
        ]),
      ),
    ]);
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
                  value={
                    field.name === "category"
                      ? displayCategory(String(service.category ?? ""))
                      : service[field.name]
                  }
                  disabled={disabled}
                  long={field.name === "description"}
                  invalid={invalidAt(errors, ["services", index, field.name])}
                  testId={`service-${index}-${field.name}`}
                  onChange={(value) => update(index, field.name, value)}
                  onBlur={
                    field.name === "name" ? () => settle(index) : undefined
                  }
                />
              ))}
            </div>
            {!disabled && (
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => remove(index)}
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
          onClick={add}
        >
          <IconPlus className="size-4" />
          Add a service
        </Button>
      )}
    </div>
  );
}
