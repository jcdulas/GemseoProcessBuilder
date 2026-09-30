import assert from "node:assert/strict";
import { test } from "node:test";

import { formatExpressions, parseExpressionLines } from "../../gemseo_process_builder/static/js/lib/expressions.js";

test("expression lines are parsed", () => {
  assert.deepEqual(parseExpressionLines("y = x**2\n\n# comment\nz=sin(x) + y2"), {
    expressions: { y: "x**2", z: "sin(x) + y2" },
    errors: [],
  });
});

test("invalid lines are reported", () => {
  const { errors } = parseExpressionLines("x**2\n2y = x\nz =\nw = 1\nw = 2");
  assert.equal(errors.length, 4);
  assert.match(errors[0], /Line 1/);
  assert.match(errors[3], /defined twice/);
});

test("expressions are formatted back", () => {
  assert.equal(formatExpressions({ y: "x**2", z: "1" }), "y = x**2\nz = 1");
  assert.equal(formatExpressions(undefined), "");
});
