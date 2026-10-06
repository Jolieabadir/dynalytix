/**
 * Pure helpers for admin prep metadata: the sidecar JSON import and how an
 * athlete is shown in pickers. Shared by VideoMetadataPanel and AdminView.
 */

/**
 * Keys the "Import metadata JSON" button accepts — the provenance keys of the
 * sidecar scripts/prepare_clip.py writes, which match the metadata endpoint's
 * field names. Everything else in the file is ignored.
 */
export const IMPORTABLE_KEYS = [
  'source_type',
  'source_url',
  'clip_start_ms',
  'clip_end_ms',
  'license',
  'event_name',
  'event_date',
  'athlete_id',
  'notes',
];

function toFormValue(value) {
  return value === null || value === undefined ? '' : String(value);
}

/**
 * Parse a metadata sidecar. Returns `{ values, ignored }` — `values` holds
 * only IMPORTABLE_KEYS that carry a value, as form strings; a null / missing
 * value is skipped so importing a sidecar never clears a field the admin
 * already filled (prepare_clip.py writes "athlete_id": null when no athlete
 * was given). `ignored` lists every other key. Throws an Error with a human
 * message on bad input.
 *
 * @param {string} text
 * @returns {{values: Record<string, string>, ignored: string[]}}
 */
export function parseMetadataJson(text) {
  let data;
  try {
    data = JSON.parse(text);
  } catch (err) {
    throw new Error(`That file is not valid JSON (${err.message}).`, { cause: err });
  }
  if (!data || typeof data !== 'object' || Array.isArray(data)) {
    throw new Error('That file is valid JSON but not a metadata object ({"source_url": …}).');
  }
  const values = {};
  const ignored = [];
  for (const [key, value] of Object.entries(data)) {
    if (!IMPORTABLE_KEYS.includes(key)) ignored.push(key);
    else if (value !== null && value !== undefined && value !== '') values[key] = toFormValue(value);
  }
  return { values, ignored };
}

/** First 8 characters of a uuid, for display. */
export function shortId(id) {
  return id ? String(id).slice(0, 8) : '';
}

/**
 * Athletes have no name by design; the admin tells them apart by profile URL
 * plus the measurements. "1a2b3c4d · ifsc.com/athlete/123 · 172 cm · b. 1998 · women"
 */
export function athleteLabel(athlete) {
  const parts = [shortId(athlete.athlete_id)];
  if (athlete.ifsc_profile_url) parts.push(athlete.ifsc_profile_url.replace(/^https?:\/\//, ''));
  parts.push(athlete.height_cm != null ? `${athlete.height_cm} cm` : 'height missing');
  parts.push(athlete.birth_year != null ? `b. ${athlete.birth_year}` : 'birth year missing');
  if (athlete.category) parts.push(athlete.category);
  return parts.join(' · ');
}
