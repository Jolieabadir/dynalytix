#!/usr/bin/env python3
"""
End-to-end smoke test against a deployed instance.

Exercises the full path a climber's data takes - register a video with a
synthetic pose CSV, label it across all three lenses, export, confirm the
export really landed in R2 - and then confirms a second user is walled off
from all of it.

Usage:
    python scripts/smoke_test.py --url https://<service>.up.railway.app \
        [--jwt <token>] [--other-jwt <token>]

With no --jwt, two throwaway users are created through the Supabase auth admin
API (needs SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY) and real access tokens
are fetched for them. That exercises the project's actual signing keys.

If the admin API is unreachable, it falls back to minting HS256 tokens from
SUPABASE_JWT_SECRET for two fixed uuids - only usable on projects that still
have the legacy JWT secret enabled.

Exit code is 0 only when every check passes.
"""
import argparse
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

import urllib.error
import urllib.request
import json

# Fixed so repeated runs reuse one throwaway identity instead of littering
# the database with a new user per run.
TEST_USER_ID = '00000000-0000-4000-8000-000000000001'
OTHER_USER_ID = '00000000-0000-4000-8000-000000000002'

POSE_CSV = (
    'frame_number,timestamp_ms,left_elbow_angle,right_elbow_angle\n'
    '0,0,170.0,168.0\n'
    '1,33,160.5,158.2\n'
    '2,66,140.1,139.9\n'
    '3,100,120.7,122.3\n'
    '4,133,155.0,151.8\n'
)

passed = 0
failed = 0


def check(label: str, condition: bool, detail: str = ''):
    global passed, failed
    if condition:
        passed += 1
        print(f'  PASS  {label}')
    else:
        failed += 1
        print(f'  FAIL  {label}' + (f' - {detail}' if detail else ''))


def supabase_token(email: str, password: str) -> str:
    """Create a throwaway user via the admin API and return a real access token.

    Raises RuntimeError when the project or service role key is unavailable, so
    the caller can fall back to local minting.
    """
    base = os.environ.get('SUPABASE_URL')
    service_key = os.environ.get('SUPABASE_SERVICE_ROLE_KEY')
    anon_key = os.environ.get('SUPABASE_ANON_KEY')
    if not (base and service_key and anon_key):
        raise RuntimeError('SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY and '
                           'SUPABASE_ANON_KEY are needed to use real auth')

    base = base.rstrip('/')

    # Create the user; an existing one (422) is fine, we just sign in.
    req = urllib.request.Request(
        f'{base}/auth/v1/admin/users',
        data=json.dumps({
            'email': email,
            'password': password,
            'email_confirm': True,
        }).encode(),
        headers={
            'Content-Type': 'application/json',
            'apikey': service_key,
            'Authorization': f'Bearer {service_key}',
        },
        method='POST',
    )
    try:
        urllib.request.urlopen(req, timeout=30).read()
    except urllib.error.HTTPError as exc:
        if exc.code not in (409, 422):
            raise RuntimeError(f'admin user create failed: {exc.code} {exc.read().decode()[:200]}')

    # Sign in for an access token signed with the project's real key.
    req = urllib.request.Request(
        f'{base}/auth/v1/token?grant_type=password',
        data=json.dumps({'email': email, 'password': password}).encode(),
        headers={
            'Content-Type': 'application/json',
            'apikey': anon_key,
        },
        method='POST',
    )
    try:
        body = json.loads(urllib.request.urlopen(req, timeout=30).read().decode())
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f'sign-in failed: {exc.code} {exc.read().decode()[:200]}')

    token = body.get('access_token')
    if not token:
        raise RuntimeError(f'no access_token in response: {body}')
    return token


def mint_jwt(user_id: str) -> str:
    """Sign a Supabase-shaped token locally (legacy HS256 projects only)."""
    try:
        import jwt
    except ImportError:
        sys.exit('PyJWT is required to mint a token: pip install PyJWT')

    secret = os.environ.get('SUPABASE_JWT_SECRET')
    if not secret:
        sys.exit('SUPABASE_JWT_SECRET is not set and no --jwt was supplied')

    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            'sub': user_id,
            'aud': 'authenticated',
            'role': 'authenticated',
            'iat': now,
            'exp': now + timedelta(hours=1),
        },
        secret,
        algorithm='HS256',
    )


