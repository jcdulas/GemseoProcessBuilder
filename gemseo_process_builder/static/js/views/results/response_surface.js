// @ts-check
// Response surface: the landscape of a response over two design variables,
// predicted by a metamodel (Kriging, neural network…) trained by the worker on
// the evaluations of the run, the other design variables at their best values.
// Drawn in 2D (filled contours) or in 3D (a surface turned with the mouse),
// with the boundaries of the constraints and the infeasible regions hatched.
import { app } from "../../app.js";
import { cssColor, drawAxes, formatNumber } from "../../charts/axis.js";
import { hideTooltip, showTooltip } from "../../charts/tooltip.js";
import { el } from "../../components/dom.js";
import { contourIndex, flatten, gridRange, interpolate, isoSegments, project, surfaceCells, valueAt } from "../../lib/surface_3d.js";
import { MAX_CHOICES, choice, explain, labelled } from "./common.js";

/** Constraints whose boundaries are drawn at most. */
const MAX_CONSTRAINTS = 6;
const MARGIN = { top: 16, right: 90, bottom: 44, left: 64 };
const LEVELS = 14;
/** Below this quality on the evaluations left aside, the view warns. */
const GOOD_R2 = 0.8;

/**
 * @typedef {object} SurfaceOutput
 * @property {string} name
 * @property {string} role
 * @property {(number | null)[][]} z - `z[j][i]` at `x[i]`, `y[j]`.
 * @property {number | null} r2
 * @property {(number | null)[]} samples
 */

/**
 * @typedef {object} Surface - The result of `results.responseSurface`.
 * @property {string} label
 * @property {string[]} inputs
 * @property {{name: string, values: number[]}} x
 * @property {{name: string, values: number[]}} y
 * @property {SurfaceOutput[]} outputs
 * @property {{evaluations: number[], x: (number | null)[], y: (number | null)[], feasible: (number | null)[] | null}} samples
 * @property {{evaluation: number, x: number, y: number}} best
 * @property {number} n_rows
 * @property {number} n_test
 * @property {number} seconds
 */

/** @type {Promise<{name: string, label: string}[]> | null} */
let algorithms = null;

export class ResponseSurfaceView {
  /** @param {HTMLElement} root */
  constructor(root) {
    this.toolbar = el("div.results-toolbar");
    this.status = el("div.surface-status");
    this.plot = el("div.surface-plot");
    root.append(this.toolbar, this.status, this.plot);
    this.x = "";
    this.y = "";
    this.response = "";
    this.algorithm = "GaussianProcessRegressor";
    this.learnFrom = 8;
    this.mode = "2d";
    this.showConstraints = true;
    /** The response the design variables were ranked for by this view, if any. */
    this.rankedFor = "";
    this.view = { azimuth: -0.7, elevation: 0.55 };
    this.filterKey = "";
    this.requestKey = "";
    this.token = 0;
    /** @type {Surface | null} */
    this.surface = null;
    /** @type {import("./source.js").ResultsSource | null} */
    this.source = null;
    /** @type {string[]} */
    this.inputs = [];
    /** @type {string[]} */
    this.constraints = [];
    new ResizeObserver(() => this.draw()).observe(this.plot);
  }

