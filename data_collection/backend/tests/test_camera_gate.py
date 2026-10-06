"""
Camera-check gate (runbook W2 Worker, backend half).

The worker reports has_cut / cut_frames / camera_motion_score /
camera_zoom_range / camera_motion_frames_pct with its 'done' result. A paper
clip can only be marked ready when the pose is done and the camera check
passes, or an admin has overridden it with a note. Community videos are not
gated.
"""
import uuid

import pytest

from src.web import api as api_module
from tests.conftest import requires_db
from tests.test_api_scoping import auth, finish_pose, register_video, upload_video
from tests.test_single_dataset import (  # noqa: F401 - fixtures
    client, admin, make_athlete, parse_csv, set_provenance, mark_ready,
)

pytestmark = requires_db


def clip(client, admin, **camera):
    """A paper clip with full provenance whose worker run reported `camera`."""
    video = register_video(client, admin, filename='broadcast.mp4')
    upload_video(client, admin, video)
    finish_pose(client, admin, video, **camera)
    athlete = make_athlete(client, admin)
    set_provenance(client, admin, video['id'], athlete['athlete_id'])
    return client.get(f'/api/videos/{video["id"]}', headers=auth(admin)).json()


def ready(client, admin, video_id):
    return client.post(f'/api/admin/videos/{video_id}/ready', headers=auth(admin))


def test_static_clip_passes(client, admin):
    video = clip(client, admin)
    assert video['camera_problems'] == []
    assert video['has_cut'] is False and video['camera_zoom_range'] == 1.0
    assert ready(client, admin, video['id']).status_code == 200


@pytest.mark.parametrize('camera,needle', [
    ({'has_cut': True, 'cut_frames': [41, 90]}, 'cut detected (frames 41, 90)'),
    ({'camera_motion_score': 0.01}, 'moves too much'),
    ({'camera_zoom_range': 1.4}, 'zooms'),
])
def test_failing_clip_is_blocked_until_overridden_with_a_note(client, admin, camera, needle):
    video = clip(client, admin, **camera)
    assert any(needle in p for p in video['camera_problems']), video['camera_problems']

    res = ready(client, admin, video['id'])
    assert res.status_code == 422 and any(needle in p for p in res.json()['problems'])

    url = f'/api/admin/videos/{video["id"]}/camera-override'
    assert client.put(url, json={'override': True}, headers=auth(admin)).status_code == 400
    assert client.put(url, json={'override': True, 'note': '   '}, headers=auth(admin)).status_code == 400
    res = client.put(url, json={'override': True, 'note': 'pan ends before move 1'}, headers=auth(admin))
    assert res.status_code == 200
    body = res.json()
    assert body['camera_override'] is True and body['camera_override_note'] == 'pan ends before move 1'
    assert body['camera_problems']  # still listed, just accepted
    assert ready(client, admin, video['id']).status_code == 200

    # Turning it off clears the note.
    res = client.put(url, json={'override': False}, headers=auth(admin))
    assert res.json()['camera_override'] is False and res.json()['camera_override_note'] is None


def test_unmeasured_clip_and_unfinished_pose_are_blocked(client, admin):
    unmeasured = clip(client, admin, has_cut=None, cut_frames=None,
                      camera_motion_score=None, camera_zoom_range=None,
                      camera_motion_frames_pct=None)
    assert unmeasured['camera_problems'] == ['camera check did not run on this clip']
    assert ready(client, admin, unmeasured['id']).status_code == 422

    pending = register_video(client, admin, filename='pending.mp4')
    set_provenance(client, admin, pending['id'], make_athlete(client, admin)['athlete_id'])
    res = ready(client, admin, pending['id'])
    assert res.status_code == 422 and 'pose extraction not finished' in res.json()['detail']


def test_thresholds_come_from_env(client, admin, monkeypatch):
    video = clip(client, admin, camera_motion_score=0.003, camera_zoom_range=1.04)
    assert ready(client, admin, video['id']).status_code == 422  # 0.003 > default 0.002
    monkeypatch.setenv('CAMERA_MOTION_MAX', '0.005')
    assert client.get(f'/api/videos/{video["id"]}', headers=auth(admin)).json()['camera_problems'] == []
    monkeypatch.setenv('CAMERA_ZOOM_MAX', '1.01')
    assert 'zooms' in ' '.join(
        client.get(f'/api/videos/{video["id"]}', headers=auth(admin)).json()['camera_problems'])
    monkeypatch.setenv('CAMERA_ZOOM_MAX', 'wide')  # garbage -> default 1.05
    assert api_module.camera_thresholds() == (0.005, 1.05)
    assert ready(client, admin, video['id']).status_code == 200


def test_pose_result_validates_camera_fields(client, admin):
    video = register_video(client, admin, filename='x.mp4')
    upload_video(client, admin, video)
    from tests.test_api_scoping import WORKER_SECRET
    from src.labeling import pose_queue
    url = f'/api/videos/{video["id"]}/pose-result'
    headers = {pose_queue.SECRET_HEADER: WORKER_SECRET}
    base = {'status': 'done', 'r2_pose_csv_key': 'k'}
    assert client.post(url, json={**base, 'camera_zoom_range': 0.5}, headers=headers).status_code == 422
    assert client.post(url, json={**base, 'camera_motion_frames_pct': 101}, headers=headers).status_code == 422
    assert client.post(url, json={**base, 'camera_motion_score': -1}, headers=headers).status_code == 422


def test_community_videos_are_not_gated(client, admin, monkeypatch):
    monkeypatch.setenv('SELF_UPLOAD_ENABLED', 'true')
    owner = str(uuid.uuid4())
    video = register_video(client, owner, filename='mine.mp4')
    assert video['source_type'] == 'community'
    assert ready(client, admin, video['id']).status_code == 200  # no pose, no camera, still fine


def test_camera_columns_in_exports_and_override_route_is_admin_only(client, admin):
    video = clip(client, admin, has_cut=True, cut_frames=[3])
    client.put(f'/api/admin/videos/{video["id"]}/camera-override',
               json={'override': True, 'note': 'ok'}, headers=auth(admin))
    from tests.test_single_dataset import create_hold
    from tests.test_api_scoping import create_move
    create_hold(client, admin, video['id'])
    create_move(client, admin, video['id'])
    mark_ready(client, admin, video['id'])
    rows = parse_csv(client.get('/api/admin/export/long', headers=auth(admin)).text)
    assert rows and {r['has_cut'] for r in rows} == {'true'}
    assert {r['camera_override'] for r in rows} == {'true'}
    assert {r['camera_zoom_range'] for r in rows} == {'1.0'}
    full = parse_csv(client.get('/api/admin/export/full', headers=auth(admin)).text)
    assert {r['camera_motion_score'] for r in full} == {'0.0001'}

    stranger = str(uuid.uuid4())
    assert client.put(f'/api/admin/videos/{video["id"]}/camera-override',
                      json={'override': False}, headers=auth(stranger)).status_code == 403
