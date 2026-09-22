"""
API authentication and per-user scoping tests.

Two users, one dataset each: every endpoint must refuse to leak across the
boundary, and must return 404 (not 403) so an id's existence stays private.
"""
import uuid

import pytest
from fastapi.testclient import TestClient

from src.labeling import pose_queue
from src.storage import r2
from src.web import api as api_module
from tests.conftest import make_jwt, requires_db  # noqa: F401 - `enqueued` fixture lives in conftest

WORKER_SECRET = 'test-worker-secret'
# The real enqueue, captured before any fixture replaces it.
_real_enqueue = pose_queue.enqueue_pose_job

pytestmark = requires_db


# ==================== FIXTURES ====================

@pytest.fixture
def client(clean_db, fake_r2, enqueued, monkeypatch):
    """TestClient wired to the test database, the R2 fixture and a fake worker."""
    monkeypatch.setattr(api_module, '_db', clean_db)
    monkeypatch.setattr(api_module, '_exporter', None)
    monkeypatch.setenv('MODAL_WEBHOOK_SECRET', WORKER_SECRET)
    with TestClient(api_module.app) as test_client:
        yield test_client


def auth(user_id: str) -> dict:
    return {'Authorization': f'Bearer {make_jwt(user_id)}'}


POSE_CSV = (
    'frame_number,timestamp_ms,left_elbow_angle\n'
    '0,0,170.0\n'
    '1,33,165.5\n'
    '2,66,150.2\n'
)


def register_video(client, user_id, filename='climb.mp4'):
    """Register with the browser's provisional metadata (no CSV any more)."""
    response = client.post(
        '/api/videos/register',
        json={
            'filename': filename,
            'fps': 30.0,
            'total_frames': 3,
            'duration_ms': 100.0,
            'width': 1920,
            'height': 1080,
        },
        headers=auth(user_id),
    )
    assert response.status_code == 201, response.text
    return response.json()


def upload_video(client, user_id, video):
    """upload-url -> (pretend PUT) -> confirm-upload. Returns the confirm body."""
    presigned = client.post(
        f'/api/videos/{video["id"]}/upload-url',
        json={'content_type': 'video/mp4'},
        headers=auth(user_id),
    )
    assert presigned.status_code == 200, presigned.text
    confirmed = client.post(
        f'/api/videos/{video["id"]}/confirm-upload',
        json={'key': presigned.json()['key']},
        headers=auth(user_id),
    )
    assert confirmed.status_code == 200, confirmed.text
    return confirmed.json()


def finish_pose(client, user_id, video, csv_text=POSE_CSV, **overrides):
    """Play the worker: put the CSV in R2 and post the done callback."""
    key = r2.pose_csv_key(user_id, video['id'])
    r2.put_object(key, csv_text, content_type='text/csv')
    body = {
        'status': 'done',
        'fps': 30.0,
        'total_frames': 3,
        'duration_ms': 100.0,
        'width': 1920,
        'height': 1080,
        'r2_pose_csv_key': key,
    }
    body.update(overrides)
    response = client.post(
        f'/api/videos/{video["id"]}/pose-result',
        json=body,
        headers={pose_queue.SECRET_HEADER: WORKER_SECRET},
    )
    assert response.status_code == 200, response.text
    return response.json()


def ready_video(client, user_id, filename='climb.mp4'):
    """A video that has been registered, uploaded and pose-extracted."""
    video = register_video(client, user_id, filename)
    upload_video(client, user_id, video)
    finish_pose(client, user_id, video)
    return client.get(f'/api/videos/{video["id"]}', headers=auth(user_id)).json()


def create_move(client, user_id, video_id):
    response = client.post(
        '/api/moves',
        json={
            'video_id': video_id,
            'frame_start': 0,
            'frame_end': 2,
            'timestamp_start_ms': 0.0,
            'timestamp_end_ms': 66.0,
            'approach': 'dynamic',
            'size': 'large',
            'move_tags': ['dyno', 'technical'],
            'form_quality': 4,
            'effort_level': 7,
            'confidence': 'high',
            'description': 'test move',
        },
        headers=auth(user_id),
    )
    assert response.status_code == 201, response.text
    return response.json()


