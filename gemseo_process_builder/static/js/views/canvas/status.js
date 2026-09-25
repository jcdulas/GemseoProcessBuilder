// @ts-check
// Execution states of a run on the canvas: a dot in the node header and a tint.

const STATES = ["pending", "running", "done", "failed"];

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
    let dot = group.select("circle.run-dot");
    if (!state) {
      dot.remove();
      return;
    }
    if (dot.empty()) {
      dot = group.append("circle").attr("class", "run-dot").attr("r", 4);
      dot.append("title");
    }
    dot.attr("cx", item.width - 7).attr("cy", 7);
    dot.select("title").text(`Run: ${state}`);
  });
}