  /** @param {import("./source.js").ResultsSource} source */
  async update(source) {
    this.source = source;
    if (source.live) {
      explain(this.plot, "The response surface is available when the run ends.");
      this.toolbar.replaceChildren();
      this.status.replaceChildren();
      return;
    }
    const token = ++this.token;
    const [focus, offered] = await Promise.all([source.focus(), (algorithms ??= app.api.call("results.surfaceAlgorithms"))]);
    if (token !== this.token) {
      return;
    }
    const roles = new Map(source.columns.map((column) => [column.name, column.role]));
    const responses = focus.responses.filter((name) => roles.get(name) !== "constraint");
    const allResponses = [...responses, ...focus.responses.filter((name) => roles.get(name) === "constraint")].slice(0, MAX_CHOICES);
    this.constraints = focus.responses.filter((name) => roles.get(name) === "constraint").slice(0, MAX_CONSTRAINTS);
    if (!allResponses.includes(this.response)) {
      this.response = responses[0] ?? allResponses[0] ?? "";
    }
    // The design variables of the filter, the most important first; all of
    // them when the filter keeps fewer than two.
    const designs = source.byRole("design variable").map((column) => column.name);
    this.inputs = focus.inputs.length >= 2 ? focus.inputs : designs;
    this.rankedFor = "";
    // When the filter keeps them all, the view ranks them by sensitivity to
    // the response: the axes and the metamodel take the first ones.
    if (source.filter.mode === "all" && designs.length > 2 && this.response) {
      try {
        const ranking = await source.rankingOf({ method: "sensitivity", response: this.response, limit: 100, active_only: false, response_limit: 1 });
        this.inputs = ranking.inputs.map((item) => item.name);
        this.rankedFor = this.response;
      } catch (error) {
        console.error(error);
      }
      if (token !== this.token) {
        return;
      }
    }
    this.inputs = this.inputs.slice(0, MAX_CHOICES);
    const key = JSON.stringify([source.filter, this.rankedFor]);
    if (key !== this.filterKey || !this.inputs.includes(this.x) || !this.inputs.includes(this.y)) {
      this.filterKey = key;
      this.x = this.inputs[0] ?? "";
      this.y = this.inputs[1] ?? "";
    }
    if (this.inputs.length < 2 || !this.response) {
      this.toolbar.replaceChildren();
      explain(this.plot, "A response surface needs two design variables and a response.");
      return;
    }
    this.renderToolbar(allResponses, offered);
    this.compute();
  }

  /**
   * @param {string[]} responses
   * @param {{name: string, label: string}[]} offered
   */
  renderToolbar(responses, offered) {
    const choose = (/** @type {(value: string) => void} */ apply) => (/** @type {string} */ value) => {
      apply(value);
      this.compute();
    };
    const learnFrom = /** @type {HTMLInputElement} */ (
      el("input.input.focus-count", { type: "number", min: "2", max: "20", value: String(this.learnFrom), title: "The most important design variables the metamodel learns from" })
    );
    learnFrom.addEventListener("change", () => {
      this.learnFrom = Math.max(2, Math.min(20, Math.round(Number(learnFrom.value)) || 8));
      this.compute();
    });
    const constraints = /** @type {HTMLInputElement} */ (el("input", { type: "checkbox", checked: this.showConstraints }));
    constraints.addEventListener("change", () => {
      this.showConstraints = constraints.checked;
      this.draw();
    });
    const modeButton = (/** @type {string} */ mode, /** @type {string} */ text) =>
      el(`button.driver-tab-button${this.mode === mode ? ".active" : ""}`, {
        text,
        onClick: () => {
          this.mode = mode;
          this.renderToolbar(responses, offered);
          this.draw();
        },
      });
    this.toolbar.replaceChildren(
      labelled("X", choice(this.inputs, this.x, choose((value) => (this.x = value)))),
      labelled("Y", choice(this.inputs, this.y, choose((value) => (this.y = value)))),
      labelled(
        "Response",
        choice(responses, this.response, (value) => {
          this.response = value;
          // The variables that matter depend on the response.
          if (this.rankedFor && this.source) {
            this.update(this.source);
          } else {
            this.compute();
          }
        }),
      ),
      labelled(
        "Metamodel",
        choice(
          [],
          this.algorithm,
          choose((value) => (this.algorithm = value)),
          offered.map((item) => ({ value: item.name, label: item.label })),
        ),
      ),
      labelled("Learn from", learnFrom),
      el("label.form-check", {}, [constraints, el("span", { text: "Constraints" })]),
      el("span.toolbar-spacer"),
      el("span.segmented", {}, [modeButton("2d", "2D"), modeButton("3d", "3D")]),
    );
  }

