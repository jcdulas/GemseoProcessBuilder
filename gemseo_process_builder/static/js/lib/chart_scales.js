// @ts-check
// Scale domains and tick counts for charts.

/**
 * The finite numbers of a list.
 *
 * @param {(number | null | undefined)[]} values
 * @returns {number[]}
 */
export function finite(values) {
  return /** @type {number[]} */ (values.filter((value) => typeof value === "number" && Number.isFinite(value)));
}

/**
 * The lowest and highest values (a loop: spreading long arrays overflows the stack).
 *
 * @param {number[]} numbers - Not empty.
 * @returns {[number, number]}
 */
export function extent(numbers) {
  let low = numbers[0];
  let high = numbers[0];
  for (const value of numbers) {
    if (value < low) {
      low = value;
    } else if (value > high) {
      high = value;
    }
  }
  return [low, high];
}

/**
 * A linear domain covering the values; a constant series gets a margin so it
 * is drawn in the middle instead of on an axis.
 *
 * @param {(number | null | undefined)[]} values
 * @returns {[number, number]}
 */
export function linearDomain(values) {
  const numbers = finite(values);
  if (!numbers.length) {
    return [0, 1];
  }
  const [low, high] = extent(numbers);
  if (low === high) {
    const margin = low === 0 ? 1 : Math.abs(low) * 0.1;
    return [low - margin, high + margin];
  }
  return [low, high];
}

/**
 * Whether a log scale can show the values: they must all be positive.
 *
 * @param {(number | null | undefined)[]} values
 */
export function canUseLog(values) {
  const numbers = finite(values);
  return numbers.length > 0 && numbers.every((value) => value > 0);
}

/**
 * A log domain, or ``null`` when some values are zero or negative.
 *
 * @param {(number | null | undefined)[]} values
 * @returns {[number, number] | null}
 */
export function logDomain(values) {
  if (!canUseLog(values)) {
    return null;
  }
  const numbers = finite(values);
  const [low, high] = extent(numbers);
  return low === high ? [low / 10, high * 10] : [low, high];
}

/**
 * About one tick every 80 pixels, between 2 and 10.
 *
 * @param {number} pixels
 */
export function tickCount(pixels) {
  return Math.max(2, Math.min(10, Math.round(pixels / 80)));
}
