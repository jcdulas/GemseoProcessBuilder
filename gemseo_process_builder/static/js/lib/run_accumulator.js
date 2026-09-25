// @ts-check
// What the page keeps of a run: the events of the runner reduced to series.

/**
 * @typedef {object} IterationPoint
 * @property {number} index
 * @property {number | null} objective - The first objective.
 * @property {number | null} violation - The largest constraint violation (0 when feasible).
 * @property {boolean | null} feasible
 *
 * @typedef {object} SamplePoint
 * @property {number} index
 * @property {number[]} inputs - The first two design values.
 * @property {number | null} output - The first response.
 *
 * @typedef {{current: number, total: number | null, unit: string}} Progress
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

/**
 * Keep at most ``count`` points: in each bucket, the first, last, lowest and
 * highest values survive, so the shape of the curve is preserved.
 *
 * @template T
 * @param {T[]} points
 * @param {number} count
 * @param {(point: T) => number | null} valueOf
 * @returns {T[]}
 */
export function decimate(points, count, valueOf) {
  if (points.length <= count) {
    return points;
  }
  const buckets = Math.max(1, Math.floor(count / 4));
  const size = points.length / buckets;
  /** @type {Set<number>} */
  const kept = new Set();
  for (let bucket = 0; bucket < buckets; bucket += 1) {
    const start = Math.floor(bucket * size);
    const end = Math.min(points.length, Math.floor((bucket + 1) * size));
    kept.add(start).add(end - 1);
    let lowest = { index: -1, value: Number.POSITIVE_INFINITY };
    let highest = { index: -1, value: Number.NEGATIVE_INFINITY };
    for (let index = start; index < end; index += 1) {
      const value = valueOf(points[index]);
      if (value !== null && value < lowest.value) {
        lowest = { index, value };
      }
      if (value !== null && value > highest.value) {
        highest = { index, value };
      }
    }
    for (const extreme of [lowest, highest]) {
      if (extreme.index >= 0) {
        kept.add(extreme.index);
      }
    }
  }
  return [...kept].sort((a, b) => a - b).map((index) => points[index]);
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
    });
    if (this.samples.length > this.maxPoints) {
      this.samples = decimate(this.samples, this.maxPoints / 2, (point) => point.output);
    }
  }
}
