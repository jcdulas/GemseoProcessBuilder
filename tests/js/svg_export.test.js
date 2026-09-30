import assert from "node:assert/strict";
import { test } from "node:test";

import {
  fitViewBox,
  pngSize,
  serializeTree,
  standaloneSvg,
  styleAttribute,
} from "../../gemseo_process_builder/static/js/lib/svg_export.js";

test("computed styles are written without the defaults", () => {
  const computed = {
    fill: "rgb(31, 111, 209)",
    stroke: "none",
    "stroke-width": "1.5px",
    opacity: "1",
    "font-family": '"Segoe UI", Roboto, sans-serif',
    "font-size": "13px",
    "text-anchor": "middle",
    visibility: "visible",
  };
  assert.equal(styleAttribute("rect", computed), "fill:rgb(31, 111, 209);stroke:none;stroke-width:1.5px");
  assert.equal(
    styleAttribute("text", computed),
    "fill:rgb(31, 111, 209);stroke:none;stroke-width:1.5px;font-family:'Segoe UI', Roboto, sans-serif;font-size:13px;text-anchor:middle",
  );
  // Fonts without a generic family get system fallbacks.
  assert.match(styleAttribute("text", { "font-family": "Cascadia Mono" }), /Cascadia Mono, Arial, Helvetica, sans-serif/);
});

test("trees become SVG text, without the attributes of the page", () => {
  const tree = {
    tag: "g",
    attributes: { class: "node", transform: "translate(10,20)", onclick: "x()" },
    style: { opacity: "0.5" },
    children: [
      { tag: "rect", attributes: { width: "5", height: "4" }, style: { fill: "red" }, children: [] },
      { tag: "text", attributes: { x: "1" }, style: {}, children: [], text: "a < b & c" },
    ],
  };
  assert.equal(
    serializeTree(tree),
    '<g transform="translate(10,20)" style="opacity:0.5"><rect width="5" height="4" style="fill:red"/><text x="1">a &lt; b &amp; c</text></g>',
  );
});

test("the viewBox fits the content with a margin", () => {
  assert.deepEqual(fitViewBox({ x: 10.4, y: -5.2, width: 100.3, height: 50 }, 10), { x: 0, y: -16, width: 121, height: 71 });
});

test("standalone documents have a namespace and a background", () => {
  const text = standaloneSvg("<circle r=\"2\"/>", { x: -5, y: 0, width: 50, height: 40 }, { title: "Sellar & co" });
  assert.match(text, /^<\?xml/);
  assert.match(text, /xmlns="http:\/\/www\.w3\.org\/2000\/svg"/);
  assert.match(text, /viewBox="-5 0 50 40"/);
  assert.match(text, /<title>Sellar &amp; co<\/title>/);
  assert.match(text, /<rect x="-5" y="0" width="50" height="40" fill="#ffffff"\/><circle r="2"\/><\/svg>/);
  assert.doesNotMatch(standaloneSvg("", { x: 0, y: 0, width: 1, height: 1 }, { background: "" }), /<rect/);
});

test("PNG sizes are limited", () => {
  assert.deepEqual(pngSize(400, 300, 2), { width: 800, height: 600, scale: 2 });
  const large = pngSize(8000, 1000, 4);
  assert.equal(large.width, 16384);
  assert.equal(large.scale, 16384 / 8000);
});
