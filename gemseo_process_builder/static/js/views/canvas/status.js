// @ts-check
// Execution states of a run on the canvas: a ring around the running nodes and
// a badge on the corner of each node (a check once done, a mark if it failed).

const STATES = ["pending", "running", "done", "failed"];

/** The glyph of each badge, drawn in a 16×16 box centered on the corner. */
const GLYPHS = {
  pending: "",
  running: "M-3,0h.01 M0,0h.01 M3,0h.01",
  done: "M-3.2,0.2l2.2,2.2 4.2-4.6",
  failed: "M0,-3.5v3.8 M0,3h.01",
};

const LABELS = { pending: "waiting", running: "running", done: "done", failed: "failed" };

/**
 * Show the run state of each drawn node, without redrawing the nodes.
 *
 * @param {any} nodesLayer - d3 selection of the nodes layer.
 * @param {(id: string) => string | null} stateOf
 */
export function applyRunStates(nodesLayer, stateOf) {
  nodesLayer.selectAll("g.node").each(function (/** @type {any} */ item) {
    // @ts-ignore - d3 binds `this` to the group element.
    const group = d3.select(this);
    const state = stateOf(item.id);
    for (const candidate of STATES) {
      group.classed(`run-${candidate}`, state === candidate);
    }
    let badge = group.select("g.run-badge");
    if (!state) {
      badge.remove();
      return;
    }
    if (badge.empty()) {
      badge = group.append("g").attr("class", "run-badge");
      badge.append("circle").attr("class", "run-dot").attr("r", 9);
      badge.append("path").attr("class", "run-glyph");
      badge.append("title");
    }
    badge.attr("transform", `translate(${item.width - 2},2)`);
    badge.select("path").attr("d", GLYPHS[/** @type {keyof GLYPHS} */ (state)] ?? "");
    badge.select("title").text(`Run: ${LABELS[/** @type {keyof LABELS} */ (state)] ?? state}`);
  });
}
