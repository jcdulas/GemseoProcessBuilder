import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { ESSENTIAL_FIELDS } from "../../gemseo_process_builder/static/js/forms/essential_fields.js";
import {
  essentialNames,
  formatFieldValue,
  labelOf,
  parseFieldValue,
  plainDescription,
  schemaToForm,
  withSetting,
} from "../../gemseo_process_builder/static/js/lib/schema_to_form.js";

/** Schemas captured from GEMSEO 6 (``settings_schema`` in the worker). */
const schemas = Object.fromEntries(
  ["SLSQP", "COBYQA", "LHS", "MDAGaussSeidel", "MDF"].map((name) => [
    name,
    JSON.parse(readFileSync(new URL(`fixtures/schemas/${name}.json`, import.meta.url), "utf-8")),
  ]),
);
const table = ESSENTIAL_FIELDS;

/**
 * @param {string} name
 * @param {string} kind
 */
function formOf(name, kind) {
  return schemaToForm(schemas[name], essentialNames(table, kind, name), table.hidden);
}

/**
 * @param {import("../../gemseo_process_builder/static/js/lib/schema_to_form.js").Form} form
 * @param {string} name
 */
function field(form, name) {
  const found = [...form.essential, ...form.advanced].find((candidate) => candidate.name === name);
  assert.ok(found, `no field ${name}`);
  return found;
}

test("an enumeration becomes a choice", () => {
  const solver = field(formOf("MDAGaussSeidel", "mda"), "linear_solver");
  assert.equal(solver.type, "enum");
  assert.ok(solver.options.includes("DEFAULT"));
  assert.equal(solver.default, "DEFAULT");
});

test("a nullable enumeration keeps its options without null", () => {
  const optimization = field(formOf("LHS", "doe"), "optimization");
  assert.equal(optimization.type, "enum");
  assert.equal(optimization.nullable, true);
  assert.deepEqual(optimization.options, ["random-cd", "lloyd"]);
});

test("numbers keep their bounds and defaults", () => {
  const tolerance = field(formOf("MDAGaussSeidel", "mda"), "tolerance");
  assert.equal(tolerance.type, "number");
  assert.deepEqual(tolerance.bounds, { minimum: 0 });
  assert.equal(tolerance.default, 1e-6);
  const samples = field(formOf("LHS", "doe"), "n_samples");
  assert.equal(samples.type, "integer");
  assert.deepEqual(samples.bounds, { exclusiveMinimum: 0 });
});

test("a nullable integer", () => {
  const seed = field(formOf("LHS", "doe"), "seed");
  assert.equal(seed.type, "integer");
  assert.equal(seed.nullable, true);
  assert.equal(seed.default, null);
});

test("an array of strings", () => {
  const names = schemaToForm(schemas.MDF, []).advanced.find((f) => f.name === "differentiated_input_names_substitute");
  assert.equal(names?.type, "array");
  assert.equal(names?.itemType, "string");
});

test("a union with a settings model becomes a nested object", () => {
  const settings = schemaToForm(schemas.MDF, []).advanced.find((f) => f.name === "main_mda_settings");
  assert.equal(settings?.type, "object");
  assert.ok(settings?.fields.some((nested) => nested.name === "tolerance"));
});

test("essential fields come first, in the listed order; required ones always", () => {
  const slsqp = formOf("SLSQP", "optimization");
  assert.deepEqual(
    slsqp.essential.map((f) => f.name),
    ["max_iter", "ftol_rel", "ftol_abs", "xtol_rel", "xtol_abs", "ineq_tolerance", "eq_tolerance"],
  );
  assert.ok(slsqp.advanced.some((f) => f.name === "normalize_design_space"));
  const lhs = formOf("LHS", "doe");
  assert.equal(lhs.essential[0].name, "n_samples");
  assert.equal(lhs.essential[0].required, true);
});

test("hidden fields are left out", () => {
  const lhs = formOf("LHS", "doe");
  const names = [...lhs.essential, ...lhs.advanced].map((f) => f.name);
  assert.ok(!names.includes("progress_bar_data_name"));
  assert.ok(!names.includes("callbacks"));
});

test("unknown algorithms use the list of their kind", () => {
  assert.deepEqual(essentialNames(table, "doe", "Halton"), ["n_samples", "seed", "n_processes"]);
  assert.deepEqual(essentialNames(table, "surrogate", "RBF"), []);
});

test("descriptions become plain text", () => {
  assert.equal(
    plainDescription("The class of the main MDA.\n\nTypically the :class:`.MDAChain`,\nor ``MDAJacobi``."),
    "The class of the main MDA.\n\nTypically the MDAChain, or MDAJacobi.",
  );
  assert.equal(labelOf("max_mda_iter"), "Max mda iter");
});

test("parsing typed values", () => {
  const form = formOf("LHS", "doe");
  const samples = field(form, "n_samples");
  assert.deepEqual(parseFieldValue(samples, "20"), { value: 20, error: null });
  assert.equal(parseFieldValue(samples, "2.5").error, "Enter a whole number.");
  assert.equal(parseFieldValue(samples, "0").error, "The value must be greater than 0.");
  assert.deepEqual(parseFieldValue(field(form, "seed"), ""), { value: null, error: null });
  const tolerance = field(formOf("MDAGaussSeidel", "mda"), "tolerance");
  assert.deepEqual(parseFieldValue(tolerance, "1e-8"), { value: 1e-8, error: null });
  assert.deepEqual(parseFieldValue(tolerance, ""), { value: 1e-6, error: null });
  assert.equal(parseFieldValue(tolerance, "-1").error, "The value must be at least 0.");
  assert.equal(parseFieldValue(tolerance, "abc").error, "Enter a number.");
});

test("parsing arrays and JSON", () => {
  const names = schemaToForm(schemas.MDF, []).advanced.find((f) => f.name === "differentiated_input_names_substitute");
  assert.ok(names);
  assert.deepEqual(parseFieldValue(names, "x, y z").value, ["x", "y", "z"]);
  assert.equal(formatFieldValue(names, ["x", "y"]), "x, y");
  const settings = schemaToForm(schemas.MDF, []).advanced.find((f) => f.name === "main_mda_settings");
  assert.ok(settings);
  assert.deepEqual(parseFieldValue(settings, '{"tolerance": 1e-8}').value, { tolerance: 1e-8 });
  assert.match(String(parseFieldValue(settings, "{oops").error), /JSON/);
});

test("settings only keep values different from the default", () => {
  const tolerance = field(formOf("MDAGaussSeidel", "mda"), "tolerance");
  const changed = withSetting({ max_mda_iter: 50 }, tolerance, 1e-8);
  assert.deepEqual(changed, { max_mda_iter: 50, tolerance: 1e-8 });
  assert.deepEqual(withSetting(changed, tolerance, 1e-6), { max_mda_iter: 50 });
});
