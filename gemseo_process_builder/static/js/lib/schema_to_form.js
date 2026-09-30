// @ts-check
// From the JSON Schema of GEMSEO settings (Pydantic models) to a form description.

/**
 * @typedef {"number" | "integer" | "boolean" | "string" | "enum" | "array" | "object" | "json"} FieldType
 *
 * @typedef {object} FormField
 * @property {string} name
 * @property {string} label
 * @property {string} description - Plain text, for tooltips.
 * @property {FieldType} type
 * @property {boolean} nullable - Whether an empty value means ``None``.
 * @property {any} default
 * @property {boolean} required
 * @property {{minimum?: number, maximum?: number, exclusiveMinimum?: number, exclusiveMaximum?: number}} bounds
 * @property {any[]} options - The values of an enumeration.
 * @property {FieldType | null} itemType - The type of the items of an array.
 * @property {FormField[]} fields - The fields of an object.
 *
 * @typedef {object} Form
 * @property {FormField[]} essential - Shown first.
 * @property {FormField[]} advanced - Shown in the "Advanced" section.
 *
 * @typedef {object} EssentialTable
 * @property {string[]} hidden - Fields never shown (progress bars, callbacks…).
 * @property {Record<string, string[]>} [hiddenByKind] - Fields never shown for a kind.
 * @property {Record<string, Record<string, string[]>>} kinds - Essential fields by kind, then by algorithm name or "*".
 */

/**
 * Resolve a ``$ref`` to the definitions of the schema.
 *
 * @param {any} schema
 * @param {Record<string, any>} defs
 */
function resolve(schema, defs) {
  const ref = schema?.$ref;
  if (typeof ref === "string" && ref.startsWith("#/$defs/")) {
    return { ...defs[ref.slice(8)], ...Object.fromEntries(Object.entries(schema).filter(([key]) => key !== "$ref")) };
  }
  return schema ?? {};
}

/**
 * Turn Sphinx markup into plain text: ``:class:`.MDAChain``` becomes ``MDAChain``.
 *
 * @param {string | undefined} text
 */
export function plainDescription(text) {
  return (text ?? "")
    .replace(/:[a-z]+:`~?\.?([^`]+)`/g, "$1")
    .replace(/``([^`]+)``/g, "$1")
    .replace(/(?<!\n)\n(?!\n)/g, " ")
    .replace(/[ \t]+/g, " ")
    .trim();
}

/**
 * "max_iter" becomes "Max iter".
 *
 * @param {string} name
 */