# ==================== AUTH ====================

def test_health_needs_no_token(client):
    response = client.get('/api/health')
    assert response.status_code == 200
    body = response.json()
    assert body['database'] == 'ok'
    assert body['schema_version'] == 3


def test_root_needs_no_token(client):
    assert client.get('/').status_code == 200


@pytest.mark.parametrize('path', [
    '/api/config',
    '/api/videos',
    '/api/exports/mine',
])
def test_endpoints_require_a_token(client, path):
    assert client.get(path).status_code == 401


def test_config_with_token(client, user_a):
    response = client.get('/api/config', headers=auth(user_a))
    assert response.status_code == 200
    config = response.json()
    assert 'technical' in config['move_tags']
    assert 'tension' in config['move_tags']
    assert 'timings' not in config
    assert config['hold_slots'] == ['start_left', 'start_right', 'end', 'foot']


def test_garbage_token_is_rejected(client):
    response = client.get('/api/videos', headers={'Authorization': 'Bearer not-a-jwt'})
    assert response.status_code == 401


def test_token_signed_with_wrong_secret_is_rejected(client, user_a):
    token = make_jwt(user_a, secret='some-other-secret-padded-to-32-bytes-minimum')
    response = client.get('/api/videos', headers={'Authorization': f'Bearer {token}'})
    assert response.status_code == 401


def test_expired_token_is_rejected(client, user_a):
    token = make_jwt(user_a, expires_in=-60)
    response = client.get('/api/videos', headers={'Authorization': f'Bearer {token}'})
    assert response.status_code == 401
    assert 'expired' in response.json()['detail'].lower()


# ==================== REGISTER ====================

def test_register_creates_a_pending_row_with_no_csv(client, fake_r2, user_a):
    video = register_video(client, user_a)

    assert video['pose_status'] == 'pending'
    assert video['pose_error'] is None
    assert video['r2_pose_csv_key'] is None
    assert video['r2_video_key'] is None
    assert video['fps'] == 30.0
    assert video['total_frames'] == 3
    assert video['width'] == 1920
    if fake_r2 is not None:
        assert fake_r2.objects == {}


def test_register_ignores_csv_data(client, user_a):
    """The old inline-CSV field is gone; a stale client must not 500."""
    response = client.post(
        '/api/videos/register',
        json={'filename': 'old.mp4', 'fps': 30.0, 'total_frames': 1,
              'duration_ms': 33.0, 'csv_data': POSE_CSV},
        headers=auth(user_a),
    )
    assert response.status_code == 201
    assert response.json()['r2_pose_csv_key'] is None


def test_register_defaults_provisional_metadata(client, user_a):
    response = client.post(
        '/api/videos/register', json={'filename': 'bare.mov'}, headers=auth(user_a)
    )
    assert response.status_code == 201
    body = response.json()
    assert body['fps'] == api_module.PROVISIONAL_FPS
    assert body['total_frames'] == 0
    assert body['pose_status'] == 'pending'


# ==================== POSE JOB ====================

def test_confirm_upload_enqueues_the_pose_job(client, enqueued, user_a):
    video = register_video(client, user_a)
    confirmed = upload_video(client, user_a, video)

    assert confirmed['pose_status'] == 'pending'
    assert enqueued == [{
        'video_id': video['id'],
        'user_id': user_a,
        'r2_key': f'videos/{user_a}/{video["id"]}/climb.mp4',
    }]


def test_confirm_upload_marks_failed_when_worker_not_configured(client, monkeypatch, user_a):
    monkeypatch.delenv('MODAL_ENDPOINT_URL', raising=False)
    # Use the real enqueue so the not-configured branch is exercised.
    monkeypatch.setattr(pose_queue, 'enqueue_pose_job', _real_enqueue)
    video = register_video(client, user_a)
    confirmed = upload_video(client, user_a, video)

    assert confirmed['r2_video_key'].startswith(f'videos/{user_a}/')
    assert confirmed['pose_status'] == 'failed'
    assert 'worker not configured' in confirmed['pose_error']


