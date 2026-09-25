import assert from "node:assert/strict";
import { test } from "node:test";

import { LogBuffer, formatLine } from "../../gemseo_process_builder/static/js/lib/log_buffer.js";
import {
  displayShortcut,
  eventToShortcut,
  isTypingTarget,
  normalizeShortcut,
} from "../../gemseo_process_builder/static/js/lib/shortcut_keys.js";
import {
  PANEL_LIMITS,
  clampSize,
  dragSize,
  normalizeLayout,
  toggleCollapsed,
} from "../../gemseo_process_builder/static/js/lib/splitter.js";

test("sizes are clamped to the panel limits", () => {
  assert.equal(clampSize(10, PANEL_LIMITS.left), PANEL_LIMITS.left.min);
  assert.equal(clampSize(10000, PANEL_LIMITS.left), PANEL_LIMITS.left.max);
  assert.equal(clampSize(300.4, PANEL_LIMITS.left), 300);
});

test("dragging grows or shrinks depending on the side", () => {
  assert.equal(dragSize(300, 50, 1, PANEL_LIMITS.left), 350);
  assert.equal(dragSize(300, 50, -1, PANEL_LIMITS.right), 250);
});

test("collapsing then expanding restores the previous size", () => {
  const collapsed = toggleCollapsed({ size: 333, collapsed: false });
  assert.deepEqual(toggleCollapsed(collapsed), { size: 333, collapsed: false });
});

test("saved layouts are merged with the defaults", () => {
  const layout = normalizeLayout({ left: { size: 5, collapsed: true }, right: "junk" });
  assert.deepEqual(layout.left, { size: PANEL_LIMITS.left.min, collapsed: true });
  assert.deepEqual(layout.right, { size: PANEL_LIMITS.right.initial, collapsed: false });
  assert.deepEqual(normalizeLayout(null).bottom, { size: PANEL_LIMITS.bottom.initial, collapsed: true });
  assert.equal(normalizeLayout({ bottom: { size: 300, collapsed: false } }).bottom.collapsed, false);
});

test("the log buffer keeps the latest lines", () => {
  const buffer = new LogBuffer(3);
  for (let i = 0; i < 5; i += 1) {
    buffer.push({ time: i, level: "INFO", source: "app", message: `m${i}` });
  }
  assert.deepEqual(
    buffer.lines.map((line) => line.message),
    ["m2", "m3", "m4"],
  );
});

test("the log buffer filters by level, text and source", () => {
  const buffer = new LogBuffer();
  buffer.push({ time: 0, level: "DEBUG", source: "app", message: "details" });
  buffer.push({ time: 0, level: "WARNING", source: "worker", message: "Slow import", logger: "catalog" });
  buffer.push({ time: 0, level: "ERROR", source: "app", message: "Crash" });
  assert.equal(buffer.filtered({ minLevel: "WARNING" }).length, 2);
  assert.equal(buffer.filtered({ text: "CATALOG" })[0].message, "Slow import");
  assert.equal(buffer.filtered({ source: "app" }).length, 2);
  assert.equal(buffer.filtered().length, 3);
});

test("lines are formatted with time, level and source", () => {
  const time = new Date(2026, 0, 1, 9, 5, 7).getTime() / 1000;
  assert.equal(
    formatLine({ time, level: "INFO", source: "app", message: "Ready" }),
    "09:05:07 INFO    [app] Ready",
  );
});

test("keyboard events become shortcut strings", () => {
  assert.equal(eventToShortcut({ key: "s", ctrlKey: true, shiftKey: true }), "Ctrl+Shift+S");
  assert.equal(eventToShortcut({ key: "z", metaKey: true }), "Ctrl+Z");
  assert.equal(eventToShortcut({ key: "F5" }), "F5");
  assert.equal(eventToShortcut({ key: "ArrowUp", altKey: true }), "Alt+ArrowUp");
  assert.equal(eventToShortcut({ key: "Shift", shiftKey: true }), null);
});

test("hand-written shortcuts are normalized", () => {
  assert.equal(normalizeShortcut("shift+ctrl+s"), "Ctrl+Shift+S");
  assert.equal(normalizeShortcut("Del"), "Delete");
  assert.equal(displayShortcut("Alt+ArrowUp"), "Alt+↑");
});

test("typing in fields disables shortcuts", () => {
  assert.equal(isTypingTarget({ tagName: "INPUT", type: "text" }), true);
  assert.equal(isTypingTarget({ tagName: "INPUT", type: "checkbox" }), false);
  assert.equal(isTypingTarget({ tagName: "TEXTAREA" }), true);
  assert.equal(isTypingTarget({ tagName: "DIV", isContentEditable: true }), true);
  assert.equal(isTypingTarget({ tagName: "BUTTON" }), false);
  assert.equal(isTypingTarget(null), false);
});