export function labelOf(name) {
  const words = name.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/**
 * The type of a (resolved) schema and whether ``null`` is allowed.
 *
 * @param {any} schema
 * @param {Record<string, any>} defs
 * @returns {{type: FieldType, nullable: boolean, schema: any}}
 */
function typeOf(schema, defs) {
  const resolved = resolve(schema, defs);
  const variants = resolved.anyOf ?? resolved.oneOf;
  if (Array.isArray(variants)) {
    const others = variants.map((variant) => resolve(variant, defs)).filter((variant) => variant.type !== "null");
    const nullable = others.length < variants.length;
    if (others.length === 1) {
      return { ...typeOf(others[0], defs), nullable };
    }
    const object = others.find((variant) => variant.properties);
    return object ? { type: "object", nullable, schema: object } : { type: "json", nullable, schema: resolved };
  }
  if (Array.isArray(resolved.enum)) {
    return { type: "enum", nullable: resolved.enum.includes(null), schema: resolved };
  }
  if ("const" in resolved) {
    return { type: "enum", nullable: false, schema: { ...resolved, enum: [resolved.const] } };
  }
  const type = resolved.type;
  if (type === "object" && !resolved.properties) {
    return { type: "json", nullable: false, schema: resolved };
  }
  if (["number", "integer", "boolean", "string", "array", "object"].includes(type)) {
    return { type, nullable: false, schema: resolved };
  }
  return { type: "json", nullable: false, schema: resolved };
}

/**
 * Describe one property of a schema.
 *
 * @param {string} name
 * @param {any} property
 * @param {Record<string, any>} defs
 * @param {Set<string>} required
 * @returns {FormField}
 */
function describeField(name, property, defs, required) {
  const { type, nullable, schema } = typeOf(property, defs);
  const bounds = Object.fromEntries(
    ["minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum"]
      .filter((key) => typeof schema[key] === "number")
      .map((key) => [key, schema[key]]),
  );
  const items = type === "array" ? typeOf(schema.items ?? {}, defs) : null;
  return {
    name,
    label: labelOf(name),
    description: plainDescription(property.description ?? schema.description),
    type,
    nullable,
    default: property.default ?? null,
    required: required.has(name),
    bounds,
    options: type === "enum" ? schema.enum.filter((/** @type {any} */ value) => value !== null) : [],
    itemType: items ? items.type : null,
    fields: type === "object" ? fieldsOf(schema, defs) : [],
  };
}

/**
 * @param {any} schema
 * @param {Record<string, any>} defs
 * @returns {FormField[]}
 */
function fieldsOf(schema, defs) {
  const required = new Set(schema.required ?? []);
  return Object.entries(schema.properties ?? {}).map(([name, property]) => describeField(name, property, defs, required));
}

/**
 * The essential fields of an algorithm: its own list, else the list of its kind.
 *
 * @param {EssentialTable} table
 * @param {string} kind
 * @param {string} name
 */
export function essentialNames(table, kind, name) {
  const lists = table.kinds[kind] ?? {};
  return lists[name] ?? lists["*"] ?? [];
}

/**
 * Build the form of a settings schema.
 *
 * Required fields are always essential; hidden fields are left out.
 *
 * @param {any} schema
 * @param {string[]} essential - Names of the fields to show first.
 * @param {string[]} [hidden]
 * @returns {Form}
 */
export function schemaToForm(schema, essential, hidden = []) {
  const defs = schema.$defs ?? {};
  const fields = fieldsOf(schema, defs).filter((field) => !hidden.includes(field.name));
  const isEssential = (/** @type {FormField} */ field) => field.required || essential.includes(field.name);
  const rank = (/** @type {FormField} */ field) => {
    const index = essential.indexOf(field.name);
    return index < 0 ? essential.length : index;
  };
  return {
    essential: fields.filter(isEssential).sort((a, b) => rank(a) - rank(b)),
    advanced: fields.filter((field) => !isEssential(field)),
  };
}

/**
 * The text shown in the input of a field.
 *
 * @param {FormField} field
 * @param {any} value
 */
export function formatFieldValue(field, value) {
  if (value === null || value === undefined) {
    return "";
  }
  if (field.type === "array" && Array.isArray(value) && field.itemType !== "json" && field.itemType !== "object") {
    return value.join(", ");
  }
  if (field.type === "json" || field.type === "object" || field.type === "array") {
    return JSON.stringify(value);
  }
  return String(value);
}

/**
 * @param {FormField} field
 * @param {number} value
 * @returns {string | null}
 */
function boundError(field, value) {
  const { minimum, maximum, exclusiveMinimum, exclusiveMaximum } = field.bounds;
  if (minimum !== undefined && value < minimum) {
    return `The value must be at least ${minimum}.`;
  }
  if (maximum !== undefined && value > maximum) {
    return `The value must be at most ${maximum}.`;
  }
  if (exclusiveMinimum !== undefined && value <= exclusiveMinimum) {
    return `The value must be greater than ${exclusiveMinimum}.`;
  }
  if (exclusiveMaximum !== undefined && value >= exclusiveMaximum) {
    return `The value must be less than ${exclusiveMaximum}.`;
  }
  return null;
}

/**
 * @param {string} text
 * @param {"number" | "integer"} type
 * @returns {{value: any, error: string | null}}
 */
function parseNumber(text, type) {
  const value = Number(text);
  if (text === "" || Number.isNaN(value)) {
    return { value: null, error: "Enter a number." };
  }
  if (type === "integer" && !Number.isInteger(value)) {
    return { value: null, error: "Enter a whole number." };
  }
  return { value, error: null };
}

/**
 * Read the text typed in the input of a field.
 *
 * An empty text gives ``null`` (``None``) for nullable fields and the default
 * value otherwise.
 *
 * @param {FormField} field
 * @param {string} text
 * @returns {{value: any, error: string | null}}
 */
export function parseFieldValue(field, text) {
  const trimmed = text.trim();
  if (trimmed === "") {
    return field.nullable || field.type === "string"
      ? { value: field.type === "string" && !field.nullable ? "" : null, error: null }
      : { value: field.default, error: null };
  }
  if (field.type === "number" || field.type === "integer") {
    const parsed = parseNumber(trimmed, field.type);
    return parsed.error ? parsed : { value: parsed.value, error: boundError(field, parsed.value) };
  }
  if (field.type === "boolean") {
    return { value: ["true", "1", "yes"].includes(trimmed.toLowerCase()), error: null };
  }
  if (field.type === "enum") {
    const option = field.options.find((candidate) => String(candidate) === trimmed);
    return option === undefined ? { value: null, error: "Choose one of the values." } : { value: option, error: null };
  }
  if (field.type === "array" && (field.itemType === "number" || field.itemType === "integer" || field.itemType === "string")) {
    const parts = trimmed.split(/[\s,;]+/).filter(Boolean);
    if (field.itemType === "string") {
      return { value: parts, error: null };
    }
    const values = parts.map((part) => parseNumber(part, /** @type {"number" | "integer"} */ (field.itemType)));
    const failed = values.find((item) => item.error);
    return failed ? { value: null, error: failed.error } : { value: values.map((item) => item.value), error: null };
  }
  if (field.type === "string") {
    return { value: trimmed, error: null };
  }
  try {
    return { value: JSON.parse(trimmed), error: null };
  } catch {
    return { value: null, error: "Enter a JSON value, like {\"key\": 1} or [1, 2]." };
  }
}

/**
 * The settings with one field changed; a value equal to the default is removed,
 * so projects only store what the user changed.
 *
 * @param {Record<string, any>} settings
 * @param {FormField} field
 * @param {any} value
 */
export function withSetting(settings, field, value) {
  const next = { ...settings };
  if (JSON.stringify(value) === JSON.stringify(field.default)) {
    delete next[field.name];
  } else {
    next[field.name] = value;
  }
  return next;
}
