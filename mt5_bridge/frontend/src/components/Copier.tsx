import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import type { Instance } from '../types';

const fetchCopierData = async (): Promise<Instance[]> => {
  const res = await fetch('/api/copier_instances');
  return res.json();
};

interface InstanceCardProps {
  inst: Instance;
  onRoleChange: (id: number, role: string) => void;
  onRiskChange: (id: number, field: string, value: string) => void;
  hasProvider: boolean;
}

const InstanceCard = ({ inst, onRoleChange, onRiskChange, hasProvider }: InstanceCardProps) => {
  return (
    <div className="dense-card" style={{ background: 'var(--bg-panel)', border: '1px solid var(--border-dark)', padding: '6px 8px', display: 'flex', flexDirection: 'column', gap: '6px', fontSize: '10px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <strong style={{ color: 'var(--text-main)', fontSize: '11px' }}>{inst.name}</strong>
        <div style={{ display: 'flex', gap: '4px' }}>
          <button className="btn-toolbar" style={{ fontSize: '9px', padding: '0 4px', borderColor: 'var(--color-active)', color: 'var(--color-active)' }}>Edit</button>
          <button className="btn-toolbar" style={{ fontSize: '9px', padding: '0 4px', borderColor: 'var(--color-sell)', color: 'var(--color-sell)' }}>Del</button>
        </div>
      </div>
      <div style={{ marginTop: '4px' }}>
        <select 
          className="dense-input" 
          style={{ width: '100%', borderColor: inst.copier_role === 'PROVIDER' ? '#f39c12' : inst.copier_role === 'CONSUMER' ? '#3498db' : 'var(--border-color)', background: 'var(--bg-toolbar)', color: 'var(--text-main)', padding: '2px 4px' }}
          value={inst.copier_role}
          onChange={(e) => onRoleChange(inst.id, e.target.value)}
        >
          <option value="NONE">Unassigned</option>
          <option value="PROVIDER" disabled={hasProvider && inst.copier_role !== 'PROVIDER'}>Master (Provider)</option>
          <option value="CONSUMER">Sub (Consumer)</option>
        </select>
      </div>
      <div style={{ color: 'var(--text-muted)', textOverflow: 'ellipsis', overflow: 'hidden', whiteSpace: 'nowrap', marginTop: '4px' }}>
        {inst.path}
      </div>
      {inst.copier_role === 'CONSUMER' && (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', background: 'var(--bg-app)', padding: '4px', border: '1px solid var(--border-dark)', marginTop: '4px' }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
            <label style={{ color: 'var(--text-muted)' }}>Risk Type</label>
            <select 
              className="dense-input" 
              value={inst.copier_risk_type || 'FIXED'} 
              onChange={(e) => onRiskChange(inst.id, 'type', e.target.value)}
              style={{ background: 'var(--bg-toolbar)', color: 'var(--text-main)', border: '1px solid var(--border-color)', padding: '2px 4px' }}
            >
              <option value="FIXED">Fixed Lot</option>
              <option value="USD">Dollar Risk ($)</option>
              <option value="MULTIPLIER">Multiplier (x)</option>
            </select>
          </div>
          {inst.copier_risk_type === 'FIXED' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
              <label style={{ color: 'var(--text-muted)' }}>Lot Size</label>
              <input type="number" step="0.01" className="dense-input" value={inst.copier_fixed_lot || 0.01} onChange={(e) => onRiskChange(inst.id, 'fixed', e.target.value)} style={{ background: 'var(--bg-toolbar)', color: 'var(--text-main)', border: '1px solid var(--border-color)', padding: '2px 4px' }} />
            </div>
          )}
          {inst.copier_risk_type === 'USD' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
              <label style={{ color: 'var(--text-muted)' }}>Risk ($)</label>
              <input type="number" className="dense-input" value={inst.copier_risk_usd || 100} onChange={(e) => onRiskChange(inst.id, 'usd', e.target.value)} style={{ background: 'var(--bg-toolbar)', color: 'var(--text-main)', border: '1px solid var(--border-color)', padding: '2px 4px' }} />
            </div>
          )}
          {inst.copier_risk_type === 'MULTIPLIER' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
              <label style={{ color: 'var(--text-muted)' }}>Multiplier</label>
              <input type="number" step="0.1" className="dense-input" value={inst.copier_risk_multiplier || 1.0} onChange={(e) => onRiskChange(inst.id, 'mult', e.target.value)} style={{ background: 'var(--bg-toolbar)', color: 'var(--text-main)', border: '1px solid var(--border-color)', padding: '2px 4px' }} />
            </div>
          )}
        </div>
      )}
    </div>
  );
};

