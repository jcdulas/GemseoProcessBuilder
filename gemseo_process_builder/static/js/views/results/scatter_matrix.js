// @ts-check
// Scatter matrix: every pair of chosen variables, with brushing in any cell.
import { app } from "../../app.js";
import { cssColor } from "../../charts/axis.js";
import { el } from "../../components/dom.js";
import { maxCount } from "../../lib/binning.js";
import { linearDomain } from "../../lib/chart_scales.js";
import { BINNING_THRESHOLD, choice, explain, labelled, plottable, pointColors, selectedPositions } from "./common.js";

const MAX_VARIABLES = 6;
const PADDING = 26;

export class ScatterMatrix {
  /** @param {HTMLElement} root */
  constructor(root) {
    this.toolbar = el("div.results-toolbar");
    this.body = el("div.matrix-body");
    root.append(this.toolbar, this.body);
    /** @type {string[]} */
    this.variables = [];
    this.color = "feasible";
    /** @type {import("./source.js").ResultsSource | null} */
    this.source = null;
    this.token = 0;
    /** @type {any[]} - The cells with a brush. */
    this.cells = [];
    /** @type {any} */
    this.data = null;
    app.brushSelection.onChange((runId, origin) => {
      if (this.source && runId === this.source.runId && origin !== "scatter") {
        this.highlight();
      }
    });
    new ResizeObserver(() => this.source && this.draw()).observe(this.body);
  }

  /** @param {import("./source.js").ResultsSource} source */
  update(source) {
    this.source = source;
    if (source.live) {
      explain(this.body, "The scatter matrix is available when the run ends.");
      this.toolbar.replaceChildren();
      return;
    }
    const names = plottable(source);
    if (!this.variables.length || this.variables.some((name) => !names.includes(name))) {
      this.variables = names.slice(0, 4);
    }
    this.renderToolbar(names);
    this.draw();
  }

  /** @param {string[]} names */
  renderToolbar(names) {
    const chips = names.map((name) => {
      const box = /** @type {HTMLInputElement} */ (el("input", { type: "checkbox", checked: this.variables.includes(name) }));
      box.addEventListener("change", () => {
        if (box.checked && this.variables.length < MAX_VARIABLES) {
          this.variables = names.filter((candidate) => candidate === name || this.variables.includes(candidate));
        } else if (!box.checked && this.variables.length > 2) {
          this.variables = this.variables.filter((candidate) => candidate !== name);
        }
        box.checked = this.variables.includes(name);
        this.draw();
      });
      return el("label.variable-chip", {}, [box, name]);
    });
    this.toolbar.replaceChildren(
      el("span.variable-chips", {}, chips),
      labelled(
        "Color",
        choice(
          names,
          this.color,
          (value) => {
            this.color = value;
            this.draw();
          },
          [
            { value: "feasible", label: "feasibility" },
            { value: "none", label: "none" },
          ],
        ),
      ),
      el("button.button.bordered", { text: "Clear selection", onClick: () => this.source && app.brushSelection.set(this.source.runId, null, "") }),
    );
  }

  async draw() {
    const source = this.source;
    if (!source || source.live) {
      return;
    }
    const token = ++this.token;
    const names = [...new Set([...this.variables, ...(this.color !== "none" && this.color !== "feasible" ? [this.color] : []), "feasible"])];
    const available = new Set(source.columns.map((column) => column.name));
    const data = await source.matrix(names.filter((name) => available.has(name)));
    if (token !== this.token) {
      return;
    }
    this.data = data;
    const binned = data.total >= BINNING_THRESHOLD;
    const count = this.variables.length;
    const size = Math.max(90, Math.min(200, (this.body.clientWidth - PADDING * 2) / count));
    const d3 = /** @type {any} */ (window).d3;
    this.body.replaceChildren();
    const svg = d3
      .select(this.body)
      .append("svg")
      .attr("width", size * count + PADDING * 2)
      .attr("height", size * count + PADDING * 2);
    const scales = this.variables.map((name) => linearDomain(data.columns[name] ?? []));
    const colors = pointColors(this.color, data.columns);
    this.cells = [];
    for (let row = 0; row < count; row += 1) {
      for (let column = 0; column < count; column += 1) {
        const cell = svg.append("g").attr("transform", `translate(${PADDING + column * size},${PADDING + row * size})`);
        cell.append("rect").attr("class", "matrix-frame").attr("width", size - 6).attr("height", size - 6);
        const x = d3.scaleLinear().domain(scales[column]).range([3, size - 9]);
        const y = d3.scaleLinear().domain(scales[row]).range([size - 9, 3]);
        const xName = this.variables[column];
        const yName = this.variables[row];
        if (row === column) {
          this.drawDiagonal(cell, xName, x, size, data);
        } else if (binned) {
          this.drawBins(cell, source, xName, yName, size, token);
        } else {
          this.drawPoints(cell, data, xName, yName, x, y, colors);
          this.installBrush(cell, data, xName, yName, x, y, size);
        }
        if (row === count - 1) {
          cell.append("text").attr("class", "chart-label").attr("x", (size - 6) / 2).attr("y", size + 8).attr("text-anchor", "middle").text(xName);
        }
        if (column === 0) {
          cell.append("text").attr("class", "chart-label").attr("transform", `translate(-8,${(size - 6) / 2}) rotate(-90)`).attr("text-anchor", "middle").text(yName);
        }
      }
    }
    if (binned) {
      this.body.append(el("p.form-hint", { text: `${data.total} evaluations: the cells count the points in bins (brushing works below ${BINNING_THRESHOLD} evaluations).` }));
    }
    this.highlight();
  }