def test_confirm_upload_marks_failed_when_enqueue_raises(client, monkeypatch, user_a):
    def boom(video_id, user_id, r2_key):
        raise pose_queue.PoseQueueError('worker unreachable: ConnectError')

    monkeypatch.setattr(pose_queue, 'enqueue_pose_job', boom)
    video = register_video(client, user_a)
    confirmed = upload_video(client, user_a, video)

    assert confirmed['pose_status'] == 'failed'
    assert confirmed['pose_error'] == 'worker unreachable: ConnectError'
    status = client.get(f'/api/videos/{video["id"]}/status', headers=auth(user_a)).json()
    assert status['pose_status'] == 'failed'
    assert status['pose_finished_at']


def test_status_endpoint_is_scoped_and_reports_pose_fields(client, user_a, user_b):
    video = register_video(client, user_a)
    response = client.get(f'/api/videos/{video["id"]}/status', headers=auth(user_a))
    assert response.status_code == 200
    body = response.json()
    assert body['pose_status'] == 'pending'
    assert body['fps'] == 30.0
    assert body['total_frames'] == 3
    assert body['width'] == 1920
    assert set(body) >= {'pose_status', 'pose_error', 'pose_started_at',
                         'pose_finished_at', 'fps', 'total_frames', 'width', 'height'}

    assert client.get(f'/api/videos/{video["id"]}/status', headers=auth(user_b)).status_code == 404


def test_pose_result_requires_the_worker_secret(client, user_a):
    video = register_video(client, user_a)
    url = f'/api/videos/{video["id"]}/pose-result'
    body = {'status': 'processing'}

    assert client.post(url, json=body).status_code == 401
    assert client.post(url, json=body, headers={pose_queue.SECRET_HEADER: 'wrong'}).status_code == 401
    # A user JWT is not a worker credential either.
    assert client.post(url, json=body, headers=auth(user_a)).status_code == 401
    assert client.post(url, json=body, headers={pose_queue.SECRET_HEADER: WORKER_SECRET}).status_code == 200


def test_pose_result_walks_processing_then_done_and_overwrites_metadata(client, user_a):
    video = register_video(client, user_a)
    upload_video(client, user_a, video)
    headers = {pose_queue.SECRET_HEADER: WORKER_SECRET}

    processing = client.post(
        f'/api/videos/{video["id"]}/pose-result', json={'status': 'processing'}, headers=headers
    ).json()
    assert processing['pose_status'] == 'processing'
    assert processing['pose_started_at']
    assert processing['pose_finished_at'] is None

    # ffprobe says 60fps and 1080x1920 (a rotated phone clip); those win.
    done = finish_pose(client, user_a, video, fps=60.0, total_frames=6, duration_ms=100.0,
                       width=1080, height=1920)
    assert done['pose_status'] == 'done'
    assert done['fps'] == 60.0
    assert done['total_frames'] == 6
    assert done['width'] == 1080 and done['height'] == 1920
    assert done['r2_pose_csv_key'] == f'pose/{user_a}/{video["id"]}.csv'
    assert done['pose_finished_at']

    fetched = client.get(f'/api/videos/{video["id"]}', headers=auth(user_a)).json()
    assert fetched['fps'] == 60.0 and fetched['pose_status'] == 'done'


def test_pose_result_failed_records_the_error(client, user_a):
    video = register_video(client, user_a)
    response = client.post(
        f'/api/videos/{video["id"]}/pose-result',
        json={'status': 'failed', 'error': 'ffmpeg produced no frames'},
        headers={pose_queue.SECRET_HEADER: WORKER_SECRET},
    )
    assert response.status_code == 200
    assert response.json()['pose_status'] == 'failed'
    assert response.json()['pose_error'] == 'ffmpeg produced no frames'


def test_pose_result_done_requires_a_csv_key(client, user_a):
    video = register_video(client, user_a)
    response = client.post(
        f'/api/videos/{video["id"]}/pose-result',
        json={'status': 'done'},
        headers={pose_queue.SECRET_HEADER: WORKER_SECRET},
    )
    assert response.status_code == 400


def test_pose_result_unknown_video_is_404(client):
    response = client.post(
        '/api/videos/999999/pose-result',
        json={'status': 'processing'},
        headers={pose_queue.SECRET_HEADER: WORKER_SECRET},
    )
    assert response.status_code == 404


