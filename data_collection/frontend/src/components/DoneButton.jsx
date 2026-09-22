/**
 * DoneButton component.
 * 
 * Simple button that triggers the passed onClick handler.
 * The parent component handles the export logic.
 */

function DoneButton({ onClick, disabled, busy = false }) {
  return (
    <button
      onClick={onClick}
      className="done-btn"
      disabled={disabled || busy}
    >
      {busy ? 'Exporting...' : 'Done'}
    </button>
  );
}

export default DoneButton;
