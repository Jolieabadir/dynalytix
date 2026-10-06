/**
 * WaitingForValidation — what a rater sees after the profile gate until an
 * admin approves them.
 *
 * The API already answers /api/me/assignments with [] for an unvalidated
 * profile; this screen says why, instead of an empty queue that looks like
 * "nothing assigned yet". An admin sets is_validated from the Admin tab.
 */
function WaitingForValidation({ profile }) {
  return (
    <div className="queue-view waiting-validation" data-testid="waiting-for-validation">
      <div className="view-header">
        <h2>Waiting for validation</h2>
        <p className="view-subtitle">
          Thanks{profile?.display_name ? `, ${profile.display_name}` : ''}: your rater profile is saved.
          An admin needs to approve your rater profile before videos can be assigned to you.
        </p>
      </div>
      <p className="queue-empty">
        There is nothing to do until then. Once you are validated, assigned videos appear in
        My queue the next time you open the app.
      </p>
    </div>
  );
}

export default WaitingForValidation;