def test_retry_pose_reenqueues_a_failed_job(client, enqueued, monkeypatch, user_a):
    video = register_video(client, user_a)
    upload_video(client, user_a, video)
    client.post(
        f'/api/videos/{video["id"]}/pose-result',
        json={'status': 'failed', 'error': 'gpu hiccup'},
        headers={pose_queue.SECRET_HEADER: WORKER_SECRET},
    )
    enqueued.clear()

    response = client.post(f'/api/videos/{video["id"]}/retry-pose', headers=auth(user_a))
    assert response.status_code == 200, response.text
    assert response.json()['pose_status'] == 'pending'
    assert response.json()['pose_error'] is None
    assert len(enqueued) == 1 and enqueued[0]['video_id'] == video['id']


def test_retry_pose_refuses_while_processing_or_done(client, user_a):
    video = register_video(client, user_a)
    upload_video(client, user_a, video)
    client.post(
        f'/api/videos/{video["id"]}/pose-result', json={'status': 'processing'},
        headers={pose_queue.SECRET_HEADER: WORKER_SECRET},
    )
    assert client.post(f'/api/videos/{video["id"]}/retry-pose', headers=auth(user_a)).status_code == 409
    finish_pose(client, user_a, video)
    assert client.post(f'/api/videos/{video["id"]}/retry-pose', headers=auth(user_a)).status_code == 409


def test_retry_pose_before_upload_is_400_and_scoped(client, user_a, user_b):
    video = register_video(client, user_a)
    assert client.post(f'/api/videos/{video["id"]}/retry-pose', headers=auth(user_a)).status_code == 400
    assert client.post(f'/api/videos/{video["id"]}/retry-pose', headers=auth(user_b)).status_code == 404


def test_pose_csv_url_409_until_done_then_presigned(client, user_a, user_b):
    video = register_video(client, user_a)
    upload_video(client, user_a, video)
    response = client.get(f'/api/videos/{video["id"]}/pose-csv-url', headers=auth(user_a))
    assert response.status_code == 409
    assert response.json()['detail'] == 'pose extraction not finished (status=pending)'

    finish_pose(client, user_a, video)
    response = client.get(f'/api/videos/{video["id"]}/pose-csv-url', headers=auth(user_a))
    assert response.status_code == 200
    assert response.json()['url']
    assert response.json()['expires_in'] == 3600

    assert client.get(f'/api/videos/{video["id"]}/pose-csv-url', headers=auth(user_b)).status_code == 404


def test_export_is_409_until_pose_is_done(client, user_a):
    video = register_video(client, user_a)
    upload_video(client, user_a, video)

    response = client.post(f'/api/videos/{video["id"]}/export', headers=auth(user_a))
    assert response.status_code == 409
    assert response.json()['detail'] == 'pose extraction not finished (status=pending)'

    assert client.get(
        f'/api/videos/{video["id"]}/export/download', headers=auth(user_a), follow_redirects=False
    ).status_code == 409
    assert client.get(
        f'/api/videos/{video["id"]}/csv', headers=auth(user_a), follow_redirects=False
    ).status_code == 409

    client.post(
        f'/api/videos/{video["id"]}/pose-result',
        json={'status': 'failed', 'error': 'x'},
        headers={pose_queue.SECRET_HEADER: WORKER_SECRET},
    )
    response = client.post(f'/api/videos/{video["id"]}/export', headers=auth(user_a))
    assert response.status_code == 409
    assert 'status=failed' in response.json()['detail']

    finish_pose(client, user_a, video)
    assert client.post(f'/api/videos/{video["id"]}/export', headers=auth(user_a)).status_code == 200


# ==================== VIDEO SCOPING ====================

def test_video_list_is_per_user(client, user_a, user_b):
    register_video(client, user_a, 'a.mp4')
    register_video(client, user_b, 'b.mp4')

    a_videos = client.get('/api/videos', headers=auth(user_a)).json()
    b_videos = client.get('/api/videos', headers=auth(user_b)).json()

    assert [v['filename'] for v in a_videos] == ['a.mp4']
    assert [v['filename'] for v in b_videos] == ['b.mp4']