def request(method: str, url: str, token: str = None, body=None, allow_redirects=True):
    """Return (status, parsed_body_or_text, headers)."""
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode()
        headers['Content-Type'] = 'application/json'
    if token:
        headers['Authorization'] = f'Bearer {token}'

    req = urllib.request.Request(url, data=data, headers=headers, method=method)

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None

    opener = urllib.request.build_opener(
        *( [] if allow_redirects else [NoRedirect] )
    )

    try:
        with opener.open(req, timeout=60) as response:
            raw = response.read().decode()
            try:
                return response.status, json.loads(raw), dict(response.headers)
            except json.JSONDecodeError:
                return response.status, raw, dict(response.headers)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        try:
            return exc.code, json.loads(raw), dict(exc.headers)
        except json.JSONDecodeError:
            return exc.code, raw, dict(exc.headers)
    except urllib.error.URLError as exc:
        return 0, str(exc.reason), {}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True, help='Base URL of the deployment')
    parser.add_argument('--jwt', help='Access token for the test user')
    parser.add_argument('--other-jwt', help='Access token for a different user')
    args = parser.parse_args()

    base = args.url.rstrip('/')

    if args.jwt and args.other_jwt:
        token, other_token = args.jwt, args.other_jwt
        print('Using the supplied tokens')
    else:
        try:
            token = args.jwt or supabase_token(
                'smoke-test-a@dynalytix.test', 'smoke-test-password-a-123')
            other_token = args.other_jwt or supabase_token(
                'smoke-test-b@dynalytix.test', 'smoke-test-password-b-123')
            print('Using real Supabase access tokens for two throwaway users')
        except RuntimeError as exc:
            print(f'Real auth unavailable ({exc});\n'
                  f'falling back to locally minted HS256 tokens')
            token = args.jwt or mint_jwt(TEST_USER_ID)
            other_token = args.other_jwt or mint_jwt(OTHER_USER_ID)

    print(f'\nSmoke test against {base}\n')

    # --- health -------------------------------------------------------------
    print('health')
    status, body, _ = request('GET', f'{base}/api/health')
    check('GET /api/health is 200', status == 200, f'got {status}: {body}')
    if isinstance(body, dict):
        check('database reachable', body.get('database') == 'ok', str(body.get('database')))
        check('schema version is 3', body.get('schema_version') == 3, str(body.get('schema_version')))
        check('R2 configured', body.get('r2') == 'ok', str(body.get('r2')))

    # --- config -------------------------------------------------------------
    print('\nconfig')
    status, body, _ = request('GET', f'{base}/api/config', token)
    check('GET /api/config is 200', status == 200, f'got {status}: {body}')
    if isinstance(body, dict):
        tags = body.get('move_tags', [])
        check("move_tags contains 'technical'", 'technical' in tags)
        check("move_tags contains 'tension'", 'tension' in tags)
        check("'timings' key is gone", 'timings' not in body)

    status, _, _ = request('GET', f'{base}/api/config')
    check('GET /api/config without a token is 401', status == 401, f'got {status}')

    # --- register -----------------------------------------------------------
    print('\nregister')
    status, video, _ = request('POST', f'{base}/api/videos/register', token, {
        'filename': 'smoke_test.mp4',
        'fps': 30.0,
        'total_frames': 5,
        'duration_ms': 166.0,
        'csv_data': POSE_CSV,
    })
    if status == 403 and 'SELF_UPLOAD_ENABLED' in str(video):
        print('  hint: self-upload is off (the default since W2). Make the smoke-test user an admin\n'
              '        (UPDATE rater_profiles SET is_admin = true WHERE user_id = ...) or run against\n'
              '        a deployment with SELF_UPLOAD_ENABLED=true.')
    check('POST /api/videos/register is 201', status == 201, f'got {status}: {video}')
    if status != 201:
        return summarize()

    video_id = video['id']
    check('pose CSV key recorded', bool(video.get('r2_pose_csv_key')), str(video))
    check('fps round-tripped', video.get('fps') == 30.0)
    check('total_frames round-tripped', video.get('total_frames') == 5)

    # --- labels -------------------------------------------------------------
    print('\nlabels')
    status, hold, _ = request('POST', f'{base}/api/holds', token, {
        'video_id': video_id,
        'bbox_x': 0.42, 'bbox_y': 0.33, 'bbox_w': 0.06, 'bbox_h': 0.05,
        'source': 'manual',
    })
    check('POST /api/holds is 201', status == 201, f'got {status}: {hold}')

    status, move, _ = request('POST', f'{base}/api/moves', token, {
        'video_id': video_id,
        'frame_start': 1,
        'frame_end': 3,
        'timestamp_start_ms': 33.0,
        'timestamp_end_ms': 100.0,
        'approach': 'dynamic',
        'size': 'large',
        'move_tags': ['dyno', 'tension'],
        'form_quality': 4,
        'effort_level': 8,
        'confidence': 'high',
        'description': 'smoke test move',
    })
    check('POST /api/moves is 201', status == 201, f'got {status}: {move}')
    if status != 201:
        return summarize()
    move_id = move['id']

    slot = {'hold_id': hold['id'], 'hold_type': 'jug', 'hold_quality': ['incut']} \
        if isinstance(hold, dict) and 'id' in hold else {}
    status, env, _ = request('POST', f'{base}/api/environments', token, {
        'move_id': move_id,
        'wall_angle': 'steep',
        'start_left': slot,
        'end': slot,
    })
    check('POST /api/environments is 201', status == 201, f'got {status}: {env}')
    if isinstance(env, dict) and 'foot' in env:
        check('foot slot left empty', env['foot'].get('hold_id') is None)

    status, outcome, _ = request('POST', f'{base}/api/outcomes', token, {
        'move_id': move_id,
        'result': 'success',
        'reach_detail': 'reached_controlled',
        'confidence': 'high',
    })
    check('POST /api/outcomes is 201', status == 201, f'got {status}: {outcome}')

    status, tag, _ = request('POST', f'{base}/api/frame-tags', token, {
        'move_id': move_id,
        'frame_number': 2,
        'timestamp_ms': 66.0,
        'tag_type': 'sharp_pain',
        'side': 'left',
        'level': 6,
        'locations': ['left_shoulder'],
        'note': 'smoke test tag',
    })
    check('POST /api/frame-tags is 201', status == 201, f'got {status}: {tag}')

    # --- export -------------------------------------------------------------
    print('\nexport')
    status, export, _ = request('POST', f'{base}/api/videos/{video_id}/export', token)
    check('POST export is 200', status == 200, f'got {status}: {export}')
    export_key = export.get('r2_export_key') if isinstance(export, dict) else None
    check('export key returned', bool(export_key), str(export))

    status, listing, _ = request('GET', f'{base}/api/exports/mine', token)
    check('GET /api/exports/mine is 200', status == 200, f'got {status}')
    if isinstance(listing, list):
        check(
            'export appears in /api/exports/mine',
            any(item.get('r2_export_key') == export_key for item in listing),
            str(listing),
        )

    # Follow the presigned redirect: proves the object really is in R2.
    status, _, headers = request(
        'GET', f'{base}/api/videos/{video_id}/export/download', token,
        allow_redirects=False,
    )
    check('export download redirects (307)', status == 307, f'got {status}')
    presigned = headers.get('location') or headers.get('Location')
    check('presigned URL returned', bool(presigned))

    if presigned:
        status, content, _ = request('GET', presigned)
        check('export object fetched from R2', status == 200, f'got {status}')
        text = content if isinstance(content, str) else json.dumps(content)
        check('export header carries raw pose columns',
              'frame_number' in text and 'left_elbow_angle' in text)
        check('export header carries label columns',
              'approach' in text and 'start_left_hold_type' in text)
        check('labels joined onto frames', 'dyno|tension' in text, text[:200])

    # --- isolation ----------------------------------------------------------
    print('\nisolation (second user)')
    status, _, _ = request('GET', f'{base}/api/videos/{video_id}', other_token)
    check('other user GET video is 404', status == 404, f'got {status}')

    status, _, _ = request('GET', f'{base}/api/videos/{video_id}/moves', other_token)
    check('other user GET moves is 404', status == 404, f'got {status}')

    status, _, _ = request('GET', f'{base}/api/moves/{move_id}', other_token)
    check('other user GET move is 404', status == 404, f'got {status}')

    status, _, _ = request('POST', f'{base}/api/videos/{video_id}/export', other_token)
    check('other user export is 404', status == 404, f'got {status}')

    status, _, _ = request(
        'GET', f'{base}/api/videos/{video_id}/export/download', other_token,
        allow_redirects=False,
    )
    check('other user download is 404', status == 404, f'got {status}')

    status, listing, _ = request('GET', f'{base}/api/exports/mine', other_token)
    if isinstance(listing, list):
        check(
            "other user's export list excludes it",
            all(item.get('r2_export_key') != export_key for item in listing),
            str(listing),
        )

    return summarize()


def summarize() -> int:
    print(f'\n{passed} passed, {failed} failed')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
