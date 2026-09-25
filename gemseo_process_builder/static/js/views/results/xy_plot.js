// @ts-check
// XY plot: any two variables, colored by feasibility or a third one, with brushing.
import { app } from "../../app.js";
import { MARGIN, cssColor, drawAxes, formatNumber } from "../../charts/axis.js";
import { hideTooltip, showTooltip } from "../../charts/tooltip.js";
import { el } from "../../components/dom.js";
import { linearDomain } from "../../lib/chart_scales.js";
import { choice, explain, labelled, plottable, pointColors, selectedPositions } from "./common.js";

export class XYPlot {
  /** @param {HTMLElement} root */
  constructor(root) {
    this.toolbar = el("div.results-toolbar");
    this.plot = el("div.xy-plot");
    root.append(this.toolbar, this.plot);
    this.x = "";
    this.y = "";
    this.color = "feasible";
    this.line = false;
    /** @type {import("./source.js").ResultsSource | null} */
    this.source = null;
    /** @type {any} */
    this.data = null;
    this.token = 0;
    app.brushSelection.onChange((runId, origin) => {
      if (this.source && runId === this.source.runId && origin !== "xy") {
        this.highlight();
      }
    });
    new ResizeObserver(() => this.source && this.draw()).observe(this.plot);
  }

  /** @param {import("./source.js").ResultsSource} source */
  update(source) {
    this.source = source;
    if (source.live) {
      explain(this.plot, "The XY plot is available when the run ends.");
      this.toolbar.replaceChildren();
      return;
    }
    const names = plottable(source);
    this.x = names.includes(this.x) ? this.x : (names[0] ?? "");
    this.y = names.includes(this.y) ? this.y : (source.byRole("objective")[0]?.name ?? source.byRole("output")[0]?.name ?? names[1] ?? "");
    const redraw = () => this.draw();
    /** @param {(value: string) => void} apply - Keeps the choice, then redraws. */
    const choose = (apply) => (/** @type {string} */ value) => {
      apply(value);
      redraw();
    };
    const line = /** @type {HTMLInputElement} */ (el("input", { type: "checkbox", checked: this.line }));
    line.addEventListener("change", () => {
      this.line = line.checked;
      redraw();
    });
    this.toolbar.replaceChildren(
      labelled("X", choice(names, this.x, choose((value) => (this.x = value)))),
      labelled("Y", choice(names, this.y, choose((value) => (this.y = value)))),
      labelled(
        "Color",
        choice(names, this.color, choose((value) => (this.color = value)), [
          { value: "feasible", label: "feasibility" },
          { value: "none", label: "none" },
        ]),
      ),
      el("label.form-check", {}, [line, el("span", { text: "Join in evaluation order" })]),
      el("button.button.bordered", { text: "Clear selection", onClick: () => app.brushSelection.set(source.runId, null, "") }),
    );
    this.draw();
  }

  async draw() {
    const source = this.source;
    if (!source || source.live || !this.x || !this.y) {
      return;
    }
    const token = ++this.token;
    const names = [...new Set([this.x, this.y, ...(this.color !== "none" && this.color !== "feasible" ? [this.color] : [])])];
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
    if (width < 120 || height < 100) {
      return;
    }
    const innerWidth = width - MARGIN.left - MARGIN.right;
    const innerHeight = height - MARGIN.top - MARGIN.bottom;
    const xs = data.columns[this.x];
    const ys = data.columns[this.y];
    const x = d3.scaleLinear().domain(linearDomain(xs)).nice().range([0, innerWidth]);
    const y = d3.scaleLinear().domain(linearDomain(ys)).nice().range([innerHeight, 0]);
    const svg = d3.select(this.plot).append("svg").attr("width", width).attr("height", height);
    const group = svg.append("g").attr("transform", `translate(${MARGIN.left},${MARGIN.top})`);
    drawAxes(group, x, y, { width: innerWidth, height: innerHeight, xLabel: this.x, yLabel: this.y });
    const indices = data.evaluations.map((/** @type {number} */ _, /** @type {number} */ index) => index).filter((/** @type {number} */ index) => xs[index] !== null && ys[index] !== null);
    if (this.line) {
      group
        .append("path")
        .datum(indices)
        .attr("class", "chart-line")
        .attr("stroke", cssColor("--color-border-strong"))
        .attr("d", d3.line().x((/** @type {number} */ index) => x(xs[index])).y((/** @type {number} */ index) => y(ys[index])));
    }
    const colors = pointColors(this.color, data.columns);
    group
      .selectAll("circle")
      .data(indices)
      .join("circle")
      .attr("class", "xy-point")
      .attr("r", 3.5)
      .attr("cx", (/** @type {number} */ index) => x(xs[index]))
      .attr("cy", (/** @type {number} */ index) => y(ys[index]))
      .attr("fill", (/** @type {number} */ index) => colors(index))
      .on("mousemove", (/** @type {MouseEvent} */ event, /** @type {number} */ index) =>
        showTooltip(event.clientX, event.clientY, [
          `Evaluation ${data.evaluations[index]}`,
          `${this.x}: ${formatNumber(xs[index])}`,
          `${this.y}: ${formatNumber(ys[index])}`,
        ]),
      )
      .on("mouseleave", hideTooltip);
    const brush = d3
      .brush()
      .extent([
        [0, 0],
        [innerWidth, innerHeight],
      ])
      .on("end", (/** @type {any} */ event) => {
        if (!event.sourceEvent) {
          return;
        }
        if (!event.selection) {
          app.brushSelection.set(source.runId, null, "xy");
        } else {
          const [[x0, y0], [x1, y1]] = event.selection;
          const selected = new Set(
            indices
              .filter((/** @type {number} */ index) => {
                const px = x(xs[index]);
                const py = y(ys[index]);
                return px >= x0 && px <= x1 && py >= y0 && py <= y1;
              })
              .map((/** @type {number} */ index) => data.evaluations[index]),
          );
          app.brushSelection.set(source.runId, selected, "xy");
        }
        this.highlight();
      });
    // The brush lies under the points, so that their tooltips still show.
    group.insert("g", "circle").attr("class", "brush").call(brush);
    this.highlight();
  }

  highlight() {
    if (!this.source || !this.data) {
      return;
    }
    const positions = selectedPositions(app.brushSelection.get(this.source.runId), this.data.evaluations);
    const d3 = /** @type {any} */ (window).d3;
    d3.select(this.plot)
      .selectAll("circle.xy-point")
      .classed("dimmed", (/** @type {number} */ index) => positions !== null && !positions.has(index));
  }
}