def test_other_users_video_is_404(client, user_a, user_b):
    video = register_video(client, user_a)
    assert client.get(f'/api/videos/{video["id"]}', headers=auth(user_a)).status_code == 200
    assert client.get(f'/api/videos/{video["id"]}', headers=auth(user_b)).status_code == 404


def test_other_user_cannot_request_upload_url(client, user_a, user_b):
    video = register_video(client, user_a)
    response = client.post(
        f'/api/videos/{video["id"]}/upload-url',
        json={'content_type': 'video/mp4'},
        headers=auth(user_b),
    )
    assert response.status_code == 404


def test_upload_url_and_confirm(client, user_a):
    video = register_video(client, user_a)

    response = client.post(
        f'/api/videos/{video["id"]}/upload-url',
        json={'content_type': 'video/mp4'},
        headers=auth(user_a),
    )
    assert response.status_code == 200
    payload = response.json()
    expected_key = f'videos/{user_a}/{video["id"]}/climb.mp4'
    assert payload['key'] == expected_key
    assert payload['url']

    confirmed = client.post(
        f'/api/videos/{video["id"]}/confirm-upload',
        json={'key': payload['key']},
        headers=auth(user_a),
    )
    assert confirmed.status_code == 200
    assert confirmed.json()['r2_video_key'] == expected_key


def test_confirm_upload_rejects_foreign_prefix(client, user_a, user_b):
    video = register_video(client, user_a)
    response = client.post(
        f'/api/videos/{video["id"]}/confirm-upload',
        json={'key': f'videos/{user_b}/999/steal.mp4'},
        headers=auth(user_a),
    )
    assert response.status_code == 400


# ==================== LABEL SCOPING ====================

def test_other_user_cannot_create_move_on_your_video(client, user_a, user_b):
    video = register_video(client, user_a)
    response = client.post(
        '/api/moves',
        json={
            'video_id': video['id'],
            'frame_start': 0, 'frame_end': 1,
            'timestamp_start_ms': 0.0, 'timestamp_end_ms': 33.0,
            'approach': 'static', 'size': 'small',
        },
        headers=auth(user_b),
    )
    assert response.status_code == 404


def test_other_user_cannot_read_or_update_move(client, user_a, user_b):
    video = register_video(client, user_a)
    move = create_move(client, user_a, video['id'])

    assert client.get(f'/api/moves/{move["id"]}', headers=auth(user_b)).status_code == 404
    assert client.put(
        f'/api/moves/{move["id"]}',
        json={'approach': 'static'},
        headers=auth(user_b),
    ).status_code == 404
    assert client.delete(f'/api/moves/{move["id"]}', headers=auth(user_b)).status_code == 404

    # Still intact for the owner.
    assert client.get(f'/api/moves/{move["id"]}', headers=auth(user_a)).json()['approach'] == 'dynamic'


def test_move_list_scoped_by_video_owner(client, user_a, user_b):
    video = register_video(client, user_a)
    create_move(client, user_a, video['id'])

    assert client.get(f'/api/videos/{video["id"]}/moves', headers=auth(user_b)).status_code == 404
    assert len(client.get(f'/api/videos/{video["id"]}/moves', headers=auth(user_a)).json()) == 1


def test_holds_and_environment_slots(client, user_a):
    video = register_video(client, user_a)
    move = create_move(client, user_a, video['id'])

    hold = client.post(
        '/api/holds',
        json={
            'video_id': video['id'],
            'bbox_x': 0.4, 'bbox_y': 0.5, 'bbox_w': 0.06, 'bbox_h': 0.05,
            'source': 'detected',
        },
        headers=auth(user_a),
    )
    assert hold.status_code == 201, hold.text
    hold_id = hold.json()['id']

    env = client.post(
        '/api/environments',
        json={
            'move_id': move['id'],
            'wall_angle': 'steep',
            'start_left': {'hold_id': hold_id, 'hold_type': 'jug', 'hold_quality': ['incut']},
            'end': {'hold_id': hold_id, 'hold_type': 'pinch', 'hold_quality': ['small']},
        },
        headers=auth(user_a),
    )
    assert env.status_code == 201, env.text
    body = env.json()
    assert body['start_left']['hold_id'] == hold_id
    assert body['start_left']['hold_quality'] == ['incut']
    # Foot slot omitted entirely - it is optional.
    assert body['foot']['hold_id'] is None
    assert body['start_right']['hold_id'] is None


