// @ts-check
// Rows of a large table, fetched page by page as the user scrolls.

export class PagedRows {
  /** @param {number} [pageSize] */
  constructor(pageSize = 200) {
    this.pageSize = pageSize;
    /** @type {Map<number, any[][]>} */
    this.pages = new Map();
    /** @type {Set<number>} */
    this.loading = new Set();
    /** Rows matching the query; unknown until the first page arrives. */
    this.total = /** @type {number | null} */ (null);
    this.queryKey = "";
  }

  /**
   * Change the sort or the filters: every page must be fetched again.
   *
   * @param {string} key - Identifies the query (sort, filters, columns).
   * @returns {boolean} Whether the query changed.
   */
  setQuery(key) {
    if (key === this.queryKey) {
      return false;
    }
    this.queryKey = key;
    this.clear();
    return true;
  }

  /** Forget every page (the results changed). */
  clear() {
    this.pages.clear();
    this.loading.clear();
    this.total = null;
  }

  /**
   * The pages to fetch to show rows ``first`` to ``last``, with one page ahead
   * each way; pages already here or on their way are left out.
   *
   * @param {number} first
   * @param {number} last
   * @returns {number[]}
   */
  missing(first, last) {
    const lastPage = this.total === null ? Number.POSITIVE_INFINITY : Math.max(0, Math.ceil(this.total / this.pageSize) - 1);
    const from = Math.max(0, Math.floor(first / this.pageSize) - 1);
    const to = Math.min(lastPage, Math.floor(Math.max(first, last) / this.pageSize) + 1);
    const pages = [];
    for (let page = from; page <= to; page += 1) {
      if (!this.pages.has(page) && !this.loading.has(page)) {
        pages.push(page);
      }
    }
    return pages;
  }

  /** @param {number} page */
  markLoading(page) {
    this.loading.add(page);
  }

  /**
   * Keep a page received for a query; ignored if the query changed meanwhile.
   *
   * @param {string} queryKey
   * @param {number} page
   * @param {any[][]} rows
   * @param {number} total
   */
  store(queryKey, page, rows, total) {
    if (queryKey !== this.queryKey) {
      return false;
    }
    this.loading.delete(page);
    this.pages.set(page, rows);
    this.total = total;
    return true;
  }

  /**
   * A row, or ``undefined`` while its page is not here.
   *
   * @param {number} index
   */
  row(index) {
    return this.pages.get(Math.floor(index / this.pageSize))?.[index % this.pageSize];
  }
}
