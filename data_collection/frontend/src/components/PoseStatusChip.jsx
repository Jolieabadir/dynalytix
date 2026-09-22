/**
 * Header chip: where the background work is.
 *
 * Two jobs run behind the labeling UI once a file is picked — the upload to
 * R2, then the pose worker. The chip shows whichever is in flight, turns
 * green when the skeleton is ready, and offers a retry when the worker
 * failed. It owns the status poll (usePoseStatus) because it is mounted for
 * the whole time a video is open.
 */
import useStore from '../store/useStore';
import usePoseStatus from '../hooks/usePoseStatus';

const CHIP_TEXT = {
  uploading: (fraction) => `Uploading video… ${Math.round(fraction * 100)}%`,
  confirming: 'Finishing upload…',
  uploadFailed: 'Upload failed',
  pending: 'Pose extraction queued',
  processing: 'Extracting pose on the server…',
  done: 'Pose ready',
  failed: 'Pose extraction failed',
};

function PoseStatusChip() {
  const currentVideo = useStore((s) => s.currentVideo);
  const upload = useStore((s) => s.upload);
  const { state, poseError, error, retry, retrying } = usePoseStatus();

  if (!currentVideo) return null;

  let tone = 'pending';
  let text;
  let detail = null;
  let showRetry = false;

  if (upload.state === 'uploading') {
    text = CHIP_TEXT.uploading(upload.fraction);
  } else if (upload.state === 'confirming') {
    text = CHIP_TEXT.confirming;
  } else if (upload.state === 'failed') {
    tone = 'failed';
    text = CHIP_TEXT.uploadFailed;
    detail = upload.error;
  } else if (state === 'done') {
    tone = 'done';
    text = CHIP_TEXT.done;
  } else if (state === 'failed') {
    tone = 'failed';
    text = CHIP_TEXT.failed;
    detail = poseError;
    showRetry = true;
  } else if (state === 'processing') {
    tone = 'processing';
    text = CHIP_TEXT.processing;
  } else {
    text = CHIP_TEXT.pending;
  }

  return (
    <div
      className={`pose-chip pose-chip-${tone}`}
      role="status"
      aria-live="polite"
      data-testid="pose-status-chip"
      title={detail || error || undefined}
    >
      {tone === 'pending' || tone === 'processing' ? <span className="pose-chip-spinner" /> : null}
      <span className="pose-chip-text">{text}</span>
      {upload.state === 'uploading' && (
        <span className="pose-chip-bar" aria-hidden="true">
          <span className="pose-chip-bar-fill" style={{ width: `${Math.round(upload.fraction * 100)}%` }} />
        </span>
      )}
      {detail && <span className="pose-chip-detail">{detail}</span>}
      {error && !detail && <span className="pose-chip-detail">{error}</span>}
      {showRetry && (
        <button
          type="button"
          className="pose-chip-retry"
          onClick={retry}
          disabled={retrying}
        >
          {retrying ? 'Retrying…' : 'Retry'}
        </button>
      )}
    </div>
  );
}

export default PoseStatusChip;