def test_environment_cannot_reference_another_users_hold(client, user_a, user_b):
    video_a = register_video(client, user_a)
    hold_a = client.post(
        '/api/holds',
        json={'video_id': video_a['id'], 'bbox_x': 0.1, 'bbox_y': 0.1,
              'bbox_w': 0.1, 'bbox_h': 0.1, 'source': 'manual'},
        headers=auth(user_a),
    ).json()

    video_b = register_video(client, user_b)
    move_b = create_move(client, user_b, video_b['id'])

    response = client.post(
        '/api/environments',
        json={
            'move_id': move_b['id'],
            'wall_angle': 'slab',
            'start_left': {'hold_id': hold_a['id'], 'hold_type': 'jug'},
        },
        headers=auth(user_b),
    )
    assert response.status_code == 404


def test_outcome_and_frame_tag_scoping(client, user_a, user_b):
    video = register_video(client, user_a)
    move = create_move(client, user_a, video['id'])

    outcome = client.post(
        '/api/outcomes',
        json={'move_id': move['id'], 'result': 'success',
              'reach_detail': 'reached_controlled', 'confidence': 'high'},
        headers=auth(user_a),
    )
    assert outcome.status_code == 201, outcome.text
    assert 'foot_cut' not in outcome.json()

    tag = client.post(
        '/api/frame-tags',
        json={'move_id': move['id'], 'frame_number': 1, 'timestamp_ms': 33.0,
              'tag_type': 'sharp_pain', 'side': 'left', 'level': 6,
              'locations': ['left_shoulder'], 'note': 'tweak'},
        headers=auth(user_a),
    )
    assert tag.status_code == 201, tag.text

    # user_b sees none of it.
    assert client.get(f'/api/moves/{move["id"]}/outcome', headers=auth(user_b)).status_code == 404
    assert client.get(f'/api/moves/{move["id"]}/frame-tags', headers=auth(user_b)).status_code == 404
    assert client.put(
        f'/api/outcomes/{outcome.json()["id"]}',
        json={'result': 'fall'},
        headers=auth(user_b),
    ).status_code == 404
    assert client.delete(
        f'/api/frame-tags/{tag.json()["id"]}', headers=auth(user_b)
    ).status_code == 404


# ==================== EXPORT ====================

def test_export_writes_to_r2_and_is_scoped(client, fake_r2, user_a, user_b):
    video = ready_video(client, user_a)
    move = create_move(client, user_a, video['id'])
    client.post(
        '/api/outcomes',
        json={'move_id': move['id'], 'result': 'success',
              'reach_detail': 'reached_controlled', 'confidence': 'high'},
        headers=auth(user_a),
    )

    # Another user cannot trigger it.
    assert client.post(
        f'/api/videos/{video["id"]}/export', headers=auth(user_b)
    ).status_code == 404

    response = client.post(f'/api/videos/{video["id"]}/export', headers=auth(user_a))
    assert response.status_code == 200, response.text
    key = response.json()['r2_export_key']
    assert key == f'exports/{user_a}/{video["id"]}_labeled.csv'

    if fake_r2 is not None:
        content = fake_r2.objects[key].decode()
        header = content.splitlines()[0]
        # Raw pose columns survive, labels are appended.
        assert header.startswith('frame_number,timestamp_ms,left_elbow_angle')
        assert 'approach' in header
        assert 'start_left_hold_type' in header
        assert 'foot_hold_bbox' in header
        assert 'dyno|technical' in content
        assert 'reached_controlled' in content


def test_export_response_has_no_delete_video_option(client, fake_r2, user_a):
    video = ready_video(client, user_a)
    response = client.post(f'/api/videos/{video["id"]}/export', headers=auth(user_a))
    assert response.status_code == 200
    assert set(response.json().keys()) == {'video_id', 'r2_export_key'}


