import {
  IconChevronDown,
  IconPlus,
  IconTrash,
  IconUsers,
} from "@tabler/icons-react";

import { EmptyState } from "../components/empty-state";
import { Button } from "../components/ui/button";
import { Card, CardContent } from "../components/ui/card";
import { Checkbox } from "../components/ui/checkbox";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "../components/ui/collapsible";
import { Label } from "../components/ui/label";
import { displayCategory } from "./catalog";
import { fieldsOf, invalidAt, type Draft, type TabProps } from "./schemaFields";
import { SchemaInput } from "./SchemaInput";

/**
 * Who a caller may ask for by name. `config.team` is the closed vocabulary
 * behind `items.practitioner`: the model may only return a name on this list,
 * or "any", and the ledger nulls anything else (CLAUDE.md non-negotiable 2).
 * A role is written where the clinic states one publicly; it is never spoken
 * as a claim about qualifications.
 *
 * Each person carries the services they perform, by `services[].id`, and an
 * empty list means every service. The slot engine reads it for "unfortunately
 * Helen doesn't do X", so the tick boxes are the tenant's own catalog, grouped
 * the way the Services page groups it, and nothing off that page can be
 * ticked.
 *
 * A catalog of a dozen treatments times a team of six is too many boxes to
 * read, so each category is one bar (the kit's `Collapsible`, shut until
 * opened): the category, how many of its services this person does, and a
 * select-all box that ticks or clears the whole category without opening it.
 * The individual boxes are inside.
 *
 * Name and role are the schema's fields; the services list is a shape
 * `SchemaInput` has no control for, so it is drawn here as the kit's
 * checkboxes under their labels.
 */
export function TeamTab({
  config,
  schema,
  onChange,
  disabled,
  errors,
}: TabProps) {
  const fields = fieldsOf(schema, "TeamMember").filter(
    (field) => field.kind !== "unsupported",
  );
  const team: Draft[] = config.team ?? [];
  const catalog = serviceGroups(config.services ?? []);

  function setTeam(next: Draft[]) {
    onChange({ ...config, team: next });
  }

  function setMember(index: number, patch: Draft) {
    setTeam(
      team.map((entry, i) => (i === index ? { ...entry, ...patch } : entry)),
    );
  }

  /** Tick or clear `ids` for one member, keeping the order already stored. */
  function tick(index: number, ids: string[], on: boolean) {
    const current = performed(team[index]);
    const services = on
      ? [...current, ...ids.filter((id) => !current.includes(id))]
      : current.filter((id) => !ids.includes(id));
    setMember(index, { services });
  }

  return (
    <div className="space-y-4">
      {team.length === 0 && (
        <EmptyState
          title="Nobody on the team yet"
          description="Until someone is listed here, the assistant has no name to record when a caller asks for a particular person."
          icon={IconUsers}
          testId="team-empty"
        />
      )}

      {team.map((member, index) => {
        const selected = performed(member);
        const servicesInvalid = invalidAt(errors, ["team", index, "services"]);
        return (
          <Card key={index} data-testid={`team-${index}`}>
            <CardContent className="space-y-4">
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                {fields.map((field) => (
                  <SchemaInput
                    key={field.name}
                    field={field}
                    value={member[field.name]}
                    disabled={disabled}
                    invalid={invalidAt(errors, ["team", index, field.name])}
                    testId={`team-${index}-${field.name}`}
                    onChange={(value) =>
                      setMember(index, { [field.name]: value })
                    }
                  />
                ))}
              </div>

              <div className="space-y-3">
                <div className="flex flex-col gap-1">
                  <span className="text-muted-foreground text-xs uppercase">
                    Services
                  </span>
                  <p className="text-muted-foreground text-sm">
                    Leave every service unticked for someone who does
                    everything.
                  </p>
                </div>

                {catalog.length === 0 ? (
                  <p
                    className="text-muted-foreground text-sm"
                    data-testid={`team-${index}-no-services`}
                  >
                    There is no service to tick until one is on the Services
                    page.
                  </p>
                ) : (
                  catalog.map((group) => (
                    <CategoryBar
                      key={group.category}
                      group={group}
                      selected={selected}
                      disabled={disabled}
                      invalid={servicesInvalid}
                      testId={`team-${index}-category-${group.category}`}
                      onTick={(ids, on) => tick(index, ids, on)}
                      boxId={(serviceId) =>
                        `team-${index}-service-${serviceId}`
                      }
                    />
                  ))
                )}
              </div>

              {!disabled && (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  data-testid={`remove-team-${index}`}
                  onClick={() => setTeam(team.filter((_, i) => i !== index))}
                >
                  <IconTrash className="size-4" />
                  Remove this person
                </Button>
              )}
            </CardContent>
          </Card>
        );
      })}

      {!disabled && (
        <Button
          type="button"
          variant="outline"
          size="sm"
          data-testid="add-team-member"
          onClick={() =>
            setTeam([
              ...team,
              {
                ...Object.fromEntries(
                  fields.map((field) => [
                    field.name,
                    field.kind === "boolean" ? false : "",
                  ]),
                ),
                services: [],
              },
            ])
          }
        >
          <IconPlus className="size-4" />
          Add a person
        </Button>
      )}
    </div>
  );
}

