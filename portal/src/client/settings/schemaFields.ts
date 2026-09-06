/**
 * The settings forms are built from the runtime's own schema.
 *
 * `docs/reference/tenant-config.md`: "Pydantic models in
 * `runtime/spatalk/tenants/schema.py` are the single source of truth; the
 * portal's settings forms are generated from the JSON schema the runtime serves
 * at `GET /internal/schema/tenant-config`. A field added anywhere else is a
 * defect." So this module reads that document and hands each tab its fields —
 * the portal keeps no second copy of what a tenant may configure.
 */

export type FieldKind =
  | "string"
  | "integer"
  | "number"
  | "boolean"
  | "enum"
  | "unsupported";

export type SchemaField = {
  name: string;
  title: string;
  description?: string;
  kind: FieldKind;
  options?: string[];
  required: boolean;
  nullable: boolean;
  /** Pydantic's `max_length`, so a control can stop at the runtime's bound. */
  maxLength?: number;
};

type Json = Record<string, any>;

/** The tenant configuration a form is editing: whatever the runtime last stored. */
export type Draft = Record<string, any>;

/**
 * Where a refused save pointed: the runtime's `loc`, as strings, with the
 * request wrapper dropped — `["faq", "2", "answer"]` for the third row's
 * answer. `SettingsPage` lists them above the form; a tab marks the controls.
 */
export type FieldPathError = { path: string[] };

export type TabProps = {
  config: Draft;
  /** `GET /internal/schema/tenant-config`, verbatim. */
  schema: Json;
  onChange: (next: Draft) => void;
  disabled: boolean;
  /** What the last save was refused for, if anything. */
  errors?: FieldPathError[];
};

/**
 * Whether a refused save named this path. A field is marked when an error
 * points at it or at anything inside it, and when an error points at a
 * container above it: a row whose answer was refused is a refused row, and
 * every span of a refused day is a refused span.
 */
export function invalidAt(
  errors: FieldPathError[] | undefined,
  path: (string | number)[],
): boolean {
  if (!errors) return false;
  const want = path.map(String);
  return errors.some((error) => {
    const shared = Math.min(error.path.length, want.length);
    for (let index = 0; index < shared; index += 1) {
      if (error.path[index] !== want[index]) return false;
    }
    return true;
  });
}

/** The object schema for one pydantic model inside `$defs`. */
export function definition(schema: Json, name: string): Json | undefined {
  return schema?.["$defs"]?.[name];
}

function kindOf(node: Json): { kind: FieldKind; options?: string[] } {
  if (Array.isArray(node?.enum)) {
    return { kind: "enum", options: node.enum.map(String) };
  }
  switch (node?.type) {
    case "string":
      return { kind: "string" };
    case "integer":
      return { kind: "integer" };
    case "number":
      return { kind: "number" };
    case "boolean":
      return { kind: "boolean" };
    default:
      return { kind: "unsupported" };
  }
}

/**
 * Pydantic writes an optional value as `anyOf: [{…}, {type: "null"}]`, so the
 * shape and the nullability arrive together.
 */
function resolve(node: Json): {
  kind: FieldKind;
  options?: string[];
  nullable: boolean;
  maxLength?: number;
} {
  if (Array.isArray(node?.anyOf)) {
    const nullable = node.anyOf.some((branch: Json) => branch?.type === "null");
    const real =
      node.anyOf.find((branch: Json) => branch?.type !== "null") ?? {};
    return { ...kindOf(real), nullable, maxLength: maxLengthOf(real) };
  }
  return { ...kindOf(node), nullable: false, maxLength: maxLengthOf(node) };
}

function maxLengthOf(node: Json): number | undefined {
  return typeof node?.maxLength === "number" ? node.maxLength : undefined;
}

function fieldFrom(name: string, node: Json, required: string[]): SchemaField {
  const { kind, options, nullable, maxLength } = resolve(node ?? {});
  return {
    name,
    title: node?.title ?? name,
    description: node?.description,
    kind,
    options,
    required: required.includes(name),
    nullable,
    maxLength,
  };
}

/** Every scalar field of an object schema, in the order the model declares them. */
export function objectFields(objectSchema: Json | undefined): SchemaField[] {
  const properties: Json = objectSchema?.properties ?? {};
  const required: string[] = objectSchema?.required ?? [];
  return Object.keys(properties).map((name) =>
    fieldFrom(name, properties[name], required),
  );
}

/** The scalar fields of one `$defs` model, e.g. `Scripts` or `Destination`. */
export function fieldsOf(schema: Json, definitionName: string): SchemaField[] {
  return objectFields(definition(schema, definitionName));
}

/** Named top-level fields of the tenant configuration itself. */
export function rootFields(schema: Json, names: string[]): SchemaField[] {
  const properties: Json = schema?.properties ?? {};
  const required: string[] = schema?.required ?? [];
  return names
    .filter((name) => properties[name] !== undefined)
    .map((name) => fieldFrom(name, properties[name], required));
}
