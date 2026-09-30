// @ts-check
// Axes, labels and colors shared by the charts.
import { tickCount } from "../lib/chart_scales.js";

/** Space around the plotting area, for the axes and their labels. */
export const MARGIN = { top: 22, right: 18, bottom: 34, left: 60 };

const SERIES_TOKENS = [
  "--color-accent",
  "--color-driver-optimization",
  "--color-driver-doe",
  "--color-driver-mda",
  "--color-driver-parametric",
  "--color-success",
  "--color-error",
  "--color-assembly",
];

/** @param {string} name */
export function cssColor(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

/**
 * A color for the ``index``-th series, from the tokens of the theme.
 *
 * @param {number} index
 */
export function seriesColor(index) {
  return cssColor(SERIES_TOKENS[index % SERIES_TOKENS.length]);
}

/** A compact number format for ticks and readouts. */
export function formatNumber(/** @type {number | null | undefined} */ value) {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return "–";
  }
  const d3 = /** @type {any} */ (window).d3;
  return d3.format(".4~g")(value);
}

/**
 * Draw the axes of a plotting area.
 *
 * @param {any} group - d3 selection translated to the plotting area.
 * @param {any} x - d3 scale.
 * @param {any} y - d3 scale.
 * @param {{width: number, height: number, xLabel?: string, yLabel?: string, integerX?: boolean, log?: boolean}} options
 */
export function drawAxes(group, x, y, { width, height, xLabel = "", yLabel = "", integerX = false, log = false }) {
  const d3 = /** @type {any} */ (window).d3;
  const xAxis = d3.axisBottom(x).ticks(tickCount(width));
  if (integerX) {
    // Only whole ticks: a short history would repeat "1, 2, 2, 3…".
    xAxis.tickValues(x.ticks(tickCount(width)).filter(Number.isInteger)).tickFormat(d3.format("d"));
  }
  const yAxis = d3.axisLeft(y).ticks(tickCount(height), log ? "~g" : undefined);
  if (!log) {
    yAxis.tickFormat(d3.format(".3~g"));
  }
  group.append("g").attr("class", "chart-axis").attr("transform", `translate(0,${height})`).call(xAxis);
  group.append("g").attr("class", "chart-axis").call(yAxis);
  group
    .append("g")
    .attr("class", "chart-grid")
    .call(d3.axisLeft(y).ticks(tickCount(height)).tickSize(-width).tickFormat(""));
  if (xLabel) {
    group.append("text").attr("class", "chart-label").attr("x", width).attr("y", height + 30).attr("text-anchor", "end").text(xLabel);
  }
  if (yLabel) {
    group.append("text").attr("class", "chart-label").attr("x", 0).attr("y", -8).text(yLabel);
  }
}
