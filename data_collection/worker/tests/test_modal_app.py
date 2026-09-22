"""
The job body (run_job) and the endpoint's secret check, without Modal.

`modal` must be importable (pip install modal) but no account is needed:
nothing here talks to Modal. storage/extract/report_result are stubbed so the
retry policy is what is under test: 2 retries for transient errors, none for
a PipelineError, 'failed' with pose_error at the end.
"""
import pytest

pytest.importorskip('modal')

from conftest import WORKER_ROOT  # noqa: E402
import modal_app  # noqa: E402
from extract import ExtractionMeta, PipelineError  # noqa: E402


class FakeStorage:
    def __init__(self):
        self.uploaded = {}

    def get_client(self):
        return object()

    def download_video(self, key, local_path, client=None):
        with open(local_path, 'wb') as f:
            f.write(b'video')
        return local_path

    def upload_csv(self, key, csv_text, client=None):
        self.uploaded[key] = csv_text
        return key

    @staticmethod
    def pose_csv_key(user_id, video_id):
        return f'pose/{user_id}/{video_id}.csv'

    @staticmethod
    def key_belongs_to(key, user_id):
        return key.startswith(f'videos/{user_id}/')


META = ExtractionMeta(fps=30.0, total_frames=130, duration_ms=4338.3, width=1080, height=1920,
                      frames_decoded=130, frames_with_pose=130)


@pytest.fixture
def harness(monkeypatch):
    """Stub the container-side collaborators; return (reports, storage, extract_calls)."""
    import sys
    reports = []
    storage = FakeStorage()
    extract_calls = []

    monkeypatch.setitem(sys.modules, 'storage', storage)

    def fake_report(video_id, status, error=None, **fields):
        reports.append({'video_id': video_id, 'status': status, 'error': error, **fields})

    monkeypatch.setattr(modal_app, 'report_result', fake_report)
    monkeypatch.setattr(modal_app.time, 'sleep', lambda s: None)

    behaviours = []

    def fake_extract(path, model_path, use_gpu=False):
        extract_calls.append(path)
        behaviour = behaviours.pop(0) if behaviours else 'ok'
        if isinstance(behaviour, Exception):
            raise behaviour
        return 'frame_number,timestamp_ms\n0,0', META

    import extract
    monkeypatch.setattr(extract, 'extract_pose_csv', fake_extract)
    return reports, storage, extract_calls, behaviours


def test_run_job_success_reports_processing_then_done(harness):
    reports, storage, calls, _ = harness
    result = modal_app.run_job(12, 'user-1', 'videos/user-1/12/clip.mov', use_gpu=False)

    assert result['status'] == 'done' and result['attempts'] == 1
    assert storage.uploaded == {'pose/user-1/12.csv': 'frame_number,timestamp_ms\n0,0'}
    assert [r['status'] for r in reports] == ['processing', 'done']
    done = reports[-1]
    assert done['fps'] == 30.0 and done['total_frames'] == 130
    assert (done['width'], done['height']) == (1080, 1920)
    assert done['r2_pose_csv_key'] == 'pose/user-1/12.csv'
    assert 'frames_with_pose' not in done


def test_run_job_retries_transient_errors_twice(harness):
    reports, _, calls, behaviours = harness
    behaviours.extend([RuntimeError('cuda hiccup'), OSError('r2 reset')])
    result = modal_app.run_job(1, 'u', 'videos/u/1/a.mov', use_gpu=False)

    assert result['status'] == 'done' and result['attempts'] == 3
    assert len(calls) == 3
    assert [r['status'] for r in reports] == ['processing', 'done']


def test_run_job_fails_after_three_transient_attempts(harness):
    reports, _, calls, behaviours = harness
    behaviours.extend([RuntimeError('one'), RuntimeError('two'), RuntimeError('three')])
    result = modal_app.run_job(1, 'u', 'videos/u/1/a.mov', use_gpu=False)

    assert result['status'] == 'failed'
    assert len(calls) == 3
    assert reports[-1]['status'] == 'failed'
    assert reports[-1]['error'] == 'RuntimeError: three'


def test_run_job_does_not_retry_a_pipeline_error(harness):
    reports, _, calls, behaviours = harness
    behaviours.append(PipelineError('No video stream found'))
    result = modal_app.run_job(1, 'u', 'videos/u/1/a.mov', use_gpu=False)

    assert result['status'] == 'failed'
    assert len(calls) == 1
    assert reports[-1] == {'video_id': 1, 'status': 'failed', 'error': 'No video stream found'}


def test_run_job_survives_a_failed_processing_ping(harness, monkeypatch):
    reports, _, _, _ = harness
    original = modal_app.report_result

    def flaky(video_id, status, error=None, **fields):
        if status == 'processing':
            raise RuntimeError('db down')
        original(video_id, status, error, **fields)

    monkeypatch.setattr(modal_app, 'report_result', flaky)
    assert modal_app.run_job(1, 'u', 'videos/u/1/a.mov', use_gpu=False)['status'] == 'done'
    assert [r['status'] for r in reports] == ['done']


def test_secret_matches(monkeypatch):
    monkeypatch.setenv('MODAL_WEBHOOK_SECRET', 'abc')
    assert modal_app._secret_matches('abc')
    assert modal_app._secret_matches('Bearer abc')
    assert not modal_app._secret_matches('abd')
    assert not modal_app._secret_matches(None)
    monkeypatch.delenv('MODAL_WEBHOOK_SECRET')
    assert not modal_app._secret_matches('abc')


