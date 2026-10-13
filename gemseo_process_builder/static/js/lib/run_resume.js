// @ts-check
// Which runs can be resumed from their caches (SPEC § 8.8). Pure, tested with node --test.

/** The statuses of a run that can be resumed. */
export const RESUMABLE = ["failed", "stopped", "killed"];

/**
 * Whether a run of the Runs panel offers Resume: it ended without completing
 * and its folder is still there.
 *
 * @param {{status: string, missing?: boolean}} row
 */
export function canResume(row) {
  return !row.missing && RESUMABLE.includes(row.status);
}

/**
 * How the Runs panel names a run resumed from another one.
 *
 * @param {{status: string, resumed_from?: string | null}} row
 */
export function statusText(row) {
  return row.resumed_from ? `${row.status} (resumes ${row.resumed_from})` : row.status;
}
