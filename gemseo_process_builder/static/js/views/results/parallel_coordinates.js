// @ts-check
// Parallel coordinates: one axis per variable, one line per evaluation.
// Axes can be dragged to reorder them; brushing an axis keeps the lines
// crossing the brushed range (every brushed axis must agree).
import { app } from "../../app.js";
import { el } from "../../components/dom.js";
import { linearDomain } from "../../lib/chart_scales.js";
import { evenPositions } from "../../lib/decimate.js";
import { explain, focusedNames, pointColors, selectedPositions } from "./common.js";

/** Lines drawn at most (the brushes still consider every loaded evaluation). */
const MAX_LINES = 2000;
const MAX_AXES = 10;
/** The design variables among the axes at most; the responses take the others. */
const MAX_INPUT_AXES = 6;
const MARGIN = { top: 34, right: 40, bottom: 16, left: 40 };

export class ParallelCoordinates {
  /** @param {HTMLElement} root */
  constructor(root) {
    this.toolbar = el("div.results-toolbar");
    this.plot = el("div.parallel-plot");
    root.append(this.toolbar, this.plot);
    /** @type {string[]} */
    this.axes = [];
    /** @type {Map<string, [number, number]>} - Brushed range of values per axis. */
    this.ranges = new Map();
    /** @type {import("./source.js").ResultsSource | null} */
    this.source = null;
    /** @type {any} */
    this.data = null;
    this.token = 0;
    this.updates = 0;
    this.filterKey = "";
    app.brushSelection.onChange((runId, origin) => {
      if (this.source && runId === this.source.runId && origin !== "parallel") {
        if (origin === "") {
          this.ranges.clear();
          this.draw();
        } else {
          this.highlight();
        }
      }
    });
    new ResizeObserver(() => this.source && this.draw()).observe(this.plot);
  }

  /** @param {import("./source.js").ResultsSource} source */
  async update(source) {
    this.source = source;
    if (source.live) {
      explain(this.plot, "The parallel coordinates are available when the run ends.");
      this.toolbar.replaceChildren();
      return;
    }
    const token = ++this.updates;
    const { focus, names, key } = await focusedNames(source);
    if (token !== this.updates) {
      return;
    }
    if (key !== this.filterKey || !this.axes.length || this.axes.some((name) => !names.includes(name))) {
      this.filterKey = key;
      const inputs = focus.inputs.slice(0, MAX_INPUT_AXES);
      this.axes = [...inputs, ...focus.responses.slice(0, MAX_AXES - inputs.length)];
      this.ranges.clear();
    }
    this.toolbar.replaceChildren(
      el("span.form-hint", { text: "Drag an axis title to move it; brush along axes to select." }),
      el("span.toolbar-spacer"),
      el("button.button.bordered", {
        text: "Clear selection",
        onClick: () => app.brushSelection.set(source.runId, null, ""),
      }),
    );
    this.draw();
  }