def test_export_download_redirects_to_presigned_url(client, fake_r2, user_a, user_b):
    video = ready_video(client, user_a)
    client.post(f'/api/videos/{video["id"]}/export', headers=auth(user_a))

    response = client.get(
        f'/api/videos/{video["id"]}/export/download',
        headers=auth(user_a),
        follow_redirects=False,
    )
    assert response.status_code == 307
    assert response.headers['location']

    assert client.get(
        f'/api/videos/{video["id"]}/export/download',
        headers=auth(user_b),
        follow_redirects=False,
    ).status_code == 404


def test_download_before_export_is_404(client, user_a):
    video = ready_video(client, user_a)
    response = client.get(
        f'/api/videos/{video["id"]}/export/download',
        headers=auth(user_a),
        follow_redirects=False,
    )
    assert response.status_code == 404


def test_exports_mine_lists_only_own(client, fake_r2, user_a, user_b):
    video_a = ready_video(client, user_a, 'mine.mp4')
    video_b = ready_video(client, user_b, 'theirs.mp4')
    client.post(f'/api/videos/{video_a["id"]}/export', headers=auth(user_a))
    client.post(f'/api/videos/{video_b["id"]}/export', headers=auth(user_b))

    mine = client.get('/api/exports/mine', headers=auth(user_a)).json()
    assert len(mine) == 1
    assert mine[0]['filename'] == 'mine.mp4'
    assert mine[0]['r2_export_key'].startswith(f'exports/{user_a}/')


def test_exports_mine_excludes_unexported(client, user_a):
    register_video(client, user_a)
    assert client.get('/api/exports/mine', headers=auth(user_a)).json() == []


# ==================== BULK HOLD CREATE AND UPDATE ====================
#
# Added with the frontend hold work: the detector posts a whole frame's worth of
# boxes in one request, and the overlay can move or resize one after the fact.


def test_bulk_hold_create_returns_ids_in_order(client, user_a):
    video = register_video(client, user_a)

    boxes = [
        {'bbox_x': 0.10, 'bbox_y': 0.10, 'bbox_w': 0.05, 'bbox_h': 0.05, 'source': 'detected'},
        {'bbox_x': 0.30, 'bbox_y': 0.20, 'bbox_w': 0.06, 'bbox_h': 0.04, 'source': 'detected'},
        {'bbox_x': 0.50, 'bbox_y': 0.60, 'bbox_w': 0.07, 'bbox_h': 0.07, 'source': 'manual'},
    ]
    res = client.post(
        f'/api/videos/{video["id"]}/holds', json={'holds': boxes}, headers=auth(user_a)
    )
    assert res.status_code == 201, res.text

    created = res.json()
    assert len(created) == 3
    # Order preserved, so the caller can line the response up with what it sent.
    assert [h['bbox_x'] for h in created] == [0.10, 0.30, 0.50]
    assert [h['source'] for h in created] == ['detected', 'detected', 'manual']
    assert all(h['video_id'] == video['id'] for h in created)

    listed = client.get(f'/api/videos/{video["id"]}/holds', headers=auth(user_a)).json()
    assert [h['id'] for h in listed] == [h['id'] for h in created]


def test_bulk_hold_create_accepts_an_empty_list(client, user_a):
    video = register_video(client, user_a)
    res = client.post(f'/api/videos/{video["id"]}/holds', json={'holds': []}, headers=auth(user_a))
    assert res.status_code == 201
    assert res.json() == []


def test_bulk_hold_create_is_all_or_nothing(client, user_a):
    """A bad box anywhere in the batch must leave no holds behind."""
    video = register_video(client, user_a)
    good = {'bbox_x': 0.1, 'bbox_y': 0.1, 'bbox_w': 0.05, 'bbox_h': 0.05}

    res = client.post(
        f'/api/videos/{video["id"]}/holds',
        json={'holds': [good, dict(good, source='nonsense'), good]},
        headers=auth(user_a),
    )
    assert res.status_code == 400
    assert 'Invalid source' in res.json()['detail']

    assert client.get(f'/api/videos/{video["id"]}/holds', headers=auth(user_a)).json() == []


