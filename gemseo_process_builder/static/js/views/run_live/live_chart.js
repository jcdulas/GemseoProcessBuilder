// @ts-check
// Live charts of a run: convergence of an optimization, samples of a DOE.
import { el } from "../../components/dom.js";
import { decimate } from "../../lib/run_accumulator.js";

/** Points drawn at most per curve; the stored history can be longer. */
const MAX_DRAWN = 2000;

/** Points drawn at most in a scatter plot, taken at regular intervals. */
const MAX_SCATTERED = 5000;
const MARGIN = { top: 12, right: 16, bottom: 30, left: 56 };

/** @param {string} name */
function cssColor(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

/**
 * A line chart of ``value`` against ``index``, drawn into an SVG group.
 *
 * @param {any} svg - d3 selection of the SVG.
 * @param {{index: number, value: number | null}[]} points
 * @param {{width: number, height: number, top: number, title: string, color: string}} frame
 */
function lineChart(svg, points, { width, height, top, title, color }) {
  const d3 = /** @type {any} */ (window).d3;
  const drawn = decimate(points, MAX_DRAWN, (point) => point.value).filter((point) => point.value !== null);
  const group = svg.append("g").attr("transform", `translate(${MARGIN.left},${top + MARGIN.top})`);
  const innerWidth = width - MARGIN.left - MARGIN.right;
  const innerHeight = height - MARGIN.top - MARGIN.bottom;
  const x = d3
    .scaleLinear()
    .domain([1, Math.max(2, d3.max(drawn, (/** @type {any} */ point) => point.index) ?? 2)])
    .range([0, innerWidth]);
  const y = d3
    .scaleLinear()
    .domain(d3.extent(drawn, (/** @type {any} */ point) => point.value).map((/** @type {any} */ v) => v ?? 0))
    .nice()
    .range([innerHeight, 0]);
  group.append("g").attr("class", "chart-axis").attr("transform", `translate(0,${innerHeight})`).call(d3.axisBottom(x).ticks(6).tickFormat(d3.format("d")));
  group.append("g").attr("class", "chart-axis").call(d3.axisLeft(y).ticks(5).tickFormat(d3.format(".3~g")));
  group.append("text").attr("class", "chart-title").attr("x", 0).attr("y", -2).text(title);
  if (!drawn.length) {
    return;
  }
  group
    .append("path")
    .datum(drawn)
    .attr("class", "chart-line")
    .attr("stroke", color)
    .attr(
      "d",
      d3
        .line()
        .x((/** @type {any} */ point) => x(point.index))
        .y((/** @type {any} */ point) => y(point.value)),
    );
  const last = drawn.at(-1);
  group
    .append("circle")
    .attr("class", "chart-last")
    .attr("fill", color)
    .attr("r", 3.5)
    .attr("cx", x(last.index))
    .attr("cy", y(last.value))
    .append("title")
    .text(`${title} at ${last.index}: ${d3.format(".6~g")(last.value)}`);
}

/**
 * A scatter plot of the first two inputs, colored by the first response.
 *
 * @param {any} svg
 * @param {import("../../lib/run_accumulator.js").RunAccumulator} data
 * @param {{width: number, height: number}} frame
 */
function scatterChart(svg, data, { width, height }) {
  const d3 = /** @type {any} */ (window).d3;
  const step = Math.ceil(data.samples.length / MAX_SCATTERED);
  const points = data.samples.filter((point, index) => index % step === 0 && point.inputs.every(Number.isFinite));
  const group = svg.append("g").attr("transform", `translate(${MARGIN.left},${MARGIN.top + 8})`);
  const innerWidth = width - MARGIN.left - MARGIN.right;
  const innerHeight = height - MARGIN.top - MARGIN.bottom - 8;
  const [xName, yName] = data.inputNames;
  const twoInputs = data.inputNames.length > 1;
  const xOf = (/** @type {any} */ point) => point.inputs[0];
  const yOf = (/** @type {any} */ point) => (twoInputs ? point.inputs[1] : point.output);
  const x = d3.scaleLinear().domain(d3.extent(points, xOf)).nice().range([0, innerWidth]);
  const y = d3.scaleLinear().domain(d3.extent(points, yOf)).nice().range([innerHeight, 0]);
  const range = d3.extent(points, (/** @type {any} */ point) => point.output);
  const color = d3
    .scaleSequential(d3.interpolateRgb(cssColor("--color-accent-soft"), cssColor("--color-accent")))
    .domain(range);
  const legend = range[0] === undefined ? "" : ` (light ${d3.format(".3~g")(range[0])} to dark ${d3.format(".3~g")(range[1])})`;
  group.append("g").attr("class", "chart-axis").attr("transform", `translate(0,${innerHeight})`).call(d3.axisBottom(x).ticks(6));
  group.append("g").attr("class", "chart-axis").call(d3.axisLeft(y).ticks(5).tickFormat(d3.format(".3~g")));
  group.append("text").attr("class", "chart-title").attr("x", 0).attr("y", -6).text(
    twoInputs ? `${yName} against ${xName}, colored by ${data.outputName}${legend}` : `${data.outputName} against ${xName}`,
  );
  group
    .selectAll("circle")
    .data(points)
    .join("circle")
    .attr("class", "chart-point")
    .attr("r", 3)
    .attr("cx", (/** @type {any} */ point) => x(xOf(point)))
    .attr("cy", (/** @type {any} */ point) => y(yOf(point)))
    .attr("fill", (/** @type {any} */ point) => (point.output === null ? "none" : color(point.output)));
}

export class LiveChart {
  /**
   * @param {HTMLElement} root
   * @param {import("../../services/run_state.js").RunStates} runStates
   * @param {string} runId
   */
  constructor(root, runStates, runId) {
    this.runStates = runStates;
    this.runId = runId;
    this.summary = el("div.live-summary");
    this.chart = el("div.live-chart");
    root.classList.add("live-page");
    root.replaceChildren(this.summary, this.chart);
    runStates.onChange((record) => {
      if (record.info.id === runId && root.isConnected) {
        this.render();
      }
    });
    new ResizeObserver(() => this.render()).observe(this.chart);
    this.render();
  }

  render() {
    const record = this.runStates.runs.get(this.runId);
    if (!record) {
      return;
    }
    const { data, info } = record;
    const progress = data.progress;
    const count = progress ? `${progress.current}${progress.total ? ` / ${progress.total}` : ""} ${progress.unit}s` : "";
    const best = data.iterations.reduce(
      (/** @type {number | null} */ lowest, point) =>
        point.objective !== null && point.feasible !== false && (lowest === null || point.objective < lowest) ? point.objective : lowest,
      null,
    );
    const parts = [
      el("strong", { text: info.driver_name }),
      el(`span.run-${info.status}`, { text: ` ${info.status}` }),
    ];
    if (count) {
      parts.push(el("span", { text: ` · ${count}` }));
    }
    if (best !== null) {
      parts.push(el("span", { text: ` · best feasible ${data.objectiveName} = ${best.toPrecision(6)}` }));
    }
    this.summary.replaceChildren(...parts);
    const width = this.chart.clientWidth;
    const height = this.chart.clientHeight;
    const d3 = /** @type {any} */ (window).d3;
    d3.select(this.chart).selectAll("svg").remove();
    if (width < 50 || height < 50) {
      return;
    }
    const svg = d3.select(this.chart).append("svg").attr("width", width).attr("height", height);
    if (data.iterations.length) {
      const constrained = data.iterations.some((point) => point.violation !== null);
      const half = constrained ? Math.floor(height / 2) : height;
      lineChart(svg, data.iterations.map((point) => ({ index: point.index, value: point.objective })), {
        width,
        height: half,
        top: 0,
        title: `Objective ${data.objectiveName}`,
        color: cssColor("--color-accent"),
      });
      if (constrained) {
        lineChart(svg, data.iterations.map((point) => ({ index: point.index, value: point.violation })), {
          width,
          height: height - half,
          top: half,
          title: "Largest constraint violation",
          color: cssColor("--color-warning"),
        });
      }
    } else if (data.samples.length) {
      scatterChart(svg, data, { width, height });
    } else {
      svg
        .append("text")
        .attr("class", "chart-empty")
        .attr("x", width / 2)
        .attr("y", height / 2)
        .text(info.status === "preparing" ? "Checking the script…" : "Waiting for the first results…");
    }
  }
}
