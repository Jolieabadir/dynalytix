/**
 * MyQueue — the rater's assignments, oldest first, as `/api/me/assignments`
 * returns them. Opening one hands the assignment to the rating view.
 *
 * Re-fetched on every mount so a status change made in the rating view
 * (in_progress, done) shows the moment the rater comes back.
 */
import { useEffect, useState } from 'react';
import useStore from '../store/useStore';
import { getMyAssignments } from '../api/client';

const STATUS_LABEL = {
  assigned: 'Not started',
  in_progress: 'In progress',
  done: 'Done',
};

function formatDate(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString();
}

function MyQueue({ onOpen }) {
  const assignments = useStore((s) => s.assignments);
  const setAssignments = useStore((s) => s.setAssignments);
  // Starts true: the effect below fetches on mount and clears it.
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let active = true;
    getMyAssignments()
      .then((items) => {
        if (active) setAssignments(items);
      })
      .catch((err) => {
        if (active) setError(err.response?.data?.detail || err.message || 'Could not load your queue.');
      })
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [setAssignments]);

  return (
    <div className="queue-view">
      <div className="view-header">
        <h2>My queue</h2>
        <p className="view-subtitle">
          Videos assigned to you for rating. Each one is rated independently —
          you never see another rater's labels, and they never see yours.
        </p>
      </div>

      {error && <div className="error-message">{error}</div>}

      {loading && assignments.length === 0 ? (
        <p className="queue-empty">Loading your queue…</p>
      ) : assignments.length === 0 ? (
        <p className="queue-empty">
          Nothing assigned yet. An admin will assign videos to you; check back later.
        </p>
      ) : (
        <table className="data-table queue-table">
          <thead>
            <tr>
              <th>Video</th>
              <th>Moves</th>
              <th>Cohort</th>
              <th>Status</th>
              <th>Assigned</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {assignments.map(({ assignment, video, move_count }) => (
              <tr key={assignment.id} data-testid={`queue-row-${assignment.id}`}>
                <td className="cell-primary">{video.filename}</td>
                <td>{move_count}</td>
                <td>{assignment.cohort}</td>
                <td>
                  <span className={`status-pill status-${assignment.status}`}>
                    {STATUS_LABEL[assignment.status] || assignment.status}
                  </span>
                </td>
                <td>{formatDate(assignment.assigned_at)}</td>
                <td>
                  <button
                    type="button"
                    className="btn-primary"
                    onClick={() => onOpen({ assignment, video, move_count })}
                  >
                    {assignment.status === 'done' ? 'Review' : 'Rate'}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

export default MyQueue;