/**
 * One category of the catalog for one person: a bar that says the category
 * and "n of m", with a box that ticks or clears the whole category, and the
 * services themselves behind the bar. The bar's box is mixed while some but
 * not all of the category is ticked; a click on it then ticks the rest, which
 * is what the kit's checkbox does with a mixed state.
 */
function CategoryBar({
  group,
  selected,
  disabled,
  invalid,
  testId,
  onTick,
  boxId,
}: {
  group: ServiceGroup;
  selected: string[];
  disabled: boolean;
  invalid: boolean;
  testId: string;
  onTick: (ids: string[], on: boolean) => void;
  boxId: (serviceId: string) => string;
}) {
  const ids = group.services.map((service) => service.id);
  const ticked = ids.filter((id) => selected.includes(id)).length;
  const state: boolean | "indeterminate" =
    ticked === 0 ? false : ticked === ids.length ? true : "indeterminate";

  return (
    <Collapsible>
      <div
        className="border-input flex items-center gap-3 rounded-md border px-3 py-2"
        data-testid={`${testId}-bar`}
      >
        <Checkbox
          data-testid={`${testId}-all`}
          aria-label={`Select all ${group.category}`}
          disabled={disabled}
          aria-invalid={invalid || undefined}
          checked={state}
          onCheckedChange={(checked) => onTick(ids, checked === true)}
        />
        <CollapsibleTrigger asChild>
          <button
            type="button"
            data-testid={`${testId}-toggle`}
            className="group flex flex-1 items-center justify-between gap-2 text-left text-sm"
          >
            <span className="font-medium">
              {displayCategory(group.category)}
            </span>
            <span className="text-muted-foreground flex items-center gap-2">
              {ticked} of {ids.length}
              <IconChevronDown className="size-4 transition-transform group-data-[state=open]:rotate-180" />
            </span>
          </button>
        </CollapsibleTrigger>
      </div>
      <CollapsibleContent>
        <div className="grid grid-cols-1 gap-1.5 px-3 py-2 sm:grid-cols-2 lg:grid-cols-3">
          {group.services.map((service) => {
            const id = boxId(service.id);
            return (
              <div key={service.id} className="flex items-center gap-2">
                <Checkbox
                  id={id}
                  data-testid={id}
                  disabled={disabled}
                  aria-invalid={invalid || undefined}
                  checked={selected.includes(service.id)}
                  onCheckedChange={(checked) =>
                    onTick([service.id], checked === true)
                  }
                />
                <Label htmlFor={id} className="font-normal">
                  {service.name}
                </Label>
              </div>
            );
          })}
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}

/** The ids a member performs, as stored; anything that is not a list is nothing. */
function performed(member: Draft): string[] {
  return Array.isArray(member?.services) ? member.services.map(String) : [];
}

type ServiceGroup = {
  category: string;
  services: { id: string; name: string }[];
};

/**
 * The tenant's catalog by category, in the order the Services page lists it.
 * A service that has no id yet cannot be ticked, because the list stores ids,
 * so it is left out until it is saved with one.
 */
function serviceGroups(services: Draft[]): ServiceGroup[] {
  const groups = new Map<string, ServiceGroup["services"]>();
  for (const service of services) {
    const id = String(service?.id ?? "").trim();
    if (!id) continue;
    const category = String(service?.category ?? "").trim() || "other";
    const name = String(service?.name ?? "").trim() || id;
    const group = groups.get(category) ?? [];
    group.push({ id, name });
    groups.set(category, group);
  }
  return [...groups].map(([category, entries]) => ({
    category,
    services: entries,
  }));
}
