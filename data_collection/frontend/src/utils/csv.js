/**
 * Pose CSV → row objects keyed by column name.
 *
 * One parser, shared by everything that reads the worker's CSV: the player's
 * skeleton, hold suggestions, the move form, and the Dataset A entry points
 * that load a video someone else uploaded (the rating view, an admin reopening
 * a video for prep). Values stay strings — a pose-less frame has empty
 * strings in every landmark column, and consumers decide how to treat that
 * (services/holdSuggestions.numberOrNull).
 *
 * Rows are positional: the worker guarantees row N is frame N with no gaps,
 * which is what SkeletonOverlay relies on when it indexes by currentFrame.
 */
export function parsePoseCsv(csvText) {
  if (!csvText) return [];
  const lines = csvText.split('\n');
  const headers = lines[0].split(',').map((h) => h.trim());
  return lines
    .slice(1)
    .map((line) => {
      const values = line.split(',');
      const row = {};
      headers.forEach((header, i) => {
        row[header] = values[i]?.trim();
      });
      return row;
    })
    .filter((row) => row.frame_number !== undefined && row.frame_number !== '');
}

/** Alias kept for the pose-status hook and its tests. */
export const parseCsv = parsePoseCsv;
