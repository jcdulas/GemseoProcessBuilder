// @ts-check
// Forms generated from the JSON Schema of GEMSEO settings (SPEC § 8.6).
import { el } from "../components/dom.js";
import { essentialNames, formatFieldValue, parseFieldValue, schemaToForm, withSetting } from "../lib/schema_to_form.js";
import { ESSENTIAL_FIELDS } from "./essential_fields.js";

/**
 * The control editing one field.
 *
 * @param {import("../lib/schema_to_form.js").FormField} field
 * @param {any} value - The current value, ``undefined`` when it is the default.
 * @param {(text: string) => void} commit
 */
function control(field, value, commit) {
  const current = value === undefined ? field.default : value;
  if (field.type === "boolean" && !field.nullable) {
    const box = /** @type {HTMLInputElement} */ (el("input", { type: "checkbox", name: field.name, checked: Boolean(current) }));
    box.addEventListener("change", () => commit(String(box.checked)));
    return box;
  }
  if (field.type === "enum" || field.type === "boolean") {
    const options = field.type === "boolean" ? [true, false] : field.options;
    const select = /** @type {HTMLSelectElement} */ (
      el("select.select", { name: field.name }, [
        field.nullable ? el("option", { value: "", text: "(none)", selected: current === null }) : null,
        ...options.map((option) =>
          el("option", { value: String(option), text: String(option), selected: option === current }),
        ),
      ])
    );
    select.addEventListener("change", () => commit(select.value));
    return select;
  }
  const input = /** @type {HTMLInputElement} */ (
    el("input.input", {
      type: "text",
      name: field.name,
      value: value === undefined ? "" : formatFieldValue(field, value),
      placeholder: field.default === null ? (field.required ? "required" : "") : formatFieldValue(field, field.default),
    })
  );
  input.addEventListener("change", () => commit(input.value));
  return input;
}

/**
 * A form editing the settings of an algorithm, an MDA or a formulation.
 *
 * Only the settings that differ from their default are kept. Errors of the
 * typed text are shown at once; ``showErrors`` shows those found by Pydantic.
 *
 * @param {{
 *   schema: any,
 *   kind: string,
 *   name: string,
 *   settings: Record<string, any>,
 *   onChange: (settings: Record<string, any>) => Promise<unknown> | void,
 * }} options
 */
export function settingsForm({ schema, kind, name, settings, onChange }) {
  const hidden = [...ESSENTIAL_FIELDS.hidden, ...(ESSENTIAL_FIELDS.hiddenByKind?.[kind] ?? [])];
  const form = schemaToForm(schema, essentialNames(ESSENTIAL_FIELDS, kind, name), hidden);
  /** @type {Map<string, HTMLElement>} */
  const errorOf = new Map();

  /** @param {import("../lib/schema_to_form.js").FormField} field */
  const row = (field) => {
    const error = el("div.form-error");
    errorOf.set(field.name, error);
    const modified = field.name in settings;
    const commit = (/** @type {string} */ text) => {
      const parsed = parseFieldValue(field, text);
      error.textContent = parsed.error ?? "";
      if (!parsed.error) {
        onChange(withSetting(settings, field, parsed.value));
      }
    };
    return el("div.form-field", {}, [
      el(`label.form-row${modified ? ".form-modified" : ""}`, { title: field.description }, [
        el("span.form-label", { text: field.label + (field.required ? " *" : "") }),
        control(field, settings[field.name], commit),
      ]),
      error,
    ]);
  };

  const root = el("div.settings-form", {}, form.essential.map(row));
  if (form.advanced.length) {
    const changed = form.advanced.filter((field) => field.name in settings).length;
    root.append(
      el("details.form-advanced", { open: changed > 0 }, [
        el("summary", { text: `Advanced (${form.advanced.length})` }),
        ...form.advanced.map(row),
      ]),
    );
  }
  if (!form.essential.length && !form.advanced.length) {
    root.append(el("p.placeholder", { text: "No settings." }));
  }
  return {
    element: root,
    /** @param {{field: string, message: string}[]} errors */
    showErrors(errors) {
      for (const [name, element] of errorOf) {
        element.textContent = errors.filter((error) => error.field.split(".")[0] === name).map((error) => error.message).join(" ");
      }
    },
  };
}
