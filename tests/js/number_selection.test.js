import assert from "node:assert/strict";
import { test } from "node:test";

import {
  formatNumber,
  guessFormat,
  markerText,
  markerValueText,
  numberAt,
  numberTokens,
  parseNumber,
  renameMarkers,
  replaceByMarker,
  selectionNumbers,
  templateMarkers,
} from "../../gemseo_process_builder/static/js/lib/number_selection.js";

test("numbers, also in Fortran notation", () => {
  assert.equal(parseNumber("1.5D+03"), 1500);
  assert.equal(parseNumber(" -2e-1 "), -0.2);
  assert.ok(Number.isNaN(parseNumber("x1")));
  const tokens = numberTokens("x1 = 2.5, run_3 -4 7.0d0");
  assert.deepEqual(
    tokens.map((token) => token.text),
    ["2.5", "-4", "7.0d0"],
  );
  assert.equal(tokens[2].value, 7);
  assert.equal(numberAt("a = 12.5", 6).value, 12.5);
  assert.equal(numberAt("a = 12.5", 1), null);
});

test("formats keep the layout of the file", () => {
  assert.equal(guessFormat("1.234560e+00"), ".6e");
  assert.equal(guessFormat("1.5D+03"), ".1E");
  assert.equal(guessFormat("    3.1416"), "10.4f");
  assert.equal(guessFormat("42"), ".0f");
  assert.equal(markerText("x", ".6e"), "{{x:.6e}}");
  assert.equal(markerText("x"), "{{x}}");
});

test("selections of vectors", () => {
  assert.deepEqual(selectionNumbers("1.0 2.0 3.0"), { values: [1, 2, 3], separator: " ", format: ".1f" });
  assert.equal(selectionNumbers("1.0\n2.0").separator, "\n");
  assert.equal(selectionNumbers("1, 2").separator, ", ");
  assert.equal(selectionNumbers("x = 1"), null);
  assert.equal(selectionNumbers("   "), null);
});

test("a selection becomes a marker and an input", () => {
  const sample = "x = 0.500000\ny = 1 2 3\n";
  const scalar = replaceByMarker(sample, 4, 12, "x");
  assert.equal(scalar.text, "x = {{x:.6f}}\ny = 1 2 3\n");
  assert.deepEqual(scalar.port, { name: "x", size: 1, default: 0.5 });
  const vector = replaceByMarker(sample, 17, 22, "y", { format: "" });
  assert.equal(vector.text, "x = 0.500000\ny = {{y}}\n");
  assert.deepEqual(vector.port, { name: "y", size: 3, default: [1, 2, 3] });
  assert.equal(replaceByMarker(sample, 0, 3, "z"), null);
});

test("markers of a template", () => {
  const template = "a {{x:.6e}} b {{ y }} \\{{z}} {{x}}";
  assert.deepEqual(
    templateMarkers(template).map(({ name, format }) => [name, format]),
    [
      ["x", ".6e"],
      ["y", ""],
      ["x", ""],
    ],
  );
  assert.equal(renameMarkers(template, "x", "w"), "a {{w:.6e}} b {{ y }} \\{{z}} {{w}}");
  assert.equal(replaceByMarker("v 1.5", 2, 5, "v", { format: ".3f" }).text, "v {{v:.3f}}");
});

test("values written like Python formats", () => {
  assert.equal(formatNumber(1.5, ".6e"), "1.500000e+00");
  assert.equal(formatNumber(1500, ".1E"), "1.5E+03");
  assert.equal(formatNumber(3.14159, "10.4f"), "    3.1416");
  assert.equal(formatNumber(42, ".0f"), "42");
  assert.equal(formatNumber(0.1, ""), "0.1");
  assert.equal(markerValueText([1, 2], ".1f", ", "), "1.0, 2.0");
});
