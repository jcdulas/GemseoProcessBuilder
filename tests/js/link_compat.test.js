import assert from "node:assert/strict";
import { test } from "node:test";

import { conversionNotes, linkCompatibility, unitCompatibility } from "../../gemseo_process_builder/static/js/lib/link_compat.js";

test("types and sizes decide whether a link is possible", () => {
  assert.equal(linkCompatibility({ dtype: "str" }, { dtype: "float" }).ok, false);
  assert.equal(linkCompatibility({ dtype: "float", shape: [3] }, { dtype: "float", shape: [2] }).ok, false);
  assert.equal(linkCompatibility({ dtype: "int" }, { dtype: "float" }).ok, true);
});

test("unit feedback from Python's check", () => {
  assert.deepEqual(unitCompatibility(null), { ok: true, warning: "", reason: "" });
  assert.equal(unitCompatibility({ status: "incompatible", message: "m cannot be converted to s" }).ok, false);
  assert.equal(
    unitCompatibility({ status: "convert", message: "mm → m, × 0.001" }).warning,
    "The value will be converted (mm → m, × 0.001).",
  );
  assert.deepEqual(unitCompatibility({ status: "same", message: "" }), { ok: true, warning: "", reason: "" });
});

test("conversion notes of the variables of a link", () => {
  const notes = conversionNotes([
    { name: "t", unit: { status: "convert", message: "mm → m, × 0.001" }, converted: true },
    { name: "u", unit: { status: "convert", message: "degC → K, + 273.15" }, converted: false },
    { name: "v", unit: { status: "same", message: "" }, converted: false },
  ]);
  assert.deepEqual(notes, ["t: mm → m, × 0.001", "u: degC → K, + 273.15 (not converted)"]);
});