const Copier = () => {
  const queryClient = useQueryClient();
  const { data = [], isLoading } = useQuery<Instance[]>({ queryKey: ['copier'], queryFn: fetchCopierData });

  const updateRoleMutation = useMutation({
    mutationFn: async ({ id, role }: { id: number; role: string }) => {
      await fetch('/api/copier_instances/update', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id, copier_role: role }),
      });
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['copier'] }),
  });

  const updateRiskMutation = useMutation({
    mutationFn: async ({ id, field, value, inst }: { id: number; field: string; value: string; inst: Instance }) => {
      const payload = {
        id,
        copier_role: inst.copier_role,
        copier_risk_type: inst.copier_risk_type,
        copier_fixed_lot: inst.copier_fixed_lot,
        copier_risk_usd: inst.copier_risk_usd,
        copier_risk_multiplier: inst.copier_risk_multiplier
      };
      
      if (field === 'type') payload.copier_risk_type = value;
      else if (field === 'fixed') payload.copier_fixed_lot = parseFloat(value);
      else if (field === 'usd') payload.copier_risk_usd = parseFloat(value);
      else if (field === 'mult') payload.copier_risk_multiplier = parseFloat(value);
      
      await fetch('/api/copier_instances/update', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['copier'] }),
  });

  if (isLoading) return <div style={{ padding: '20px' }}>Loading instances...</div>;

  const hasProvider = data.some((d) => d.copier_role === 'PROVIDER');
  const unassigned = data.filter((d) => d.copier_role === 'NONE');
  const providers = data.filter((d) => d.copier_role === 'PROVIDER');
  const consumers = data.filter((d) => d.copier_role === 'CONSUMER');

  return (
    <div className="workspace" style={{ display: 'grid', gridTemplateColumns: '350px 1fr', gap: '8px', padding: '8px' }}>
      <section className="pane">
        <div className="pane-header" style={{ display: 'flex', justifyContent: 'space-between' }}>
          <span>Available Instances</span>
          <button className="btn btn-primary-premium" style={{ padding: '2px 8px', fontSize: '10px' }}>+ Add Instance</button>
        </div>
        <div className="pane-content" style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
          {unassigned.length === 0 && <div style={{ color: 'var(--text-muted)', fontStyle: 'italic', padding: '4px' }}>All instances assigned.</div>}
          {unassigned.map((inst) => (
            <InstanceCard key={inst.id} inst={inst} onRoleChange={(id: number, role: string) => updateRoleMutation.mutate({ id, role })} onRiskChange={(id: number, field: string, value: string) => updateRiskMutation.mutate({ id, field, value, inst })} hasProvider={hasProvider} />
          ))}
        </div>
      </section>

      <div style={{ display: 'grid', gridTemplateRows: 'auto 1fr', gap: '8px' }}>
        <section className="pane" style={{ borderTop: '2px solid #f39c12' }}>
          <div className="pane-header">
            <span style={{ color: '#f39c12', fontWeight: 'bold' }}>Master (Provider)</span>
          </div>
          <div className="pane-content" style={{ display: 'flex', flexDirection: 'column', gap: '4px', minHeight: '80px' }}>
            {providers.length === 0 && <div style={{ color: 'var(--text-muted)', fontStyle: 'italic', padding: '4px' }}>No Master assigned.</div>}
            {providers.map((inst) => (
              <InstanceCard key={inst.id} inst={inst} onRoleChange={(id: number, role: string) => updateRoleMutation.mutate({ id, role })} onRiskChange={(id: number, field: string, value: string) => updateRiskMutation.mutate({ id, field, value, inst })} hasProvider={hasProvider} />
            ))}
          </div>
        </section>

        <section className="pane" style={{ borderTop: '2px solid #3498db' }}>
          <div className="pane-header">
            <span style={{ color: '#3498db', fontWeight: 'bold' }}>Subs (Consumers)</span>
          </div>
          <div className="pane-content" style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
            {consumers.length === 0 && <div style={{ color: 'var(--text-muted)', fontStyle: 'italic', padding: '4px' }}>No Subs assigned.</div>}
            {consumers.map((inst) => (
              <InstanceCard key={inst.id} inst={inst} onRoleChange={(id: number, role: string) => updateRoleMutation.mutate({ id, role })} onRiskChange={(id: number, field: string, value: string) => updateRiskMutation.mutate({ id, field, value, inst })} hasProvider={hasProvider} />
            ))}
          </div>
        </section>
      </div>
    </div>
  );
};

export default Copier;