  async draw() {
    const source = this.source;
    if (!source || source.live || !this.axes.length) {
      return;
    }
    const token = ++this.token;
    const names = [...this.axes];
    if (source.columns.some((column) => column.name === "feasible")) {
      names.push("feasible");
    }
    const data = await source.matrix(names);
    if (token !== this.token) {
      return;
    }
    this.data = data;
    const d3 = /** @type {any} */ (window).d3;
    this.plot.replaceChildren();
    const width = this.plot.clientWidth;
    const height = this.plot.clientHeight;
    if (width < 200 || height < 120) {
      return;
    }
    const innerHeight = height - MARGIN.top - MARGIN.bottom;
    const x = d3.scalePoint().domain(this.axes).range([MARGIN.left, width - MARGIN.right]);
    /** @type {Record<string, any>} */
    const y = Object.fromEntries(
      this.axes.map((name) => [name, d3.scaleLinear().domain(linearDomain(data.columns[name])).nice().range([innerHeight, 0])]),
    );
    const svg = d3.select(this.plot).append("svg").attr("width", width).attr("height", height);
    const group = svg.append("g").attr("transform", `translate(0,${MARGIN.top})`);
    const colors = pointColors("feasible", data.columns);
    const drawn = evenPositions(data.evaluations.length, MAX_LINES);
    // One point per axis; a missing value breaks the line.
    const line = d3
      .line()
      .defined((/** @type {{value: number | null}} */ point) => point.value !== null)
      .x((/** @type {{name: string}} */ point) => x(point.name))
      .y((/** @type {{name: string, value: number}} */ point) => y[point.name](point.value));
    const path = (/** @type {number} */ index) =>
      line(this.axes.map((name) => ({ name, value: data.columns[name][index] })));
    group
      .append("g")
      .attr("class", "parallel-lines")
      .selectAll("path")
      .data(drawn)
      .join("path")
      .attr("class", "parallel-line")
      .attr("stroke", (/** @type {number} */ index) => colors(index))
      .attr("d", path);

    for (const name of this.axes) {
      const axis = group.append("g").attr("class", "chart-axis").attr("transform", `translate(${x(name)},0)`);
      axis.call(d3.axisLeft(y[name]).ticks(5).tickFormat(d3.format(".3~g")));
      axis
        .append("text")
        .attr("class", "parallel-title")
        .attr("y", -12)
        .attr("text-anchor", "middle")
        .text(name)
        .call(this.dragAxis(name, x));
      const brush = d3
        .brushY()
        .extent([
          [-10, 0],
          [10, innerHeight],
        ])
        .on("end", (/** @type {any} */ event) => {
          if (!event.sourceEvent) {
            return;
          }
          if (event.selection) {
            const [top, bottom] = event.selection;
            this.ranges.set(name, [y[name].invert(bottom), y[name].invert(top)]);
          } else {
            this.ranges.delete(name);
          }
          this.select();
        });
      const brushGroup = axis.append("g").attr("class", "brush").call(brush);
      const range = this.ranges.get(name);
      if (range) {
        brushGroup.call(brush.move, [y[name](range[1]), y[name](range[0])]);
      }
    }
    svg.append("text").attr("class", "chart-label").attr("x", MARGIN.left).attr("y", height - 2).text(
      data.evaluations.length > MAX_LINES
        ? `${MAX_LINES} of ${data.total} evaluations drawn; green feasible, red not`
        : `${data.total} evaluations; green feasible, red not`,
    );
    this.highlight();
  }

  /**
   * Drag an axis title sideways to move the axis.
   *
   * @param {string} name
   * @param {any} x
   */
  dragAxis(name, x) {
    const d3 = /** @type {any} */ (window).d3;
    return d3
      .drag()
      .on("drag", (/** @type {any} */ event) => {
        d3.select(event.sourceEvent.target.parentNode).attr("transform", `translate(${event.x},0)`);
      })
      .on("end", (/** @type {any} */ event) => {
        const positions = this.axes.map((axis) => (axis === name ? event.x : x(axis)));
        this.axes = this.axes
          .map((axis, index) => ({ axis, position: positions[index] }))
          .sort((a, b) => a.position - b.position)
          .map((item) => item.axis);
        this.draw();
      });
  }

  /** Select the evaluations inside every brushed range. */
  select() {
    if (!this.source || !this.data) {
      return;
    }
    if (!this.ranges.size) {
      app.brushSelection.set(this.source.runId, null, "parallel");
      this.highlight();
      return;
    }
    const selected = new Set();
    this.data.evaluations.forEach((/** @type {number} */ evaluation, /** @type {number} */ index) => {
      const inside = [...this.ranges].every(([name, [low, high]]) => {
        const value = this.data.columns[name][index];
        return value !== null && value >= low && value <= high;
      });
      if (inside) {
        selected.add(evaluation);
      }
    });
    app.brushSelection.set(this.source.runId, selected, "parallel");
    this.highlight();
  }

  highlight() {
    if (!this.source || !this.data) {
      return;
    }
    const positions = selectedPositions(app.brushSelection.get(this.source.runId), this.data.evaluations);
    const d3 = /** @type {any} */ (window).d3;
    d3.select(this.plot)
      .selectAll("path.parallel-line")
      .classed("dimmed", (/** @type {number} */ index) => positions !== null && !positions.has(index))
      .attr("stroke-width", (/** @type {number} */ index) => (positions?.has(index) ? 1.6 : 1));
  }
}
