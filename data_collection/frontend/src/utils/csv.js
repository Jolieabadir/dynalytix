/**
 * Pose CSV → row objects keyed by column name.
 *
 * The same parse the upload path and the player do inline; shared here for
 * the two Dataset A entry points that load a video someone else extracted
 * (the rating view, and an admin reopening a video for prep).
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
    .filter((row) => row.frame_number);
}
