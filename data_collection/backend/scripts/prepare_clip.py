#!/usr/bin/env python3
"""
Trim a local video file into a dataset clip plus a source-metadata sidecar.

The paper's clips come from public footage that is obtained and trimmed
locally. This script takes a file already on disk, cuts [start, end) out of
it, and writes:

    <name>.mp4   video only (no audio), source frame rate kept exactly
    <name>.json  the sidecar the admin prep form imports ("Import metadata JSON")

It never downloads anything.

Trimming
    The cut must be frame-accurate (within one frame). A stream copy is only
    frame-accurate when the start lands on a keyframe, so the script asks
    ffprobe for the keyframe positions around the start:

      * start on a keyframe  -> stream copy, then ffprobe the result; if the
        frame count or frame rate is not what the source implies, the copy is
        discarded and the clip is re-encoded instead.
      * otherwise            -> re-encode: H.264 (libx264) CRF 18, -preset slow,
        timestamps passed through (no frame-rate conversion), -an.

Usage
    python scripts/prepare_clip.py INPUT.mp4 --start 00:12:03.500 --end 00:12:41.000 \\
        --source-type public_broadcast --source-url URL --license "..." \\
        --event-name "..." --event-date 2026-05-10 \\
        [--athlete-id UUID] [--notes "..."] [--out-dir clips/] [--name NAME]

    python scripts/prepare_clip.py --batch clips.csv [--out-dir clips/]

Timestamps: HH:MM:SS.mmm, MM:SS.mmm, or plain seconds (e.g. 723.5).

Batch CSV columns (header row required):
    input, start, end, source_type, source_url, license, event_name,
    event_date, athlete_id, notes, name
`input`, `start`, `end`, `source_type`, `source_url`, `license`,
`event_name` and `event_date` are required; the rest may be blank. A relative
`input` is resolved against the CSV's directory. Every row is validated before
anything is trimmed; a summary is printed and written to
<out-dir>/batch_summary.json.

Exit codes: 0 ok, 2 validation error, 1 processing error (ffmpeg/ffprobe).
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import subprocess
import sys
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from fractions import Fraction
from pathlib import Path

SCRIPT_VERSION = '1.0.0'

SOURCE_TYPES = ('public_broadcast', 'cc_license', 'research_dataset')
DEFAULT_MAX_SECONDS = 180.0
DEFAULT_OUT_DIR = 'clips'

SIDECAR_KEYS = (
    'source_type', 'source_url', 'clip_start_ms', 'clip_end_ms', 'license',
    'event_name', 'event_date', 'athlete_id', 'notes', 'fps', 'width',
    'height', 'duration_ms', 'frame_count', 'sha256', 'prepared_at',
    'script_version',
)

BATCH_COLUMNS = (
    'input', 'start', 'end', 'source_type', 'source_url', 'license',
    'event_name', 'event_date', 'athlete_id', 'notes', 'name',
)
BATCH_REQUIRED = (
    'input', 'start', 'end', 'source_type', 'source_url', 'license',
    'event_name', 'event_date',
)

EXIT_PROCESSING = 1
EXIT_VALIDATION = 2


class ValidationError(Exception):
    """Bad input from the user. Exit code 2."""


class ProcessingError(Exception):
    """ffmpeg / ffprobe failed or produced something unusable. Exit code 1."""


# ==================== parsing ====================

_TS_RE = re.compile(
    r'^(?:(?:(?P<h>\d+):)?(?P<m>\d{1,2}):)?(?P<s>\d+(?:\.\d+)?)$'
)


def parse_timestamp(text: str) -> int:
    """HH:MM:SS.mmm, MM:SS.mmm or seconds -> integer milliseconds.

    Uses Decimal so "12.345" is exactly 12345 ms (no float drift). Sub-ms
    digits are rounded half-up.
    """
    if text is None:
        raise ValidationError('timestamp is missing')
    raw = str(text).strip()
    m = _TS_RE.match(raw)
    if not m:
        raise ValidationError(
            f'bad timestamp {raw!r}: use HH:MM:SS.mmm, MM:SS.mmm or seconds'
        )
    hours = int(m.group('h') or 0)
    minutes = int(m.group('m') or 0)
    try:
        seconds = Decimal(m.group('s'))
    except InvalidOperation:  # pragma: no cover - regex already guards this
        raise ValidationError(f'bad timestamp {raw!r}')
    has_colon = ':' in raw
    if has_colon and seconds >= 60:
        raise ValidationError(f'bad timestamp {raw!r}: seconds must be < 60')
    if m.group('h') is not None and minutes >= 60:
        raise ValidationError(f'bad timestamp {raw!r}: minutes must be < 60')
    total = (Decimal(hours * 3600 + minutes * 60) + seconds) * 1000
    return int(total.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def parse_event_date(text: str) -> str:
    raw = (text or '').strip()
    if not raw:
        raise ValidationError('--event-date is required (YYYY-MM-DD)')
    try:
        return date.fromisoformat(raw).isoformat()
    except ValueError:
        raise ValidationError(f'bad event date {raw!r}: use YYYY-MM-DD')


def ms_to_seconds_str(ms: int) -> str:
    return f'{ms // 1000}.{ms % 1000:03d}'


# ==================== ffprobe helpers ====================

def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        tail = (proc.stderr or '').strip().splitlines()[-5:]
        raise ProcessingError(
            f'{Path(cmd[0]).name} failed (exit {proc.returncode}): ' + ' | '.join(tail)
        )
    return proc


def require_tools() -> None:
    missing = [t for t in ('ffmpeg', 'ffprobe') if shutil.which(t) is None]
    if missing:
        raise ProcessingError(f'not found on PATH: {", ".join(missing)}')


def _fraction(text: str | None) -> Fraction | None:
    if not text or text in ('0/0', 'N/A'):
        return None
    try:
        f = Fraction(text)
    except (ValueError, ZeroDivisionError):
        return None
    return f if f > 0 else None


def fraction_str(f: Fraction) -> str:
    return f'{f.numerator}/{f.denominator}'


def probe_video(path: Path, count_frames: bool = False) -> dict:
    """First video stream: fps (Fraction), width, height, duration (s),
    start_time (s), and frame_count when requested."""
    cmd = [
        'ffprobe', '-v', 'error', '-select_streams', 'v:0',
        '-show_entries',
        'stream=r_frame_rate,avg_frame_rate,width,height,duration,start_time,nb_read_packets'
        ':format=duration,start_time',
        '-of', 'json',
    ]
    if count_frames:
        cmd.append('-count_packets')
    cmd.append(str(path))
    data = json.loads(_run(cmd).stdout or '{}')
    streams = data.get('streams') or []
    if not streams:
        raise ProcessingError(f'{path}: no video stream')
    s = streams[0]
    fmt = data.get('format') or {}
    fps = _fraction(s.get('r_frame_rate')) or _fraction(s.get('avg_frame_rate'))
    if fps is None:
        raise ProcessingError(f'{path}: could not determine frame rate')

    def _float(*vals):
        for v in vals:
            try:
                if v not in (None, 'N/A'):
                    return float(v)
            except ValueError:
                continue
        return None

    out = {
        'fps': fps,
        'avg_fps': _fraction(s.get('avg_frame_rate')),
        'width': int(s.get('width') or 0),
        'height': int(s.get('height') or 0),
        'duration': _float(s.get('duration'), fmt.get('duration')),
        'start_time': _float(fmt.get('start_time'), s.get('start_time')) or 0.0,
    }
    if count_frames:
        try:
            out['frame_count'] = int(s.get('nb_read_packets'))
        except (TypeError, ValueError):
            raise ProcessingError(f'{path}: could not count frames')
    return out


def start_is_keyframe(path: Path, start_ms: int, fps: Fraction, start_time: float) -> bool:
    """True when a video keyframe sits at start_ms (within half a frame).

    Reads packet flags only (no decode) over a window around the start.
    Packet timestamps are absolute; ffmpeg's -ss is relative to the file's
    start_time, so the comparison is made on that relative timeline.
    """
    start_s = start_ms / 1000.0
    window_from = max(0.0, start_time + start_s - 5.0)
    cmd = [
        'ffprobe', '-v', 'error', '-select_streams', 'v:0',
        '-read_intervals', f'{window_from:.3f}%+10',
        '-show_entries', 'packet=pts_time,flags',
        '-of', 'json', str(path),
    ]
    data = json.loads(_run(cmd).stdout or '{}')
    half_frame = float(1 / fps) / 2
    for pkt in data.get('packets') or []:
        if 'K' not in (pkt.get('flags') or ''):
            continue
        try:
            pts = float(pkt['pts_time']) - start_time
        except (KeyError, TypeError, ValueError):
            continue
        if abs(pts - start_s) < half_frame:
            return True
    return False


def expected_frame_count(start_ms: int, end_ms: int, fps: Fraction, start_time: float = 0.0) -> int:
    """Frames of a constant-rate source whose timestamp falls in [start, end)."""
    def first_at_or_after(ms: int) -> int:
        # ceil(ms/1000 * fps)
        x = Fraction(ms, 1000) * fps
        return -((-x.numerator) // x.denominator)
    return first_at_or_after(end_ms) - first_at_or_after(start_ms)


# ==================== trimming ====================

def _ffmpeg_base(src: Path, start_ms: int, duration_ms: int) -> list[str]:
    return [
        'ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-y',
        '-ss', ms_to_seconds_str(start_ms), '-i', str(src),
        '-t', ms_to_seconds_str(duration_ms),
        '-map', '0:v:0', '-an', '-sn', '-dn',
        '-map_metadata', '-1', '-map_chapters', '-1',
    ]


def trim_copy(src: Path, dst: Path, start_ms: int, duration_ms: int) -> None:
    cmd = _ffmpeg_base(src, start_ms, duration_ms) + [
        '-c:v', 'copy', '-avoid_negative_ts', 'make_zero',
        '-movflags', '+faststart', str(dst),
    ]
    _run(cmd)


def trim_reencode(src: Path, dst: Path, start_ms: int, duration_ms: int,
                  width: int, height: int) -> None:
    cmd = _ffmpeg_base(src, start_ms, duration_ms) + [
        '-c:v', 'libx264', '-crf', '18', '-preset', 'slow',
        # Keep every source frame with its own timestamp: no fps conversion,
        # no duplicated or dropped frames.
        '-fps_mode', 'passthrough',
    ]
    # yuv420p for browser playback; 4:2:0 needs even dimensions.
    if width % 2 == 0 and height % 2 == 0:
        cmd += ['-pix_fmt', 'yuv420p']
    cmd += ['-movflags', '+faststart', str(dst)]
    _run(cmd)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


# ==================== the clip ====================

@dataclass
class ClipSpec:
    input: Path
    start_ms: int
    end_ms: int
    source_type: str
    source_url: str
    license: str
    event_name: str
    event_date: str
    athlete_id: str | None = None
    notes: str | None = None
    name: str | None = None
    extra: dict = field(default_factory=dict)

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms

    def output_name(self) -> str:
        if self.name:
            return self.name
        return f'{self.input.stem}_{self.start_ms}-{self.end_ms}'


_NAME_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]*$')


def build_spec(*, input, start, end, source_type, source_url, license,
               event_name, event_date, athlete_id=None, notes=None, name=None,
               max_seconds: float = DEFAULT_MAX_SECONDS) -> ClipSpec:
    """Validate raw values (strings) into a ClipSpec. Raises ValidationError.

    Checks that need ffprobe (end within the source) happen in prepare_clip.
    """
    src = Path(str(input or '')).expanduser()
    if not str(input or '').strip():
        raise ValidationError('input file is required')
    if not src.is_file():
        raise ValidationError(f'input file not found: {src}')

    start_ms = parse_timestamp(start)
    end_ms = parse_timestamp(end)
    if end_ms <= start_ms:
        raise ValidationError(
            f'end ({end}) must be after start ({start})'
        )
    if max_seconds <= 0:
        raise ValidationError('--max-seconds must be positive')
    if (end_ms - start_ms) > max_seconds * 1000:
        raise ValidationError(
            f'clip is {(end_ms - start_ms) / 1000:.3f}s, longer than the '
            f'{max_seconds:g}s limit (--max-seconds)'
        )

    st = (source_type or '').strip()
    if st not in SOURCE_TYPES:
        raise ValidationError(
            f'source type {st!r} not allowed; use one of {", ".join(SOURCE_TYPES)}'
        )

    url = (source_url or '').strip()
    if not url:
        raise ValidationError('--source-url is required')
    if not re.match(r'^https?://\S+$', url):
        raise ValidationError(f'source URL must be an http(s) URL: {url!r}')

    lic = (license or '').strip()
    if not lic:
        raise ValidationError('--license is required')

    ev = (event_name or '').strip()
    if not ev:
        raise ValidationError('--event-name is required')

    ev_date = parse_event_date(event_date)

    aid = (athlete_id or '').strip() or None
    if aid is not None:
        try:
            aid = str(uuid.UUID(aid))
        except ValueError:
            raise ValidationError(f'athlete id is not a UUID: {aid!r}')

    nm = (name or '').strip() or None
    if nm is not None and not _NAME_RE.match(nm):
        raise ValidationError(
            f'bad output name {nm!r}: letters, digits, ".", "_" and "-" only'
        )

    return ClipSpec(
        input=src, start_ms=start_ms, end_ms=end_ms, source_type=st,
        source_url=url, license=lic, event_name=ev, event_date=ev_date,
        athlete_id=aid, notes=(notes or '').strip() or None, name=nm,
    )


def prepare_clip(spec: ClipSpec, out_dir: Path, overwrite: bool = False) -> dict:
    """Trim spec.input into out_dir/<name>.mp4 + .json. Returns a result dict:
    {'mp4', 'json', 'mode', 'sidecar'}."""
    require_tools()
    out_dir = Path(out_dir)
    name = spec.output_name()
    mp4 = out_dir / f'{name}.mp4'
    sidecar_path = out_dir / f'{name}.json'
    if not overwrite:
        for p in (mp4, sidecar_path):
            if p.exists():
                raise ValidationError(f'{p} already exists (use --overwrite)')

    src = probe_video(spec.input)
    if src['duration'] is not None:
        src_ms = int(round(src['duration'] * 1000))
        if spec.end_ms > src_ms:
            raise ValidationError(
                f'end {ms_to_seconds_str(spec.end_ms)}s is past the end of '
                f'{spec.input.name} ({ms_to_seconds_str(src_ms)}s)'
            )
    if src['avg_fps'] is not None and src['avg_fps'] != src['fps']:
        # Variable frame rate (or odd timebase). Frame counts can't be
        # predicted, so never trust a copy here.
        constant_rate = False
    else:
        constant_rate = True

    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = out_dir / f'.{name}.partial.mp4'
    expected = expected_frame_count(spec.start_ms, spec.end_ms, src['fps'])

    mode = 'reencode'
    if constant_rate and start_is_keyframe(spec.input, spec.start_ms, src['fps'], src['start_time']):
        trim_copy(spec.input, tmp, spec.start_ms, spec.duration_ms)
        got = probe_video(tmp, count_frames=True)
        if got['fps'] == src['fps'] and abs(got['frame_count'] - expected) <= 1:
            mode = 'copy'
        else:
            tmp.unlink(missing_ok=True)
    if mode == 'reencode':
        trim_reencode(spec.input, tmp, spec.start_ms, spec.duration_ms,
                      src['width'], src['height'])

    out = probe_video(tmp, count_frames=True)
    if out['frame_count'] <= 0:
        tmp.unlink(missing_ok=True)
        raise ProcessingError(f'{name}: trimmed clip has no frames')
    if out['fps'] != src['fps']:
        tmp.unlink(missing_ok=True)
        raise ProcessingError(
            f'{name}: output frame rate {fraction_str(out["fps"])} differs from '
            f'source {fraction_str(src["fps"])}'
        )
    tmp.replace(mp4)

    if out['duration'] is not None:
        duration_ms = int(round(out['duration'] * 1000))
    else:
        duration_ms = int(round(out['frame_count'] / out['fps'] * 1000))

    sidecar = {
        'source_type': spec.source_type,
        'source_url': spec.source_url,
        'clip_start_ms': spec.start_ms,
        'clip_end_ms': spec.end_ms,
        'license': spec.license,
        'event_name': spec.event_name,
        'event_date': spec.event_date,
        'athlete_id': spec.athlete_id,
        'notes': spec.notes,
        'fps': fraction_str(out['fps']),
        'width': out['width'],
        'height': out['height'],
        'duration_ms': duration_ms,
        'frame_count': out['frame_count'],
        'sha256': sha256_file(mp4),
        'prepared_at': datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z'),
        'script_version': SCRIPT_VERSION,
    }
    assert tuple(sidecar) == SIDECAR_KEYS
    sidecar_path.write_text(json.dumps(sidecar, indent=2) + '\n', encoding='utf-8')
    return {'mp4': mp4, 'json': sidecar_path, 'mode': mode,
            'expected_frames': expected, 'sidecar': sidecar}


# ==================== batch ====================

def read_batch(csv_path: Path, max_seconds: float) -> list[ClipSpec]:
    """Validate every row up front. Raises ValidationError listing all bad rows."""
    if not csv_path.is_file():
        raise ValidationError(f'batch file not found: {csv_path}')
    with open(csv_path, newline='', encoding='utf-8-sig') as fh:
        reader = csv.DictReader(fh)
        header = [h.strip() for h in (reader.fieldnames or [])]
        missing = [c for c in BATCH_REQUIRED if c not in header]
        if missing:
            raise ValidationError(
                f'{csv_path.name}: missing column(s): {", ".join(missing)}'
            )
        unknown = [c for c in header if c not in BATCH_COLUMNS]
        if unknown:
            raise ValidationError(
                f'{csv_path.name}: unknown column(s): {", ".join(unknown)}'
            )
        rows = [{(k or '').strip(): (v or '') for k, v in r.items()} for r in reader]

    if not rows:
        raise ValidationError(f'{csv_path.name}: no rows')

    specs, errors, names = [], [], {}
    for i, row in enumerate(rows, start=2):  # line 1 is the header
        inp = row.get('input', '').strip()
        if inp and not Path(inp).expanduser().is_absolute():
            inp = str(csv_path.parent / inp)
        try:
            spec = build_spec(
                input=inp, start=row.get('start'), end=row.get('end'),
                source_type=row.get('source_type'), source_url=row.get('source_url'),
                license=row.get('license'), event_name=row.get('event_name'),
                event_date=row.get('event_date'), athlete_id=row.get('athlete_id'),
                notes=row.get('notes'), name=row.get('name'),
                max_seconds=max_seconds,
            )
        except ValidationError as e:
            errors.append(f'line {i}: {e}')
            continue
        out_name = spec.output_name()
        if out_name in names:
            errors.append(f'line {i}: output name {out_name!r} repeats line {names[out_name]}')
            continue
        names[out_name] = i
        specs.append(spec)
    if errors:
        raise ValidationError(
            f'{csv_path.name}: {len(errors)} invalid row(s); nothing was trimmed\n  '
            + '\n  '.join(errors)
        )
    return specs


def run_batch(csv_path: Path, out_dir: Path, max_seconds: float, overwrite: bool) -> int:
    specs = read_batch(csv_path, max_seconds)
    results = []
    failed = 0
    for spec in specs:
        entry = {'name': spec.output_name(), 'input': str(spec.input),
                 'clip_start_ms': spec.start_ms, 'clip_end_ms': spec.end_ms}
        try:
            r = prepare_clip(spec, out_dir, overwrite=overwrite)
            entry.update(status='ok', mode=r['mode'], mp4=str(r['mp4']),
                         json=str(r['json']), fps=r['sidecar']['fps'],
                         frame_count=r['sidecar']['frame_count'],
                         duration_ms=r['sidecar']['duration_ms'])
        except (ValidationError, ProcessingError) as e:
            failed += 1
            entry.update(status='error', error=str(e))
        results.append(entry)
        _print_result(entry)

    summary = {
        'script_version': SCRIPT_VERSION,
        'batch_file': str(csv_path),
        'prepared_at': datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z'),
        'total': len(results),
        'ok': len(results) - failed,
        'failed': failed,
        'clips': results,
    }
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    summary_path = Path(out_dir) / 'batch_summary.json'
    summary_path.write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
    print(f'\n{summary["ok"]}/{summary["total"]} clips prepared; summary: {summary_path}')
    return EXIT_PROCESSING if failed else 0


def _print_result(entry: dict) -> None:
    if entry.get('status') == 'ok':
        print(f'ok    {entry["name"]}  [{entry["mode"]}]  {entry["fps"]} fps  '
              f'{entry["frame_count"]} frames  {entry["duration_ms"]} ms')
    else:
        print(f'FAIL  {entry["name"]}  {entry.get("error")}', file=sys.stderr)


# ==================== CLI ====================

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog='prepare_clip.py',
        description='Trim a local video into a dataset clip + metadata sidecar. '
                    'Never downloads anything.',
    )
    p.add_argument('input', nargs='?', help='local video file (single mode)')
    p.add_argument('--batch', metavar='CSV', help='CSV with one row per clip')
    p.add_argument('--start', help='HH:MM:SS.mmm, MM:SS.mmm or seconds')
    p.add_argument('--end', help='HH:MM:SS.mmm, MM:SS.mmm or seconds')
    p.add_argument('--source-type', choices=None,
                   help='one of: ' + ', '.join(SOURCE_TYPES))
    p.add_argument('--source-url')
    p.add_argument('--license')
    p.add_argument('--event-name')
    p.add_argument('--event-date', help='YYYY-MM-DD')
    p.add_argument('--athlete-id', help='athletes.id UUID (optional)')
    p.add_argument('--notes')
    p.add_argument('--name', help='output basename (default: <input stem>_<start_ms>-<end_ms>)')
    p.add_argument('--out-dir', default=DEFAULT_OUT_DIR, help=f'default: {DEFAULT_OUT_DIR}/')
    p.add_argument('--max-seconds', type=float, default=DEFAULT_MAX_SECONDS,
                   help=f'longest clip allowed (default {DEFAULT_MAX_SECONDS:g})')
    p.add_argument('--overwrite', action='store_true', help='replace existing outputs')
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.batch:
            if args.input:
                raise ValidationError('give either INPUT or --batch CSV, not both')
            return run_batch(Path(args.batch), Path(args.out_dir),
                             args.max_seconds, args.overwrite)

        if not args.input:
            raise ValidationError('INPUT is required (or use --batch CSV)')
        for flag in ('start', 'end'):
            if getattr(args, flag) is None:
                raise ValidationError(f'--{flag} is required')
        spec = build_spec(
            input=args.input, start=args.start, end=args.end,
            source_type=args.source_type, source_url=args.source_url,
            license=args.license, event_name=args.event_name,
            event_date=args.event_date, athlete_id=args.athlete_id,
            notes=args.notes, name=args.name, max_seconds=args.max_seconds,
        )
        r = prepare_clip(spec, Path(args.out_dir), overwrite=args.overwrite)
    except ValidationError as e:
        print(f'error: {e}', file=sys.stderr)
        return EXIT_VALIDATION
    except ProcessingError as e:
        print(f'error: {e}', file=sys.stderr)
        return EXIT_PROCESSING

    s = r['sidecar']
    print(f'{r["mp4"]}  [{r["mode"]}]  {s["fps"]} fps  {s["width"]}x{s["height"]}  '
          f'{s["frame_count"]} frames  {s["duration_ms"]} ms')
    print(r['json'])
    return 0


if __name__ == '__main__':
    sys.exit(main())