  /** Train the metamodel and predict the grid (in the worker). */
  async compute() {
    const source = this.source;
    if (!source || this.x === this.y) {
      this.status.textContent = this.x === this.y ? "Choose two different variables." : "";
      return;
    }
    const learnFrom = [this.x, this.y, ...this.inputs.filter((name) => name !== this.x && name !== this.y)].slice(0, this.learnFrom);
    const outputs = [this.response, ...this.constraints.filter((name) => name !== this.response)];
    const params = { id: source.runId, x: this.x, y: this.y, outputs, inputs: learnFrom, algorithm: this.algorithm };
    const key = JSON.stringify(params);
    if (key === this.requestKey && this.surface) {
      this.draw();
      return;
    }
    this.requestKey = key;
    const label = /** @type {HTMLSelectElement | null} */ (this.toolbar.querySelectorAll("select")[3])?.selectedOptions[0]?.text ?? this.algorithm;
    this.status.replaceChildren(el("span.surface-busy", { text: `Training ${label} on the evaluations of the run…` }));
    try {
      const surface = await app.api.call("results.responseSurface", params, { timeout: 600_000 });
      if (key !== this.requestKey) {
        return;
      }
      this.surface = surface;
      this.renderStatus();
      this.draw();
    } catch (error) {
      if (key === this.requestKey) {
        this.surface = null;
        this.status.replaceChildren(el("span.focus-error", { text: String(/** @type {any} */ (error)?.message ?? error) }));
        this.plot.replaceChildren();
      }
    }
  }

  /** What the surface is, and how much it can be trusted. */
  renderStatus() {
    const surface = this.surface;
    if (!surface) {
      return;
    }
    const quality = surface.outputs.map((output) => {
      const good = output.r2 !== null && output.r2 >= GOOD_R2;
      return el(`span.surface-quality${good ? "" : ".poor"}`, {
        text: `${output.name}: R² ${output.r2 === null ? "—" : output.r2.toFixed(2)}`,
        title: good
          ? "Quality on evaluations the metamodel did not learn from"
          : "Poor quality on evaluations the metamodel did not learn from: learn from more variables, or try another metamodel",
      });
    });
    const others = (this.source?.byRole("design variable").length ?? 2) - 2;
    const fixed = others > 0 ? `; the other design variables at their values of the best evaluation (${surface.best.evaluation})` : "";
    const ranked = this.rankedFor ? `, the most sensitive to ${this.rankedFor}` : "";
    this.status.replaceChildren(
      el("span", {
        text: `${surface.label}, learned from ${surface.n_rows} evaluations and ${surface.inputs.length} design variables${ranked} (${surface.seconds} s)${fixed}. Quality on ${surface.n_test} evaluations left aside:`,
      }),
      ...quality,
    );
  }

  draw() {
    const surface = this.surface;
    if (!surface || !this.source || this.source.live) {
      return;
    }
    const width = this.plot.clientWidth;
    const height = this.plot.clientHeight;
    this.plot.replaceChildren();
    if (width < 200 || height < 160) {
      return;
    }
    const response = surface.outputs.find((output) => output.name === this.response) ?? surface.outputs[0];
    const constraints = this.showConstraints ? surface.outputs.filter((output) => output.role === "constraint") : [];
    const d3 = /** @type {any} */ (window).d3;
    const svg = d3.select(this.plot).append("svg").attr("class", "surface-svg").attr("width", width).attr("height", height);
    const range = gridRange(response.z);
    const color = d3.scaleSequential(d3.interpolateViridis).domain(range);
    if (this.mode === "3d") {
      this.draw3d(svg, surface, response, constraints, color, width, height);
    } else {
      this.draw2d(svg, surface, response, constraints, color, width, height);
    }
    this.legend(svg, response, color, range, width, height);
  }

