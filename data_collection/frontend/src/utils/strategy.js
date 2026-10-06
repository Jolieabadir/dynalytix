/**
 * Strategy-lens helpers shared by the prep MoveForm and the rater's
 * RaterMoveForm (both render LensFields.StrategyLens).
 */

/**
 * Form quality anchor text. Not taxonomy — these are scale anchors for a
 * 1-5 rating, and the backend stores the number.
 */
export const FORM_QUALITY_LABELS = {
  1: 'Failed',
  2: 'Clear compensation',
  3: 'Acceptable',
  4: 'Efficient/repeatable',
  5: 'Excellent, repeatable under greater demand',
};

/**
 * Toggle one move tag, keeping no_hands and no_feet_on mutually exclusive.
 * @param {string[]} prev
 * @param {string} tag
 * @returns {string[]}
 */
export function toggleMoveTagValue(prev, tag) {
  if (prev.includes(tag)) return prev.filter((t) => t !== tag);
  let next = [...prev, tag];
  if (tag === 'no_hands') next = next.filter((t) => t !== 'no_feet_on');
  if (tag === 'no_feet_on') next = next.filter((t) => t !== 'no_hands');
  return next;
}