  /**
   * @param {any} cell
   * @param {string} name
   * @param {any} x
   * @param {number} size
   * @param {any} data
   */
  drawDiagonal(cell, name, x, size, data) {
    const d3 = /** @type {any} */ (window).d3;
    const values = (data.columns[name] ?? []).filter((/** @type {any} */ value) => value !== null);
    const bins = d3.bin().domain(x.domain()).thresholds(12)(values);
    const height = d3.scaleLinear().domain([0, d3.max(bins, (/** @type {any} */ bin) => bin.length) || 1]).range([0, size - 30]);
    cell
      .selectAll("rect.matrix-bar")
      .data(bins)
      .join("rect")
      .attr("class", "matrix-bar")
      .attr("x", (/** @type {any} */ bin) => x(bin.x0))
      .attr("width", (/** @type {any} */ bin) => Math.max(0, x(bin.x1) - x(bin.x0) - 1))
      .attr("y", (/** @type {any} */ bin) => size - 9 - height(bin.length))
      .attr("height", (/** @type {any} */ bin) => height(bin.length));
    cell.append("text").attr("class", "matrix-name").attr("x", 6).attr("y", 14).text(name);
  }

  /**
   * @param {any} cell
   * @param {any} data
   * @param {string} xName
   * @param {string} yName
   * @param {any} x
   * @param {any} y
   * @param {(index: number) => string} colors
   */
  drawPoints(cell, data, xName, yName, x, y, colors) {
    const xs = data.columns[xName];
    const ys = data.columns[yName];
    const indices = data.evaluations.map((/** @type {number} */ _, /** @type {number} */ index) => index).filter((/** @type {number} */ index) => xs[index] !== null && ys[index] !== null);
    cell
      .selectAll("circle")
      .data(indices)
      .join("circle")
      .attr("class", "matrix-point")
      .attr("r", 2.2)
      .attr("cx", (/** @type {number} */ index) => x(xs[index]))
      .attr("cy", (/** @type {number} */ index) => y(ys[index]))
      .attr("fill", (/** @type {number} */ index) => colors(index));
  }

  /**
   * Counts of points in bins, computed by the worker on every evaluation.
   *
   * @param {any} cell
   * @param {import("./source.js").ResultsSource} source
   * @param {string} xName
   * @param {string} yName
   * @param {number} size
   * @param {number} token
   */
  async drawBins(cell, source, xName, yName, size, token) {
    const bins = 24;
    const result = await app.api.call("results.binned", { id: source.runId, x: xName, y: yName, bins }, { timeout: 120_000 });
    if (token !== this.token) {
      return;
    }
    const d3 = /** @type {any} */ (window).d3;
    const shade = d3.scaleSequential(d3.interpolateRgb(cssColor("--color-surface"), cssColor("--color-accent"))).domain([0, Math.log1p(maxCount(result.counts))]);
    const side = (size - 12) / bins;
    const cells = [];
    for (let i = 0; i < bins; i += 1) {
      for (let j = 0; j < bins; j += 1) {
        if (result.counts[i][j]) {
          cells.push({ i, j, count: result.counts[i][j] });
        }
      }
    }
    cell
      .selectAll("rect.matrix-bin")
      .data(cells)
      .join("rect")
      .attr("class", "matrix-bin")
      .attr("x", (/** @type {any} */ bin) => 3 + bin.i * side)
      .attr("y", (/** @type {any} */ bin) => size - 9 - (bin.j + 1) * side)
      .attr("width", side)
      .attr("height", side)
      .attr("fill", (/** @type {any} */ bin) => shade(Math.log1p(bin.count)))
      .append("title")
      .text((/** @type {any} */ bin) => `${bin.count} points`);
  }

  /**
   * @param {any} cell
   * @param {any} data
   * @param {string} xName
   * @param {string} yName
   * @param {any} x
   * @param {any} y
   * @param {number} size
   */
  installBrush(cell, data, xName, yName, x, y, size) {
    const d3 = /** @type {any} */ (window).d3;
    const brush = d3
      .brush()
      .extent([
        [0, 0],
        [size - 6, size - 6],
      ])
      .on("end", (/** @type {any} */ event) => {
        if (!event.sourceEvent || !this.source) {
          return;
        }
        if (!event.selection) {
          app.brushSelection.set(this.source.runId, null, "scatter");
          this.highlight();
          return;
        }
        const [[x0, y0], [x1, y1]] = event.selection;
        const xs = data.columns[xName];
        const ys = data.columns[yName];
        const selected = new Set();
        data.evaluations.forEach((/** @type {number} */ evaluation, /** @type {number} */ index) => {
          const px = x(xs[index]);
          const py = y(ys[index]);
          if (xs[index] !== null && ys[index] !== null && px >= x0 && px <= x1 && py >= y0 && py <= y1) {
            selected.add(evaluation);
          }
        });
        // One brush at a time: clear the others.
        for (const other of this.cells ?? []) {
          if (other !== cell) {
            other.select(".brush").call(brush.move, null);
          }
        }
        app.brushSelection.set(this.source.runId, selected, "scatter");
        this.highlight();
      });
    cell.append("g").attr("class", "brush").call(brush);
    this.cells?.push(cell);
  }

  highlight() {
    if (!this.source || !this.data) {
      return;
    }
    const positions = selectedPositions(app.brushSelection.get(this.source.runId), this.data.evaluations);
    const d3 = /** @type {any} */ (window).d3;
    d3.select(this.body)
      .selectAll("circle.matrix-point")
      .classed("dimmed", (/** @type {number} */ index) => positions !== null && !positions.has(index));
    const count = positions === null ? "" : `${positions.size} selected`;
    this.body.dataset.selected = count;
  }
}

