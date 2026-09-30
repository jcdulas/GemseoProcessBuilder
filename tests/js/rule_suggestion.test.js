import assert from "node:assert/strict";
import { test } from "node:test";

import { columnOf, escapeRegex, sameValue, suggestRules } from "../../gemseo_process_builder/static/js/lib/rule_suggestion.js";

const OUTPUT = [
  "Solver 2.1",
  "f = 1.125",
  "Max stress:   294.15  MPa",
  "RESULTS",
  "  iter  value",
  "  1     3.0",
  "  2     4.0",
  "",
  "done",
].join("\n");

const offset = (text) => OUTPUT.indexOf(text);
const kinds = (suggestions) => suggestions.map(({ rule }) => rule.kind);

test("a key = value line", () => {
  const suggestions = suggestRules(OUTPUT, offset("1.125") + 2);
  assert.deepEqual(suggestions[0].rule, { kind: "key_value", key: "f" });
  assert.deepEqual(kinds(suggestions), ["key_value", "marker", "marker", "regex", "regex"]);
  assert.deepEqual(suggestions[1].rule, { kind: "marker", marker: "f =", line: 0, column: 2 });
  assert.deepEqual(suggestions[2].rule, { kind: "marker", marker: "Solver 2.1", line: 1, column: 2 });
});

test("a value after a label, and a regular expression", () => {
  const start = offset("294.15");
  const suggestions = suggestRules(OUTPUT, start, start + 6);
  // The unit after the value rules out "Max stress: value".
  assert.deepEqual(suggestions[0].rule, { kind: "marker", marker: "Max stress:", line: 0, column: 2 });
  assert.equal(suggestRules("a: 2", 3)[0].rule.separator, ":");
  const regex = suggestions.find(({ rule }) => rule.kind === "regex").rule;
  assert.equal(regex.pattern, "Max\\s+stress:\\s*([-+]?(?:\\d+\\.?\\d*|\\.\\d+)(?:[eEdD][-+]?\\d+)?)");
  const match = OUTPUT.match(new RegExp(regex.pattern));
  assert.equal(match[1], "294.15");
});

test("a column of values", () => {
  const start = offset("3.0");
  const suggestions = suggestRules(OUTPUT, start, offset("4.0") + 3);
  assert.deepEqual(suggestions, [
    { label: 'Table under "iter  value"', rule: { kind: "table", marker: "iter  value", column: 1 } },
  ]);
  assert.deepEqual(suggestRules("A\n1\n2\nB", 2, 5)[0].rule, { kind: "table", marker: "A", column: 0, end: "B" });
  assert.deepEqual(suggestRules("1\n2\n", 0, 3), []);
});

test("nothing to suggest away from numbers", () => {
  assert.deepEqual(suggestRules(OUTPUT, offset("done")), []);
});

test("helpers", () => {
  assert.equal(columnOf("  a  b c", 7), 2);
  assert.equal(escapeRegex("a (b)  c."), "a\\s+\\(b\\)\\s+c\\.");
  assert.ok(sameValue(1.125, 1.125));
  assert.ok(sameValue([3, 4], [3, 4]));
  assert.ok(!sameValue([3], [3, 4]));
  assert.ok(!sameValue(null, 1));
});
