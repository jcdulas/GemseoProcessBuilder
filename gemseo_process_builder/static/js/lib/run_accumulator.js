// @ts-check
// What the page keeps of a run: the events of the runner reduced to series.
import { decimate } from "./decimate.js";

/**
 * @typedef {object} IterationPoint
 * @property {number} index
 * @property {number | null} objective - The first objective.
 * @property {number | null} violation - The largest constraint violation (0 when feasible).
 * @property {boolean | null} feasible
 * @property {Record<string, number | null>} values - Every value, by column name (``x[1]``).
 *
 * @typedef {object} SamplePoint
 * @property {number} index
 * @property {number[]} inputs - The first two design values.
 * @property {number | null} output - The first response.
 * @property {Record<string, number | null>} values - Every value, by column name.
 *
 * @typedef {{current: number, total: number | null, unit: string, processes?: number}} Progress
 */

/**
 * The first number of a value (a vector gives its first element).
 *
 * @param {any} value
 * @returns {number | null}
 */
function firstNumber(value) {
  const item = Array.isArray(value) ? value[0] : value;
  return typeof item === "number" && Number.isFinite(item) ? item : null;
}

/**
 * Values by column name, as in the results table: vectors give ``x[0]``, ``x[1]``…
 * and one-element vectors keep the variable name.
 *
 * @param {...Record<string, any>} groups
 * @returns {Record<string, number | null>}
 */
export function flatten(...groups) {
  /** @type {Record<string, number | null>} */
  const values = {};
  for (const group of groups) {
    for (const [name, value] of Object.entries(group ?? {})) {
      if (Array.isArray(value) && value.length === 1) {
        values[name] = typeof value[0] === "number" ? value[0] : null;
      } else if (Array.isArray(value)) {
        value.forEach((item, index) => {
          values[`${name}[${index}]`] = typeof item === "number" ? item : null;
        });
      } else {
        values[name] = typeof value === "number" ? value : null;
      }
    }
  }
  return values;
}

/**
 * The largest violation of inequality (``g <= 0``) and equality (``h = 0``) constraints.
 *
 * @param {Record<string, any>} g
 * @param {Record<string, any>} h
 * @returns {number | null}
 */
export function maxViolation(g, h) {
  const values = [
    ...Object.values(g ?? {}).flat().map((value) => (typeof value === "number" ? Math.max(value, 0) : null)),
    ...Object.values(h ?? {}).flat().map((value) => (typeof value === "number" ? Math.abs(value) : null)),
  ];
  if (!values.length) {
    return null;
  }
  return values.includes(null) ? null : Math.max(.../** @type {number[]} */ (values));
}

/** The events of one run, reduced to what the live views show. */
export class RunAccumulator {
  /**
   * @param {{maxPoints?: number}} [options] - Points kept in memory; beyond,
   *   the stored series are decimated to half this size.
   */
  constructor({ maxPoints = 100_000 } = {}) {
    this.maxPoints = maxPoints;
    /** @type {IterationPoint[]} */
    this.iterations = [];
    /** @type {SamplePoint[]} */
    this.samples = [];
    /** @type {Progress | null} */
    this.progress = null;
    /** @type {Map<string, {name: string, current: number}>} - Iterations of the
     * current run of each nested scenario, by driver id. */
    this.inner = new Map();
    /** @type {string} - The nested scenario reported last. */
    this.lastInner = "";
    /** @type {Map<string, import("./status_aggregation.js").RunState>} */
    this.states = new Map();
    /** @type {string[]} */
    this.inputNames = [];
    this.outputName = "";
    this.objectiveName = "";
  }

  /**
   * Apply one event of the runner (``batch`` events are unpacked).
   *
   * @param {string} event
   * @param {any} payload
   */
  apply(event, payload) {
    if (event === "batch") {
      for (const item of payload.items ?? []) {
        if (!("dropped" in item)) {
          this.apply(payload.event, item);
        }
      }
    } else if (event === "status") {
      this.states.set(payload.node_id, payload.state);
    } else if (event === "progress") {
      this.progress = payload;
    } else if (event === "inner_progress") {
      this.inner.set(payload.node_id, { name: payload.name, current: payload.current });
      this.lastInner = payload.node_id;
    } else if (event === "iteration") {
      this.addIteration(payload);
    } else if (event === "sample") {
      this.addSample(payload);
    }
  }

  /** @param {any} payload */
  addIteration(payload) {
    const [name, value] = Object.entries(payload.f ?? {})[0] ?? ["", null];
    this.objectiveName ||= name;
    this.iterations.push({
      index: payload.index,
      objective: firstNumber(value),
      violation: maxViolation(payload.g, payload.h),
      feasible: payload.feasible ?? null,
      values: flatten(payload.x, payload.f, payload.g, payload.h, payload.observables),
    });
    if (this.iterations.length > this.maxPoints) {
      this.iterations = decimate(this.iterations, this.maxPoints / 2, (point) => point.objective);
    }
  }

  /** @param {any} payload */
  addSample(payload) {
    const inputs = Object.entries(payload.inputs ?? {}).slice(0, 2);
    if (!this.inputNames.length) {
      this.inputNames = inputs.map(([name]) => name);
    }
    const [name, value] = Object.entries(payload.outputs ?? {})[0] ?? ["", null];
    this.outputName ||= name;
    this.samples.push({
      index: payload.index,
      inputs: inputs.map(([, input]) => firstNumber(input) ?? Number.NaN),
      output: firstNumber(value),
      values: flatten(payload.inputs, payload.outputs),
    });
    if (this.samples.length > this.maxPoints) {
      this.samples = decimate(this.samples, this.maxPoints / 2, (point) => point.output);
    }
  }
}