  /**
   * Filled contours, the constraint boundaries and the evaluations.
   *
   * @param {any} svg
   * @param {Surface} surface
   * @param {SurfaceOutput} response
   * @param {SurfaceOutput[]} constraints
   * @param {any} color
   * @param {number} width
   * @param {number} height
   */
  draw2d(svg, surface, response, constraints, color, width, height) {
    const d3 = /** @type {any} */ (window).d3;
    const innerWidth = width - MARGIN.left - MARGIN.right;
    const innerHeight = height - MARGIN.top - MARGIN.bottom;
    const xs = surface.x.values;
    const ys = surface.y.values;
    const x = d3.scaleLinear().domain([xs[0], xs[xs.length - 1]]).range([0, innerWidth]);
    const y = d3.scaleLinear().domain([ys[0], ys[ys.length - 1]]).range([innerHeight, 0]);
    const group = svg.append("g").attr("transform", `translate(${MARGIN.left},${MARGIN.top})`);
    const path = d3.geoPath(
      d3.geoTransform({
        point(/** @type {number} */ px, /** @type {number} */ py) {
          /** @type {any} */ (this).stream.point(x(valueAt(xs, contourIndex(px, xs.length))), y(valueAt(ys, contourIndex(py, ys.length))));
        },
      }),
    );
    const contours = (/** @type {(number | null)[][]} */ grid, /** @type {number[]} */ thresholds) =>
      d3.contours().size([xs.length, ys.length]).thresholds(thresholds)(flatten(grid));
    const [low, high] = gridRange(response.z);
    const levels = d3.range(LEVELS).map((/** @type {number} */ index) => low + ((high - low) * index) / LEVELS);
    group
      .append("g")
      .selectAll("path")
      .data(contours(response.z, levels))
      .join("path")
      .attr("d", path)
      .attr("fill", (/** @type {any} */ contour) => color(contour.value))
      .attr("stroke", "none");
    group
      .append("g")
      .attr("class", "surface-isolines")
      .selectAll("path")
      .data(contours(response.z, levels.slice(1)))
      .join("path")
      .attr("d", path);
    // Infeasible regions hatched, and the boundaries of the constraints.
    const hatch = `surface-hatch-${Math.random().toString(36).slice(2)}`;
    svg
      .append("defs")
      .append("pattern")
      .attr("id", hatch)
      .attr("patternUnits", "userSpaceOnUse")
      .attr("width", 8)
      .attr("height", 8)
      .attr("patternTransform", "rotate(45)")
      .append("line")
      .attr("class", "surface-hatch-line")
      .attr("x1", 0)
      .attr("y1", 0)
      .attr("x2", 0)
      .attr("y2", 8);
    const types = new Map(this.source?.columns.map((column) => [column.name, column.constraintType]) ?? []);
    for (const constraint of constraints) {
      const equality = types.get(constraint.name) === "eq";
      if (!equality) {
        const [violated] = contours(constraint.z, [0]);
        group.append("path").attr("class", "surface-infeasible").attr("fill", `url(#${hatch})`).attr("d", path(violated));
      }
      const line = isoSegments(constraint.z, 0)
        .map(([from, to]) => `M${x(valueAt(xs, from[0]))},${y(valueAt(ys, from[1]))}L${x(valueAt(xs, to[0]))},${y(valueAt(ys, to[1]))}`)
        .join("");
      group
        .append("path")
        .attr("class", "surface-boundary")
        .attr("d", line)
        .append("title")
        .text(`${constraint.name} = 0${equality ? "" : ": hatched where it is violated"}`);
    }
    drawAxes(group, x, y, { width: innerWidth, height: innerHeight, xLabel: surface.x.name, yLabel: surface.y.name });
    group.selectAll(".chart-grid").remove();
    // The evaluations the metamodel learned from, and the best one.
    const feasible = surface.samples.feasible;
    const good = cssColor("--color-success");
    const bad = cssColor("--color-error");
    group
      .append("g")
      .attr("class", "surface-samples")
      .selectAll("circle")
      .data(surface.samples.evaluations.map((evaluation, index) => ({ evaluation, index })))
      .join("circle")
      .attr("cx", (/** @type {{index: number}} */ d) => x(surface.samples.x[d.index]))
      .attr("cy", (/** @type {{index: number}} */ d) => y(surface.samples.y[d.index]))
      .attr("r", 2.5)
      .attr("fill", (/** @type {{index: number}} */ d) => (feasible ? (feasible[d.index] === 1 ? good : bad) : "white"));
    group.append("circle").attr("class", "surface-best").attr("cx", x(surface.best.x)).attr("cy", y(surface.best.y)).attr("r", 7);
    // The predicted value under the pointer.
    group
      .append("rect")
      .attr("class", "surface-hover")
      .attr("width", innerWidth)
      .attr("height", innerHeight)
      .on("mousemove", (/** @type {MouseEvent} */ event) => {
        const [px, py] = d3.pointer(event);
        const fi = ((x.invert(px) - xs[0]) / (xs[xs.length - 1] - xs[0])) * (xs.length - 1);
        const fj = ((y.invert(py) - ys[0]) / (ys[ys.length - 1] - ys[0])) * (ys.length - 1);
        showTooltip(event.clientX, event.clientY, [
          `${surface.x.name} = ${formatNumber(x.invert(px))}`,
          `${surface.y.name} = ${formatNumber(y.invert(py))}`,
          ...[response, ...constraints].map((output) => `${output.name} ≈ ${formatNumber(interpolate(output.z, fi, fj))}`),
        ]);
      })
      .on("mouseleave", hideTooltip);
  }

