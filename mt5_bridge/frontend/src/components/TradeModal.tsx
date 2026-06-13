const TradeModal = ({ isOpen, onClose }: { isOpen: boolean; onClose: () => void }) => {
  if (!isOpen) return null;

  return (
    <div className="modal-overlay" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)', zIndex: 1000 }}>
      <div className="modal" style={{ background: 'var(--bg-app)', border: '1px solid var(--border-dark)', width: '400px', borderRadius: '4px' }}>
        <div className="modal-header" style={{ display: 'flex', justifyContent: 'space-between', padding: '10px', background: 'var(--bg-panel)', borderBottom: '1px solid var(--border-color)' }}>
          <span>Trade Execution</span>
          <button onClick={onClose} style={{ background: 'transparent', border: 'none', color: 'var(--text-main)', cursor: 'pointer' }}>&times;</button>
        </div>
        <div className="modal-body" style={{ padding: '15px' }}>
          <p style={{ color: 'var(--text-muted)' }}>Trade execution form will go here...</p>
        </div>
      </div>
    </div>
  );
};

export default TradeModal;
