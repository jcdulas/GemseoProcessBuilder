// @ts-check
// Where the Results views take their data: the live events of a run, or the
// results read by the worker once the run is over.
import { app } from "../../app.js";
import { boundsByColumn } from "../../lib/normalize.js";
import { DEFAULT_FILTER, applyFilter, needsRanking, rankingQuery } from "../../lib/results_filter.js";

/**
 * Beyond this number of columns, the values of a column are read when a view
 * shows it: a run can have hundreds of thousands of variables.
 */
const LOADED_COLUMNS = 400;

/**
 * The columns read with the run when it has many: the responses, then the
 * first design variables.
 *
 * @param {ResultColumn[]} columns
 */
function firstColumns(columns) {
  if (columns.length <= LOADED_COLUMNS) {
    return columns.map((column) => column.name);
  }
  const responses = columns.filter((column) => column.role !== "design variable").slice(0, LOADED_COLUMNS / 2);
  const designs = columns.filter((column) => column.role === "design variable").slice(0, LOADED_COLUMNS - responses.length);
  return [...responses, ...designs].map((column) => column.name);
}

/**
 * @typedef {object} ResultColumn
 * @property {string} name - Like ``x_shared[1]``.
 * @property {string} variable
 * @property {string} role - design variable, objective, constraint, observable, output…
 * @property {"eq" | "ineq" | null} [constraintType]
 */

/**
 * Roles of the variables of a running driver, from its configuration.
 *
 * @param {any} driver - The driver node of the store.
 * @returns {Map<string, {role: string, constraintType: "eq" | "ineq" | null}>}
 */
function rolesFromDriver(driver) {
  const config = driver?.config ?? {};
  /** @type {Map<string, {role: string, constraintType: "eq" | "ineq" | null}>} */
  const roles = new Map();
  for (const variable of config.design_space ?? []) {
    roles.set(variable.variable, { role: "design variable", constraintType: null });
  }
  for (const level of config.levels ?? []) {
    roles.set(level.variable, { role: "design variable", constraintType: null });
  }
  for (const objective of config.objectives ?? []) {
    roles.set(objective.variable, { role: "objective", constraintType: null });
    // GEMSEO minimizes the opposite of a maximized objective, named "-y".
    roles.set(`-${objective.variable}`, { role: "objective", constraintType: null });
  }
  for (const constraint of config.constraints ?? []) {
    roles.set(constraint.variable, { role: "constraint", constraintType: constraint.type ?? "ineq" });
  }
  for (const name of config.observables ?? []) {
    roles.set(name, { role: "observable", constraintType: null });
  }
  for (const name of config.responses ?? []) {
    roles.set(name, { role: "output", constraintType: null });
  }
  return roles;
}

/** @param {string} name */
function variableOf(name) {
  return name.replace(/\[\d+\]$/, "");
}

export class ResultsSource {
  /** @param {string} runId */
  constructor(runId) {
    this.runId = runId;
    /** @type {any} - ``run.json``. */
    this.info = null;
    /** @type {ResultColumn[]} */
    this.columns = [];
    /** @type {number[]} */
    this.evaluations = [];
    /** @type {Record<string, (number | null)[]>} */
    this.values = {};
    /** @type {Map<string, {lower: number | null, upper: number | null}>} */
    this.bounds = new Map();
    this.error = "";
    /** @type {Map<string, Promise<any>>} */
    this.matrices = new Map();
    /** @type {import("../../lib/results_filter.js").FilterState} - The variables the views show. */
    this.filter = { ...DEFAULT_FILTER };
    /** @type {Map<string, Promise<import("../../lib/results_filter.js").Ranking>>} */
    this.rankings = new Map();
  }

  /**
   * The ranking of the variables the filter needs, or ``null``.
   *
   * @returns {Promise<import("../../lib/results_filter.js").Ranking | null>}
   */
  async ranking() {
    if (!needsRanking(this.filter) || this.live) {
      return null;
    }
    return this.rankingOf(rankingQuery(this.filter));
  }

  /**
   * A ranking of the variables, cached until the results change.
   *
   * @param {ReturnType<typeof rankingQuery>} query
   * @returns {Promise<import("../../lib/results_filter.js").Ranking>}
   */
  rankingOf(query) {
    const key = JSON.stringify(query);
    if (!this.rankings.has(key)) {
      const promise = app.api.call("results.ranking", { id: this.runId, ...query }, { timeout: 300_000 });
      promise.catch(() => this.rankings.delete(key));
      this.rankings.set(key, promise);
    }
    return /** @type {Promise<any>} */ (this.rankings.get(key));
  }