def test_report_result_db_mode_calls_record_result(monkeypatch):
    seen = {}
    import db

    def fake_record(dsn, video_id, status, error=None, **fields):
        seen.update(dsn=dsn, video_id=video_id, status=status, error=error, **fields)
        return True

    monkeypatch.setattr(db, 'record_result', fake_record)
    monkeypatch.setenv('DATABASE_URL', 'postgresql://x')
    monkeypatch.delenv('POSE_RESULT_MODE', raising=False)
    modal_app.report_result(3, 'done', fps=30.0, r2_pose_csv_key='k')
    assert seen == {'dsn': 'postgresql://x', 'video_id': 3, 'status': 'done', 'error': None,
                    'fps': 30.0, 'r2_pose_csv_key': 'k'}


def test_report_result_callback_mode_posts_with_secret_header(monkeypatch):
    import httpx
    seen = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        seen.update(url=url, json=json, headers=headers)
        return httpx.Response(200, json={'pose_status': 'done'})

    monkeypatch.setattr(httpx, 'post', fake_post)
    monkeypatch.setenv('POSE_RESULT_MODE', 'callback')
    monkeypatch.setenv('BACKEND_URL', 'https://api.example/')
    monkeypatch.setenv('MODAL_WEBHOOK_SECRET', 's')
    modal_app.report_result(3, 'failed', error='boom', fps=None)
    assert seen['url'] == 'https://api.example/api/videos/3/pose-result'
    assert seen['json'] == {'status': 'failed', 'error': 'boom'}
    assert seen['headers'] == {'X-Webhook-Secret': 's'}


# ==================== the enqueue web endpoint, through real FastAPI ====================
#
# Regression for the production 422: `enqueue` was annotated `request: 'Request'`
# with no `Request` in module scope, so FastAPI could not resolve the annotation
# and treated `request` as a required query parameter. Every POST from the
# backend got `{"detail":[{"type":"missing","loc":["query","request"],...}]}`.
# Building the app exactly as Modal does (`add_api_route('/', fn, methods=[...])`)
# and hitting it with TestClient catches that class of bug locally.


def _raw_function(fn):
    """The plain Python function behind a `modal.Function` (or the function itself)."""
    raw = getattr(fn, '_raw_f_', None)
    if raw is None and hasattr(fn, 'get_raw_f'):  # older/newer modal
        raw = fn.get_raw_f()
    return raw or fn


@pytest.fixture
def enqueue_client(monkeypatch):
    """A TestClient for `enqueue`, with the GPU function's spawn and R2 key check stubbed."""
    fastapi = pytest.importorskip('fastapi')
    from fastapi.testclient import TestClient

    spawned = []

    class FakeCall:
        object_id = 'fc-test-123'

    class FakeExtractPose:
        @staticmethod
        def spawn(video_id, user_id, r2_key):
            spawned.append((video_id, user_id, r2_key))
            return FakeCall()

    import sys
    monkeypatch.setitem(sys.modules, 'storage', FakeStorage())
    monkeypatch.setattr(modal_app, 'extract_pose', FakeExtractPose())
    monkeypatch.setenv('MODAL_WEBHOOK_SECRET', 'topsecret')

    app = fastapi.FastAPI()
    app.add_api_route('/', _raw_function(modal_app.enqueue), methods=['POST'])
    return TestClient(app), spawned


VALID_BODY = {'video_id': 12, 'user_id': 'user-1', 'r2_key': 'videos/user-1/12/clip.mov'}


def test_enqueue_without_secret_is_401(enqueue_client):
    client, spawned = enqueue_client
    response = client.post('/', json=VALID_BODY)
    assert response.status_code == 401, response.text
    assert response.json()['detail'] == 'bad or missing worker secret'
    assert spawned == []


def test_enqueue_with_wrong_secret_is_401(enqueue_client):
    client, spawned = enqueue_client
    response = client.post('/', json=VALID_BODY, headers={'X-Webhook-Secret': 'nope'})
    assert response.status_code == 401, response.text
    assert spawned == []


def test_enqueue_with_secret_and_missing_fields_is_400(enqueue_client):
    client, spawned = enqueue_client
    response = client.post('/', json={'video_id': 12}, headers={'X-Webhook-Secret': 'topsecret'})
    assert response.status_code == 400, response.text
    assert response.json()['detail'] == 'video_id, user_id and r2_key are required'
    assert spawned == []


def test_enqueue_rejects_r2_key_of_another_user(enqueue_client):
    client, spawned = enqueue_client
    body = {**VALID_BODY, 'r2_key': 'videos/someone-else/12/clip.mov'}
    response = client.post('/', json=body, headers={'X-Webhook-Secret': 'topsecret'})
    assert response.status_code == 400, response.text
    assert response.json()['detail'] == 'r2_key does not belong to user_id'
    assert spawned == []


def test_enqueue_with_secret_and_valid_body_spawns_and_returns_200(enqueue_client):
    client, spawned = enqueue_client
    response = client.post('/', json=VALID_BODY, headers={'X-Webhook-Secret': 'topsecret'})
    assert response.status_code == 200, response.text
    assert response.json() == {'accepted': True, 'video_id': 12, 'call_id': 'fc-test-123'}
    assert spawned == [(12, 'user-1', 'videos/user-1/12/clip.mov')]


def test_enqueue_accepts_bearer_authorization_header(enqueue_client):
    client, spawned = enqueue_client
    response = client.post('/', json=VALID_BODY, headers={'Authorization': 'Bearer topsecret'})
    assert response.status_code == 200, response.text
    assert len(spawned) == 1


def test_vendored_model_is_present():
    model = WORKER_ROOT / 'models' / 'pose_landmarker_full.task'
    assert model.exists()
    assert 8_000_000 < model.stat().st_size < 10_500_000