  /**
   * The surface in 3D, turned by dragging.
   *
   * @param {any} svg
   * @param {Surface} surface
   * @param {SurfaceOutput} response
   * @param {SurfaceOutput[]} constraints
   * @param {any} color
   * @param {number} width
   * @param {number} height
   */
  draw3d(svg, surface, response, constraints, color, width, height) {
    const d3 = /** @type {any} */ (window).d3;
    const plotWidth = width - MARGIN.right;
    const scale = Math.min(plotWidth, height) * 0.82;
    const center = [plotWidth / 2, height / 2 + 10];
    const screen = (/** @type {number} */ px, /** @type {number} */ py) => [center[0] + px * scale, center[1] + py * scale];
    const range = gridRange(response.z);
    const xs = surface.x.values;
    const ys = surface.y.values;
    const group = svg.append("g");
    const render = () => {
      group.selectAll("*").remove();
      const view = this.view;
      const point = (/** @type {number} */ u, /** @type {number} */ v, /** @type {number} */ w) => {
        const projected = project(view, u, v, w);
        return screen(projected.x, projected.y);
      };
      // The floor of the box, with the names of the axes.
      const floor = [
        [0, 0],
        [1, 0],
        [1, 1],
        [0, 1],
      ].map(([u, v]) => point(u, v, 0));
      group.append("path").attr("class", "surface-floor").attr("d", `M${floor.join("L")}Z`);
      for (const [u, v, w, text] of /** @type {[number, number, number, string][]} */ ([
        [0.5, -0.12, 0, surface.x.name],
        [-0.12, 0.5, 0, surface.y.name],
        [0, 0, 1.08, response.name],
      ])) {
        const [px, py] = point(u, v, w);
        group.append("text").attr("class", "chart-label surface-axis-label").attr("x", px).attr("y", py).text(text);
      }
      const [top0, top1] = [point(0, 0, 0), point(0, 0, 1)];
      group.append("line").attr("class", "surface-axis").attr("x1", top0[0]).attr("y1", top0[1]).attr("x2", top1[0]).attr("y2", top1[1]);
      group
        .append("g")
        .selectAll("path")
        .data(surfaceCells(response.z, view, range))
        .join("path")
        .attr("class", "surface-cell")
        .attr("d", (/** @type {{points: [number, number][]}} */ cell) => `M${cell.points.map(([px, py]) => screen(px, py)).join("L")}Z`)
        .attr("fill", (/** @type {{value: number}} */ cell) => color(cell.value));
      // The constraint boundaries laid on the surface.
      const height01 = (/** @type {number | null} */ value) => ((value ?? range[0]) - range[0]) / (range[1] - range[0]);
      const onSurface = (/** @type {[number, number]} */ [fi, fj]) =>
        point(fi / (xs.length - 1), fj / (ys.length - 1), height01(interpolate(response.z, fi, fj)));
      for (const constraint of constraints) {
        const line = isoSegments(constraint.z, 0)
          .map(([from, to]) => `M${onSurface(from)}L${onSurface(to)}`)
          .join("");
        group.append("path").attr("class", "surface-boundary").attr("d", line).append("title").text(`${constraint.name} = 0`);
      }
      // The evaluations at their computed value.
      const u = (/** @type {number | null} */ value) => ((value ?? xs[0]) - xs[0]) / (xs[xs.length - 1] - xs[0]);
      const v = (/** @type {number | null} */ value) => ((value ?? ys[0]) - ys[0]) / (ys[ys.length - 1] - ys[0]);
      group
        .append("g")
        .attr("class", "surface-samples")
        .selectAll("circle")
        // Those beyond the values of the surface would be outside the box.
        .data(
          surface.samples.evaluations
            .map((_, index) => index)
            .filter((index) => {
              const value = response.samples[index];
              return value !== null && value >= range[0] && value <= range[1];
            }),
        )
        .join("circle")
        .attr("r", 2)
        .attr("fill", "white")
        .attr("transform", (/** @type {number} */ index) => {
          const [px, py] = point(u(surface.samples.x[index]), v(surface.samples.y[index]), height01(response.samples[index]));
          return `translate(${px},${py})`;
        });
      group.append("text").attr("class", "form-hint surface-drag-hint").attr("x", 8).attr("y", height - 8).text("Drag to turn the surface");
    };
    render();
    let frame = 0;
    svg.call(
      d3.drag().on("drag", (/** @type {any} */ event) => {
        this.view = {
          azimuth: this.view.azimuth + event.dx * 0.01,
          elevation: Math.max(0.05, Math.min(1.5, this.view.elevation + event.dy * 0.01)),
        };
        if (!frame) {
          frame = requestAnimationFrame(() => {
            frame = 0;
            render();
          });
        }
      }),
    );
  }

