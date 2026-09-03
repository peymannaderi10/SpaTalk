import { IconPlus, IconTrash } from "@tabler/icons-react";

import { Button } from "../components/ui/button";
import { Card, CardContent } from "../components/ui/card";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Separator } from "../components/ui/separator";
import {
  definition,
  fieldsOf,
  objectFields,
  type Draft,
  type TabProps,
} from "./schemaFields";
import { SchemaInput } from "./SchemaInput";

/**
 * Where a tracked request goes, who owns it, and how long the team has before
 * it is a breach. A destination names an *environment variable*, never a URL:
 * secrets stay out of the configuration (CLAUDE.md non-negotiable 5).
 *
 * Three sections on the kit's form rhythm, each destination one of its cards.
 */
export function DeliveryTab({ config, schema, onChange, disabled }: TabProps) {
  const destinationFields = fieldsOf(schema, "Destination");
  const deliveryFields = objectFields(definition(schema, "Delivery")).filter(
    (field) => field.name !== "destinations" && field.kind !== "unsupported",
  );
  const escalationFields = fieldsOf(schema, "Escalation");

  const delivery: Draft = config.delivery ?? {};
  const destinations: Draft[] = delivery.destinations ?? [];
  const escalation: Draft = config.escalation ?? {};

  function setDelivery(next: Draft) {
    onChange({ ...config, delivery: { ...delivery, ...next } });
  }

  return (
    <div className="space-y-8">
      <section className="space-y-3">
        <h3 className="text-sm font-medium">Destinations</h3>
        {destinations.map((destination, index) => (
          <Card key={index} data-testid={`destination-${index}`}>
            <CardContent className="space-y-3">
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                {destinationFields.map((field) => (
                  <SchemaInput
                    key={field.name}
                    field={field}
                    value={destination[field.name]}
                    disabled={disabled}
                    testId={`destination-${index}-${field.name}`}
                    onChange={(value) =>
                      setDelivery({
                        destinations: destinations.map((entry, i) =>
                          i === index
                            ? { ...entry, [field.name]: value }
                            : entry,
                        ),
                      })
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
                    setDelivery({
                      destinations: destinations.filter((_, i) => i !== index),
                    })
                  }
                >
                  <IconTrash className="size-4" />
                  Remove this destination
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
            data-testid="add-destination"
            onClick={() =>
              setDelivery({
                destinations: [
                  ...destinations,
                  { kind: "email", address: "", urgent_only: false },
                ],
              })
            }
          >
            <IconPlus className="size-4" />
            Add a destination
          </Button>
        )}
      </section>

      <Separator />

      <section className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        {deliveryFields.map((field) => (
          <SchemaInput
            key={field.name}
            field={field}
            value={delivery[field.name]}
            disabled={disabled}
            testId={`delivery-${field.name}`}
            onChange={(value) => setDelivery({ [field.name]: value })}
          />
        ))}
        <div className="flex flex-col gap-1.5">
          <Label
            htmlFor="delivery-staff_phone_numbers"
            className="text-muted-foreground text-xs uppercase"
          >
            Staff phone numbers (E.164, comma separated)
          </Label>
          <Input
            id="delivery-staff_phone_numbers"
            data-testid="delivery-staff_phone_numbers"
            disabled={disabled}
            value={(delivery.staff_phone_numbers ?? []).join(", ")}
            onChange={(event) =>
              setDelivery({
                staff_phone_numbers: event.target.value
                  .split(",")
                  .map((part) => part.trim())
                  .filter(Boolean),
              })
            }
          />
        </div>
      </section>

      <Separator />

      <section className="space-y-3">
        <h3 className="text-sm font-medium">Escalation</h3>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          {escalationFields.map((field) => (
            <SchemaInput
              key={field.name}
              field={field}
              value={escalation[field.name]}
              disabled={disabled}
              testId={`escalation-${field.name}`}
              onChange={(value) =>
                onChange({
                  ...config,
                  escalation: { ...escalation, [field.name]: value },
                })
              }
            />
          ))}
        </div>
      </section>
    </div>
  );
}
