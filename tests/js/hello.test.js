import assert from "node:assert/strict";
import { test } from "node:test";

import { greeting } from "../../gemseo_process_builder/static/js/lib/hello.js";

test("greeting names who says hello", () => {
  assert.equal(greeting("d3"), "Hello from d3");
});