  /**
   * The color scale of the response.
   *
   * @param {any} svg
   * @param {SurfaceOutput} response
   * @param {any} color
   * @param {[number, number]} range
   * @param {number} width
   * @param {number} height
   */
  legend(svg, response, color, range, width, height) {
    const d3 = /** @type {any} */ (window).d3;
    const barHeight = Math.min(220, height - MARGIN.top - MARGIN.bottom);
    const group = svg.append("g").attr("transform", `translate(${width - MARGIN.right + 24},${MARGIN.top + 10})`);
    const id = `surface-legend-${Math.random().toString(36).slice(2)}`;
    const gradient = svg.append("defs").append("linearGradient").attr("id", id).attr("x1", 0).attr("y1", 1).attr("x2", 0).attr("y2", 0);
    for (const offset of d3.range(0, 1.01, 0.1)) {
      gradient
        .append("stop")
        .attr("offset", offset)
        .attr("stop-color", color(range[0] + offset * (range[1] - range[0])));
    }
    group.append("rect").attr("width", 12).attr("height", barHeight).attr("fill", `url(#${id})`);
    const scale = d3.scaleLinear().domain(range).range([barHeight, 0]);
    group.append("g").attr("class", "chart-axis").attr("transform", "translate(12,0)").call(d3.axisRight(scale).ticks(5).tickFormat(d3.format(".3~g")));
    group.append("text").attr("class", "chart-label").attr("y", -6).text(response.name);
  }
}