def test_bulk_hold_create_rejects_an_oversized_batch(client, user_a):
    video = register_video(client, user_a)
    box = {'bbox_x': 0.1, 'bbox_y': 0.1, 'bbox_w': 0.05, 'bbox_h': 0.05}

    res = client.post(
        f'/api/videos/{video["id"]}/holds', json={'holds': [box] * 201}, headers=auth(user_a)
    )
    assert res.status_code == 400
    assert 'Too many holds' in res.json()['detail']
    assert client.get(f'/api/videos/{video["id"]}/holds', headers=auth(user_a)).json() == []


def test_bulk_hold_create_rejects_a_box_outside_the_frame(client, user_a):
    video = register_video(client, user_a)
    res = client.post(
        f'/api/videos/{video["id"]}/holds',
        json={'holds': [{'bbox_x': 1.5, 'bbox_y': 0.1, 'bbox_w': 0.05, 'bbox_h': 0.05}]},
        headers=auth(user_a),
    )
    assert res.status_code == 422


def test_bulk_hold_create_scoped_to_the_video_owner(client, user_a, user_b):
    video = register_video(client, user_a)
    res = client.post(
        f'/api/videos/{video["id"]}/holds',
        json={'holds': [{'bbox_x': 0.1, 'bbox_y': 0.1, 'bbox_w': 0.05, 'bbox_h': 0.05}]},
        headers=auth(user_b),
    )
    assert res.status_code == 404
    assert client.get(f'/api/videos/{video["id"]}/holds', headers=auth(user_a)).json() == []


def test_update_hold_moves_the_box(client, user_a):
    video = register_video(client, user_a)
    hold = client.post(
        '/api/holds',
        json={
            'video_id': video['id'],
            'bbox_x': 0.1, 'bbox_y': 0.1, 'bbox_w': 0.05, 'bbox_h': 0.05,
            'source': 'detected',
        },
        headers=auth(user_a),
    ).json()

    res = client.put(
        f'/api/holds/{hold["id"]}',
        json={'bbox_x': 0.42, 'bbox_y': 0.33, 'source': 'manual'},
        headers=auth(user_a),
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body['bbox_x'] == 0.42
    assert body['bbox_y'] == 0.33
    assert body['source'] == 'manual'
    # Omitted fields are left alone.
    assert body['bbox_w'] == 0.05
    assert body['bbox_h'] == 0.05


def test_update_hold_with_no_fields_is_a_no_op(client, user_a):
    video = register_video(client, user_a)
    hold = client.post(
        '/api/holds',
        json={
            'video_id': video['id'],
            'bbox_x': 0.1, 'bbox_y': 0.1, 'bbox_w': 0.05, 'bbox_h': 0.05,
        },
        headers=auth(user_a),
    ).json()

    res = client.put(f'/api/holds/{hold["id"]}', json={}, headers=auth(user_a))
    assert res.status_code == 200
    assert res.json()['bbox_x'] == 0.1


def test_update_hold_rejects_a_bad_source(client, user_a):
    video = register_video(client, user_a)
    hold = client.post(
        '/api/holds',
        json={
            'video_id': video['id'],
            'bbox_x': 0.1, 'bbox_y': 0.1, 'bbox_w': 0.05, 'bbox_h': 0.05,
        },
        headers=auth(user_a),
    ).json()

    res = client.put(f'/api/holds/{hold["id"]}', json={'source': 'nonsense'}, headers=auth(user_a))
    assert res.status_code == 400
    assert 'Invalid source' in res.json()['detail']


def test_update_hold_cannot_touch_another_users_hold(client, user_a, user_b):
    video = register_video(client, user_a)
    hold = client.post(
        '/api/holds',
        json={
            'video_id': video['id'],
            'bbox_x': 0.1, 'bbox_y': 0.1, 'bbox_w': 0.05, 'bbox_h': 0.05,
        },
        headers=auth(user_a),
    ).json()

    res = client.put(f'/api/holds/{hold["id"]}', json={'bbox_x': 0.9}, headers=auth(user_b))
    assert res.status_code == 404

    # And the original is untouched.
    still = client.get(f'/api/videos/{video["id"]}/holds', headers=auth(user_a)).json()
    assert still[0]['bbox_x'] == 0.1


def test_update_missing_hold_is_404(client, user_a):
    assert client.put('/api/holds/999999', json={'bbox_x': 0.5}, headers=auth(user_a)).status_code == 404