  /**
   * The design variables and responses the views show, by the filter.
   *
   * @returns {Promise<import("../../lib/results_filter.js").FilterResult & {ranking: any, error: string}>}
   */
  async focus() {
    try {
      const ranking = await this.ranking();
      return { ...applyFilter(this.columns, this.filter, ranking), ranking, error: "" };
    } catch (error) {
      const all = applyFilter(this.columns, { ...this.filter, mode: "all", constraints: "all" }, null);
      return { ...all, ranking: null, error: String(/** @type {any} */ (error)?.message ?? error) };
    }
  }

  /**
   * Read the values of columns not read yet (a run with many columns).
   *
   * @param {string[]} names
   */
  async ensure(names) {
    const missing = names.filter((name) => !(name in this.values) && this.columns.some((column) => column.name === name));
    if (!missing.length || this.live) {
      return;
    }
    const history = await app.api.call("results.history", { id: this.runId, names: missing }, { timeout: 120_000 });
    Object.assign(this.values, history.values);
  }

  /**
   * Some columns of every evaluation (of 5,000 evenly spaced ones beyond),
   * for the charts drawing points; cached until the results change.
   *
   * @param {string[]} names
   * @returns {Promise<{total: number, evaluations: number[], columns: Record<string, (number | null)[]>}>}
   */
  matrix(names) {
    const key = JSON.stringify(names);
    if (!this.matrices.has(key)) {
      this.matrices.set(
        key,
        app.api.call("results.matrix", { id: this.runId, names, max_rows: 5000 }, { timeout: 120_000 }),
      );
    }
    return /** @type {Promise<any>} */ (this.matrices.get(key));
  }

  /** The live record of the run, while it runs in this session. */
  liveRecord() {
    const record = app.runStates.runs.get(this.runId);
    return record && app.runStates.isActive(record) ? record : null;
  }

  get live() {
    return this.liveRecord() !== null;
  }

  /** Refresh from the live events, or load from the worker once finished. */
  async load() {
    const record = this.liveRecord();
    if (record) {
      this.loadLive(record);
      return;
    }
    await this.loadFinished();
  }

  /** @param {import("../../services/run_state.js").RunRecord} record */
  loadLive(record) {
    this.info = record.info;
    const driver = app.store.node(record.info.driver);
    const roles = rolesFromDriver(driver);
    const points = record.data.iterations.length ? record.data.iterations : record.data.samples;
    /** @type {Set<string>} */
    const names = new Set();
    for (const point of points) {
      for (const name of Object.keys(point.values)) {
        names.add(name);
      }
    }
    this.columns = [...names].map((name) => {
      const known = roles.get(variableOf(name));
      return {
        name,
        variable: variableOf(name),
        role: known?.role ?? "output",
        constraintType: known?.constraintType ?? null,
      };
    });
    this.evaluations = points.map((point) => point.index);
    this.values = Object.fromEntries(this.columns.map((column) => [column.name, points.map((point) => point.values[column.name] ?? null)]));
    this.bounds = boundsByColumn(driver?.config?.design_space ?? []);
  }

  async loadFinished() {
    this.error = "";
    this.matrices.clear();
    this.rankings.clear();
    try {
      const [summary, columns] = await Promise.all([
        app.api.call("results.summary", { id: this.runId }, { timeout: 120_000 }),
        app.api.call("results.columns", { id: this.runId }, { timeout: 120_000 }),
      ]);
      this.info = summary;
      const types = new Map(
        (summary.variables ?? []).map((/** @type {any} */ variable) => [variable.name, variable.constraint_type ?? null]),
      );
      this.columns = columns
        .filter((/** @type {any} */ column) => column.role !== "index")
        .map((/** @type {any} */ column) => ({
          name: column.name,
          variable: column.variable,
          role: column.role,
          constraintType: types.get(column.variable) ?? null,
        }));
      const history = await app.api.call(
        "results.history",
        { id: this.runId, names: firstColumns(this.columns) },
        { timeout: 120_000 },
      );
      this.evaluations = history.evaluation;
      this.values = history.values;
      this.bounds = boundsByColumn(
        (summary.variables ?? [])
          .filter((/** @type {any} */ variable) => variable.role === "design variable")
          .map((/** @type {any} */ variable) => ({ ...variable, variable: variable.name })),
      );
    } catch (error) {
      this.error = String(/** @type {any} */ (error)?.message ?? error);
      this.info ??= (await app.api.call("runs.list")).runs.find((/** @type {any} */ run) => run.id === this.runId) ?? null;
    }
  }

  /**
   * The columns with a role.
   *
   * @param {string} role
   */
  byRole(role) {
    return this.columns.filter((column) => column.role === role && column.name !== "feasible");
  }

  /**
   * The points of a column against the evaluation number.
   *
   * @param {string} name
   * @param {(value: number | null) => number | null} [transform]
   */
  points(name, transform = (value) => value) {
    const values = this.values[name] ?? [];
    return this.evaluations.map((x, index) => ({ x, y: transform(values[index] ?? null) }));
  }
}
