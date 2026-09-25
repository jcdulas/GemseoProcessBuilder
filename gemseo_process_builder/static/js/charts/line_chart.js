// @ts-check
// Line charts of series against the evaluation number, with a hover readout.
import { el } from "../components/dom.js";
import { canUseLog, extent, linearDomain, logDomain } from "../lib/chart_scales.js";
import { decimate } from "../lib/run_accumulator.js";
import { MARGIN, drawAxes, formatNumber } from "./axis.js";
import { legend } from "./legend.js";
import { hideTooltip, showTooltip } from "./tooltip.js";

/** Points drawn at most per series. */
const MAX_DRAWN = 2000;

/**
 * @typedef {object} Series
 * @property {string} name
 * @property {string} color
 * @property {{x: number, y: number | null}[]} points
 * @property {boolean} [dashed]
 *
 * @typedef {object} LineChartOptions
 * @property {string} title
 * @property {Series[]} series
 * @property {string} [xLabel]
 * @property {boolean} [log] - Use a log scale when the values allow it.
 * @property {{value: number, label: string}[]} [thresholds] - Horizontal reference lines.
 * @property {[number, number]} [yDomain] - A fixed domain, like [0, 1].
 */

export class LineChart {
  /** @param {HTMLElement} container */
  constructor(container) {
    this.root = el("div.line-chart");
    this.header = el("div.chart-header");
    this.plot = el("div.chart-plot");
    this.root.append(this.header, this.plot);
    container.append(this.root);
    /** @type {LineChartOptions | null} */
    this.options = null;
    this.scheduled = false;
    new ResizeObserver(() => this.schedule()).observe(this.plot);
  }

  /** @param {LineChartOptions} options */
  update(options) {
    this.options = options;
    this.schedule();
  }

  schedule() {
    if (!this.scheduled) {
      this.scheduled = true;
      requestAnimationFrame(() => {
        this.scheduled = false;
        this.render();
      });
    }
  }

  render() {
    const options = this.options;
    if (!options) {
      return;
    }
    const d3 = /** @type {any} */ (window).d3;
    const allValues = options.series.flatMap((series) => series.points.map((point) => point.y));
    const log = Boolean(options.log) && canUseLog(allValues);
    const title = el("span.chart-title-text", {
      text: options.log && !log ? `${options.title} (linear: some values are not positive)` : options.title,
    });
    this.header.replaceChildren(
      title,
      options.series.length > 1 ? legend(options.series.map(({ name, color, dashed }) => ({ label: name, color, dashed }))) : "",
    );
    d3.select(this.plot).selectAll("svg").remove();
    const width = this.plot.clientWidth;
    const height = this.plot.clientHeight;
    if (width < 80 || height < 60) {
      return;
    }
    const innerWidth = width - MARGIN.left - MARGIN.right;
    const innerHeight = height - MARGIN.top - MARGIN.bottom;
    const xs = options.series.flatMap((series) => series.points.map((point) => point.x));
    const [firstX, lastX] = xs.length ? extent(xs) : [1, 2];
    const x = d3.scaleLinear().domain([firstX, Math.max(lastX, firstX + 1)]).range([0, innerWidth]);
    const domain = options.yDomain ?? (log ? logDomain(allValues) : linearDomain([...allValues, ...(options.thresholds ?? []).map((t) => t.value)]));
    const y = (log ? d3.scaleLog() : d3.scaleLinear()).domain(domain).range([innerHeight, 0]);
    if (!log && !options.yDomain) {
      y.nice();
    }
    const svg = d3.select(this.plot).append("svg").attr("width", width).attr("height", height);
    const group = svg.append("g").attr("transform", `translate(${MARGIN.left},${MARGIN.top})`);
    drawAxes(group, x, y, { width: innerWidth, height: innerHeight, xLabel: options.xLabel, integerX: true, log });

    for (const threshold of options.thresholds ?? []) {
      if (!log || threshold.value > 0) {
        const at = y(threshold.value);
        group.append("line").attr("class", "chart-threshold").attr("x1", 0).attr("x2", innerWidth).attr("y1", at).attr("y2", at);
        group.append("text").attr("class", "chart-threshold-label").attr("x", innerWidth - 4).attr("y", at - 4).attr("text-anchor", "end").text(threshold.label);
      }
    }
    const line = d3
      .line()
      .defined((/** @type {any} */ point) => point.y !== null && (!log || point.y > 0))
      .x((/** @type {any} */ point) => x(point.x))
      .y((/** @type {any} */ point) => y(point.y));
    for (const series of options.series) {
      const drawn = decimate(series.points, MAX_DRAWN, (point) => point.y);
      group
        .append("path")
        .datum(drawn)
        .attr("class", `chart-line${series.dashed ? " dashed" : ""}`)
        .attr("stroke", series.color)
        .attr("d", line);
    }
    this.installReadout(group, x, y, innerWidth, innerHeight, options.series);
  }

  /**
   * A vertical rule following the pointer, with the values of every series.
   *
   * @param {any} group
   * @param {any} x
   * @param {any} y
   * @param {number} width
   * @param {number} height
   * @param {Series[]} seriesList
   */
  installReadout(group, x, y, width, height, seriesList) {
    const d3 = /** @type {any} */ (window).d3;
    const rule = group.append("line").attr("class", "chart-rule").attr("y1", 0).attr("y2", height).style("display", "none");
    const dots = seriesList.map((series) =>
      group.append("circle").attr("class", "chart-dot").attr("r", 3.5).attr("fill", series.color).style("display", "none"),
    );
    group
      .append("rect")
      .attr("class", "chart-overlay")
      .attr("width", width)
      .attr("height", height)
      .on("mousemove", (/** @type {MouseEvent} */ event) => {
        const [mouseX] = d3.pointer(event);
        const target = x.invert(mouseX);
        const lines = [];
        let shownX = null;
        seriesList.forEach((series, index) => {
          const nearest = d3.least(series.points, (/** @type {any} */ point) => Math.abs(point.x - target));
          if (!nearest || nearest.y === null) {
            dots[index].style("display", "none");
            return;
          }
          shownX = nearest.x;
          dots[index].style("display", null).attr("cx", x(nearest.x)).attr("cy", y(nearest.y));
          lines.push({ text: `${series.name}: ${formatNumber(nearest.y)}`, color: series.color });
        });
        if (shownX === null) {
          return;
        }
        rule.style("display", null).attr("x1", x(shownX)).attr("x2", x(shownX));
        showTooltip(event.clientX, event.clientY, [`Evaluation ${shownX}`, ...lines]);
      })
      .on("mouseleave", () => {
        rule.style("display", "none");
        for (const dot of dots) {
          dot.style("display", "none");
        }
        hideTooltip();
      });
  }
}
