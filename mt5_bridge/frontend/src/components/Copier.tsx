import { useState, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import type { Instance } from '../types';
import NewsPanel from './NewsPanel';
import { Modal, Field, TermInput, TermSelect, TermButton, SectionLabel } from './ui/Terminal';

const fetchInstances = async (): Promise<Instance[]> => {
  const res = await fetch('/api/instances');
  return res.json();
};

interface ControlledNumericInputProps {
  value: number;
  onChange: (val: number) => void;
  step?: string;
  prefix?: string;
  suffix?: string;
  style?: React.CSSProperties;
}

const ControlledNumericInput = ({ value, onChange, step = '1', prefix, suffix, style }: ControlledNumericInputProps) => {
  const [localVal, setLocalVal] = useState<string>(value.toString());

  useEffect(() => {
    const parsedLocal = parseFloat(localVal);
    if (parsedLocal !== value) {
      setLocalVal(value.toString());
    }
  }, [value]);

  const handleBlur = () => {
    const parsed = parseFloat(localVal);
    if (!isNaN(parsed) && parsed !== value) {
      onChange(parsed);
    } else if (localVal === '') {
      onChange(0);
    } else {
      setLocalVal(value.toString());
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.currentTarget.blur();
    }
  };

  return (
    <div style={{ display: 'flex', alignItems: 'center', width: '100%', ...style }}>
      {prefix && <span style={{ marginRight: '2px', color: 'var(--text-muted)' }}>{prefix}</span>}
      <input
        type="number"
        step={step}
        value={localVal}
        onChange={(e) => setLocalVal(e.target.value)}
        onBlur={handleBlur}
        onKeyDown={handleKeyDown}
        style={{
          width: '100%',
          background: 'var(--bg-app)',
          color: 'var(--text-main)',
          border: '1px solid var(--border-color)',
          padding: '1px 4px',
          fontSize: '10px',
          fontFamily: 'monospace',
          outline: 'none',
        }}
      />
      {suffix && <span style={{ marginLeft: '2px', color: 'var(--text-muted)' }}>{suffix}</span>}
    </div>
  );
};

const Copier = () => {
  const queryClient = useQueryClient();
  const { data = [], isLoading } = useQuery<Instance[]>({
    queryKey: ['instances'],
    queryFn: fetchInstances,
  });

  // State for Modals
  const [editingInstance, setEditingInstance] = useState<Instance | null>(null);
  const [mappingInstance, setMappingInstance] = useState<Instance | null>(null);

  // Symbol Mapping temporary state
  const [tempMappings, setTempMappings] = useState<Array<{ tv: string; mt5: string }>>([]);
  const [newTvSymbol, setNewTvSymbol] = useState('');
  const [newMt5Symbol, setNewMt5Symbol] = useState('');

  // Mutations
  const updateCopierSettingsMutation = useMutation({
    mutationFn: async (payload: {
      id: number;
      copier_role?: string;
      copier_risk_type?: string;
      copier_fixed_lot?: number;
      copier_risk_usd?: number;
      copier_risk_multiplier?: number;
    }) => {
      const original = data.find((i) => i.id === payload.id);
      if (!original) return;

      const fullPayload = {
        id: payload.id,
        copier_role: payload.copier_role !== undefined ? payload.copier_role : original.copier_role,
        copier_risk_type: payload.copier_risk_type !== undefined ? payload.copier_risk_type : (original.copier_risk_type || 'FIXED'),
        copier_fixed_lot: payload.copier_fixed_lot !== undefined ? payload.copier_fixed_lot : (original.copier_fixed_lot || 0.01),
        copier_risk_usd: payload.copier_risk_usd !== undefined ? payload.copier_risk_usd : (original.copier_risk_usd || 100.0),
        copier_risk_multiplier: payload.copier_risk_multiplier !== undefined ? payload.copier_risk_multiplier : (original.copier_risk_multiplier || 1.0),
      };

      if (payload.copier_role === 'PROVIDER') {
        // ZMQ logic: if we set a new Master, let's clear the old master role
        // Backend handles this but let's sync locally
      }

      await fetch('/api/copier_instances/update', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(fullPayload),
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['instances'] });
    },
  });

  const updateInstanceMutation = useMutation({
    mutationFn: async (updatedInst: Partial<Instance> & { id: number }) => {
      const original = data.find((i) => i.id === updatedInst.id);
      if (!original) return;

      const payload = {
        id: updatedInst.id,
        name: updatedInst.name !== undefined ? updatedInst.name : original.name,
        path: updatedInst.path !== undefined ? updatedInst.path : original.path,
        symbol_mapping: updatedInst.symbol_mapping !== undefined ? updatedInst.symbol_mapping : (original.symbol_mapping || '{}'),
        alert_drawdown_levels: updatedInst.alert_drawdown_levels !== undefined ? updatedInst.alert_drawdown_levels : (original.alert_drawdown_levels || '2,4,6,8,10'),
        alert_profit_ceiling_usd: updatedInst.alert_profit_ceiling_usd !== undefined ? updatedInst.alert_profit_ceiling_usd : (original.alert_profit_ceiling_usd || 0),
        alert_profit_lock_pct: updatedInst.alert_profit_lock_pct !== undefined ? updatedInst.alert_profit_lock_pct : (original.alert_profit_lock_pct || 0),
        account_type: updatedInst.account_type !== undefined ? updatedInst.account_type : (original.account_type || 'PERSONAL'),
        news_block_before_min: updatedInst.news_block_before_min !== undefined ? updatedInst.news_block_before_min : (original.news_block_before_min ?? 2.0),
        news_block_after_min: updatedInst.news_block_after_min !== undefined ? updatedInst.news_block_after_min : (original.news_block_after_min ?? 2.0),
        group_name: original.group_name || 'Ungrouped',
      };

      const res = await fetch('/api/instances', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        throw new Error('Failed to update instance details.');
      }
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['instances'] });
    },
  });

  const createInstanceMutation = useMutation({
    mutationFn: async (payload: Omit<Instance, 'id' | 'copier_role'>) => {
      const res = await fetch('/api/instances', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        throw new Error('Failed to create instance.');
      }
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['instances'] });
    },
  });

  const deleteInstanceMutation = useMutation({
    mutationFn: async (id: number) => {
      const res = await fetch('/api/instances', {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id }),
      });
      if (!res.ok) {
        throw new Error('Failed to delete instance.');
      }
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['instances'] });
    },
  });

  if (isLoading) {
    return <div style={{ padding: '20px', fontFamily: 'monospace', color: 'var(--text-muted)' }}>Loading routing matrix desk...</div>;
  }

  const hasProvider = data.some((d) => d.copier_role === 'PROVIDER');

  // Trigger file browser for MT5 executable path
  const handleBrowsePath = async () => {
    try {
      const res = await fetch('/api/browse_file');
      const json = await res.json();
      if (json.path && editingInstance) {
        setEditingInstance((prev) => prev ? { ...prev, path: json.path } : null);
      }
    } catch (err) {
      console.error('Error browsing path:', err);
    }
  };

  const handleOpenAddModal = () => {
    setEditingInstance({
      id: -1,
      name: '',
      path: '',
      copier_role: 'NONE',
      symbol_mapping: '{}',
      alert_drawdown_levels: '2,4,6,8,10',
      alert_profit_ceiling_usd: 0,
      alert_profit_lock_pct: 0,
      account_type: 'PERSONAL',
      news_block_before_min: 2.0,
      news_block_after_min: 2.0,
    });
  };

  const handleOpenEditModal = (inst: Instance) => {
    setEditingInstance({ ...inst });
  };

  const handleSaveInstance = () => {
    if (!editingInstance) return;
    if (!editingInstance.name || !editingInstance.path) {
      alert('Instance Name and Executable Path are required.');
      return;
    }

    if (editingInstance.id === -1) {
      // Create new
      createInstanceMutation.mutate(
        {
          name: editingInstance.name,
          path: editingInstance.path,
          symbol_mapping: editingInstance.symbol_mapping || '{}',
          alert_drawdown_levels: editingInstance.alert_drawdown_levels || '2,4,6,8,10',
          alert_profit_ceiling_usd: editingInstance.alert_profit_ceiling_usd || 0,
          alert_profit_lock_pct: editingInstance.alert_profit_lock_pct || 0,
          account_type: editingInstance.account_type || 'PERSONAL',
          news_block_before_min: editingInstance.news_block_before_min ?? 2.0,
          news_block_after_min: editingInstance.news_block_after_min ?? 2.0,
        },
        {
          onSuccess: () => setEditingInstance(null),
        }
      );
    } else {
      // Update existing
      updateInstanceMutation.mutate(
        {
          id: editingInstance.id,
          name: editingInstance.name,
          path: editingInstance.path,
          alert_drawdown_levels: editingInstance.alert_drawdown_levels,
          alert_profit_ceiling_usd: editingInstance.alert_profit_ceiling_usd,
          alert_profit_lock_pct: editingInstance.alert_profit_lock_pct,
          account_type: editingInstance.account_type,
          news_block_before_min: editingInstance.news_block_before_min,
          news_block_after_min: editingInstance.news_block_after_min,
        },
        {
          onSuccess: () => setEditingInstance(null),
        }
      );
    }
  };

  const handleDeleteInstance = (id: number, name: string) => {
    if (confirm(`Are you sure you want to remove instance "${name}"? This deletes its risk profiles permanently.`)) {
      deleteInstanceMutation.mutate(id);
    }
  };

  // Symbol Mapping management
  const handleOpenMappingModal = (inst: Instance) => {
    setMappingInstance(inst);
    let parsed: Record<string, string> = {};
    try {
      parsed = JSON.parse(inst.symbol_mapping || '{}');
    } catch {
      parsed = {};
    }
    const list = Object.entries(parsed).map(([tv, mt5]) => ({ tv, mt5 }));
    setTempMappings(list);
    setNewTvSymbol('');
    setNewMt5Symbol('');
  };

  const handleAddMappingItem = () => {
    if (!newTvSymbol || !newMt5Symbol) return;
    if (tempMappings.some((m) => m.tv.toUpperCase() === newTvSymbol.toUpperCase())) {
      alert('Symbol mapping for this TV ticker already exists.');
      return;
    }
    setTempMappings((prev) => [...prev, { tv: newTvSymbol, mt5: newMt5Symbol }]);
    setNewTvSymbol('');
    setNewMt5Symbol('');
  };

  const handleRemoveMappingItem = (tv: string) => {
    setTempMappings((prev) => prev.filter((m) => m.tv !== tv));
  };

  const handleSaveMapping = () => {
    if (!mappingInstance) return;
    const mappingObj: Record<string, string> = {};
    tempMappings.forEach((m) => {
      mappingObj[m.tv] = m.mt5;
    });

    updateInstanceMutation.mutate(
      {
        id: mappingInstance.id,
        symbol_mapping: JSON.stringify(mappingObj),
      },
      {
        onSuccess: () => setMappingInstance(null),
      }
    );
  };

  return (
    <div style={{ padding: '10px', overflow: 'hidden', display: 'flex', flexDirection: 'column', gap: '10px', height: '100%' }}>

      <NewsPanel />

      {/* Grid Desk Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', background: 'var(--bg-toolbar)', border: '1px solid var(--border-color)', padding: '8px 12px', flexShrink: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <span className="term-glow" style={{ fontSize: '13px', fontWeight: 700, color: 'var(--terminal-accent)', letterSpacing: '0.14em', textTransform: 'uppercase' }}>
            Copier Routing Matrix
          </span>
          <span style={{ color: 'var(--text-muted)', fontSize: '10px' }}>Master / Sub account configuration desk</span>
        </div>
        <TermButton variant="solid" onClick={handleOpenAddModal}>+ Add Instance</TermButton>
      </div>

      {/* Main Matrix Grid Container */}
      <section className="pane" style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
        <div className="pane-header" style={{ fontWeight: 'normal', color: 'var(--text-muted)' }}>
          <span>Active Accounts Matrix ({data.length} Nodes)</span>
          <span>Double-click detail to edit full properties</span>
        </div>
        <div className="table-container" style={{ flex: 1, overflowY: 'auto' }}>
          <table className="data-grid" style={{ width: '100%' }}>
            <thead>
              <tr>
                <th style={{ width: '160px' }}>Name</th>
                <th style={{ width: '140px' }}>Role</th>
                <th style={{ width: '130px' }}>Risk Model</th>
                <th style={{ width: '130px' }}>Lotsize / Risk</th>
                <th style={{ width: '90px', textAlign: 'center' }}>Symbol Map</th>
                <th>Path</th>
                <th style={{ width: '100px', textAlign: 'center' }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {data.length === 0 ? (
                <tr>
                  <td colSpan={10} style={{ textAlign: 'center', padding: '30px', color: 'var(--text-muted)' }}>
                    No instances registered. Click "+ Add Instance" to setup.
                  </td>
                </tr>
              ) : (
                data.map((inst) => {
                  const isSub = inst.copier_role === 'CONSUMER';
                  const isMaster = inst.copier_role === 'PROVIDER';
                  const roleColor = isMaster ? 'var(--color-pending)' : isSub ? 'var(--terminal-accent)' : 'var(--text-muted)';
                  
                  let mapCount = 0;
                  try {
                    mapCount = Object.keys(JSON.parse(inst.symbol_mapping || '{}')).length;
                  } catch {
                    mapCount = 0;
                  }

                  return (
                    <tr key={inst.id} style={{ height: '28px' }}>
                      {/* Name */}
                      <td style={{ fontWeight: 'bold' }}>
                        <span style={{ display: 'inline-block', width: '6px', height: '6px', background: 'var(--color-buy)', borderRadius: '50%', marginRight: '6px', verticalAlign: 'middle' }}></span>
                        {inst.name}
                      </td>

                      {/* Copier Role Select Dropdown */}
                      <td>
                        <select
                          value={inst.copier_role}
                          onChange={(e) => updateCopierSettingsMutation.mutate({ id: inst.id, copier_role: e.target.value })}
                          style={{
                            width: '100%',
                            fontSize: '10px',
                            background: 'var(--bg-app)',
                            color: roleColor,
                            border: `1px solid ${inst.copier_role !== 'NONE' ? roleColor : 'var(--border-color)'}`,
                            outline: 'none',
                            padding: '1px 4px',
                            fontWeight: 'bold',
                          }}
                        >
                          <option value="NONE" style={{ color: 'var(--text-muted)' }}>Unassigned</option>
                          <option value="PROVIDER" disabled={hasProvider && !isMaster}>Master (ZMQ Out)</option>
                          <option value="CONSUMER">Sub (ZMQ In)</option>
                        </select>
                      </td>

                      {/* Risk Model (Sub Only) */}
                      <td>
                        {isSub ? (
                          <select
                            value={inst.copier_risk_type || 'FIXED'}
                            onChange={(e) => updateCopierSettingsMutation.mutate({ id: inst.id, copier_risk_type: e.target.value })}
                            style={{
                              width: '100%',
                              fontSize: '10px',
                              background: 'var(--bg-app)',
                              color: 'var(--text-main)',
                              border: '1px solid var(--border-color)',
                              outline: 'none',
                              padding: '1px 4px',
                            }}
                          >
                            <option value="FIXED">Fixed Lot</option>
                            <option value="USD">Dollar Risk ($)</option>
                            <option value="MULTIPLIER">Multiplier (x)</option>
                          </select>
                        ) : (
                          <span style={{ color: 'var(--text-muted)' }}>N/A</span>
                        )}
                      </td>

                      {/* Lotsize / Risk allocation input (Sub Only) */}
                      <td>
                        {isSub ? (
                          <ControlledNumericInput
                            value={
                              inst.copier_risk_type === 'FIXED'
                                ? inst.copier_fixed_lot || 0.01
                                : inst.copier_risk_type === 'MULTIPLIER'
                                ? inst.copier_risk_multiplier || 1.0
                                : inst.copier_risk_usd || 100
                            }
                            step={inst.copier_risk_type === 'FIXED' ? '0.01' : inst.copier_risk_type === 'MULTIPLIER' ? '0.1' : '1'}
                            prefix={inst.copier_risk_type === 'USD' ? '$' : undefined}
                            suffix={inst.copier_risk_type === 'MULTIPLIER' ? 'x' : undefined}
                            onChange={(val) => {
                              if (inst.copier_risk_type === 'FIXED') {
                                updateCopierSettingsMutation.mutate({ id: inst.id, copier_fixed_lot: val });
                              } else if (inst.copier_risk_type === 'MULTIPLIER') {
                                updateCopierSettingsMutation.mutate({ id: inst.id, copier_risk_multiplier: val });
                              } else {
                                updateCopierSettingsMutation.mutate({ id: inst.id, copier_risk_usd: val });
                              }
                            }}
                          />
                        ) : (
                          <span style={{ color: 'var(--text-muted)' }}>N/A</span>
                        )}
                      </td>

                      {/* Symbol Map config button */}
                      <td style={{ textAlign: 'center' }}>
                        {isMaster || isSub ? (
                          <button
                            className="btn-toolbar"
                            style={{
                              fontSize: '9px',
                              padding: '1px 5px',
                              margin: '0 auto',
                              borderColor: mapCount > 0 ? 'var(--color-active)' : 'var(--border-color)',
                              color: mapCount > 0 ? 'var(--color-active)' : 'var(--text-muted)',
                            }}
                            onClick={() => handleOpenMappingModal(inst)}
                          >
                            ⚙ {mapCount} Map{mapCount !== 1 ? 's' : ''}
                          </button>
                        ) : (
                          <span style={{ color: 'var(--text-muted)' }}>N/A</span>
                        )}
                      </td>

                      {/* Path */}
                      <td style={{ color: 'var(--text-muted)', fontSize: '9px', whiteSpace: 'nowrap', textOverflow: 'ellipsis', overflow: 'hidden' }} title={inst.path}>
                        {inst.path}
                      </td>

                      {/* Actions */}
                      <td style={{ textAlign: 'center' }}>
                        <div style={{ display: 'flex', justifyContent: 'center', gap: '4px' }}>
                          <button
                            className="btn-toolbar"
                            style={{ fontSize: '9px', padding: '1px 5px', borderColor: 'var(--border-color)', color: 'var(--text-main)' }}
                            onClick={() => handleOpenEditModal(inst)}
                            title="Edit Instance Details"
                          >
                            Edit
                          </button>
                          <button
                            className="btn-toolbar"
                            style={{ fontSize: '9px', padding: '1px 5px', borderColor: 'var(--color-sell)', color: 'var(--color-sell)' }}
                            onClick={() => handleDeleteInstance(inst.id, inst.name)}
                            title="Delete Instance"
                          >
                            Del
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </section>

      {/* MODAL 1: ADD / EDIT INSTANCE DETAILS */}
      {editingInstance && (
        <Modal
          title={editingInstance.id === -1 ? 'Add Instance Node' : `Edit Node · ${editingInstance.name}`}
          width={480}
          onClose={() => setEditingInstance(null)}
          footer={
            <>
              <TermButton variant="outline" onClick={() => setEditingInstance(null)}>Cancel</TermButton>
              <TermButton variant="solid" onClick={handleSaveInstance}>
                {editingInstance.id === -1 ? 'Add Node' : 'Save Changes'}
              </TermButton>
            </>
          }
        >
          <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
            <Field label="Instance Name">
              <TermInput
                type="text"
                value={editingInstance.name}
                onChange={(e) => setEditingInstance((prev) => (prev ? { ...prev, name: e.target.value } : null))}
                placeholder="e.g. IC Markets Live"
              />
            </Field>

            <Field label="MetaTrader 5 Executable Path">
              <div style={{ display: 'flex', gap: '6px' }}>
                <TermInput
                  type="text"
                  value={editingInstance.path}
                  onChange={(e) => setEditingInstance((prev) => (prev ? { ...prev, path: e.target.value } : null))}
                  placeholder="C:\Program Files\...\terminal64.exe"
                />
                <TermButton variant="outline" onClick={handleBrowsePath} style={{ flexShrink: 0 }}>Browse…</TermButton>
              </div>
            </Field>

            <Field label="Account Type">
              <TermSelect
                value={editingInstance.account_type || 'PERSONAL'}
                onChange={(e) => setEditingInstance((prev) => (prev ? { ...prev, account_type: e.target.value } : null))}
              >
                <option value="PERSONAL">Personal</option>
                <option value="PROPFIRM">Prop Firm</option>
              </TermSelect>
            </Field>

            {editingInstance.account_type === 'PROPFIRM' && (
              <>
                <SectionLabel>News Blackout Window</SectionLabel>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                  <Field label="Block Before News (min)" hint="Minutes before each high-impact event to start blocking">
                    <TermInput
                      type="number"
                      step="0.5"
                      min="0"
                      value={editingInstance.news_block_before_min ?? 2.0}
                      onChange={(e) => setEditingInstance((prev) => (prev ? { ...prev, news_block_before_min: parseFloat(e.target.value) } : null))}
                    />
                  </Field>
                  <Field label="Block After News (min)" hint="Minutes after each high-impact event to keep blocking">
                    <TermInput
                      type="number"
                      step="0.5"
                      min="0"
                      value={editingInstance.news_block_after_min ?? 2.0}
                      onChange={(e) => setEditingInstance((prev) => (prev ? { ...prev, news_block_after_min: parseFloat(e.target.value) } : null))}
                    />
                  </Field>
                </div>
              </>
            )}

            <SectionLabel>Telegram Alerts</SectionLabel>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
              <Field label="Drawdown Alert Levels (%)" hint="Comma-separated %, one alert per level as drawdown climbs">
                <TermInput
                  type="text"
                  value={editingInstance.alert_drawdown_levels ?? '2,4,6,8,10'}
                  onChange={(e) => setEditingInstance((prev) => (prev ? { ...prev, alert_drawdown_levels: e.target.value } : null))}
                  placeholder="2,4,6,8,10"
                />
              </Field>
              <Field label="Profit Lock Target (%)" hint="0 = disabled">
                <TermInput
                  type="number"
                  step="0.1"
                  value={editingInstance.alert_profit_lock_pct ?? 0}
                  onChange={(e) => setEditingInstance((prev) => (prev ? { ...prev, alert_profit_lock_pct: parseFloat(e.target.value) } : null))}
                  placeholder="0 = Disabled"
                />
              </Field>
              <Field label="Profit Ceiling (Equity $)" hint="Close all positions once equity reaches this. 0 = disabled">
                <TermInput
                  type="number"
                  step="1"
                  min="0"
                  value={editingInstance.alert_profit_ceiling_usd ?? 0}
                  onChange={(e) => setEditingInstance((prev) => (prev ? { ...prev, alert_profit_ceiling_usd: parseFloat(e.target.value) } : null))}
                  placeholder="0 = Disabled"
                />
              </Field>
            </div>
          </div>
        </Modal>
      )}

      {/* MODAL 2: SYMBOL MAPPING MATRIX CONFIG */}
      {mappingInstance && (
        <Modal
          title={`Symbol Mapping · ${mappingInstance.name}`}
          width={440}
          onClose={() => setMappingInstance(null)}
          footer={
            <>
              <TermButton variant="outline" onClick={() => setMappingInstance(null)}>Cancel</TermButton>
              <TermButton variant="solid" onClick={handleSaveMapping}>Save Mapping</TermButton>
            </>
          }
        >
          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
            <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>
              Map incoming signals (e.g. TradingView tickers) to broker-specific MT5 symbols.
            </span>

            {/* Add Mapping Row */}
            <div style={{ display: 'flex', gap: '6px', alignItems: 'center', background: 'var(--bg-app)', border: '1px solid var(--border-color)', padding: '8px' }}>
              <TermInput
                type="text"
                placeholder="TV Ticker (e.g. XAUUSD)"
                value={newTvSymbol}
                onChange={(e) => setNewTvSymbol(e.target.value)}
              />
              <span style={{ color: 'var(--terminal-accent)', flexShrink: 0 }}>&rarr;</span>
              <TermInput
                type="text"
                placeholder="MT5 Symbol (e.g. GOLD.m)"
                value={newMt5Symbol}
                onChange={(e) => setNewMt5Symbol(e.target.value)}
              />
              <TermButton variant="outline" onClick={handleAddMappingItem} style={{ flexShrink: 0 }}>+ Add</TermButton>
            </div>

            {/* Existing Mappings List */}
            <div style={{ border: '1px solid var(--border-color)', background: 'var(--bg-app)', maxHeight: '200px', overflowY: 'auto' }}>
              <table className="data-grid" style={{ width: '100%' }}>
                <thead>
                  <tr>
                    <th style={{ width: '45%' }}>Signal / TV Ticker</th>
                    <th style={{ width: '45%' }}>Execution / MT5 Symbol</th>
                    <th style={{ width: '10%', textAlign: 'center' }}></th>
                  </tr>
                </thead>
                <tbody>
                  {tempMappings.length === 0 ? (
                    <tr>
                      <td colSpan={3} style={{ textAlign: 'center', padding: '14px', color: 'var(--text-muted)' }}>
                        No symbol mappings defined. Executes raw ticker by default.
                      </td>
                    </tr>
                  ) : (
                    tempMappings.map((map) => (
                      <tr key={map.tv}>
                        <td style={{ fontWeight: 'bold' }}>{map.tv}</td>
                        <td style={{ color: 'var(--terminal-accent)' }}>{map.mt5}</td>
                        <td style={{ textAlign: 'center' }}>
                          <button
                            style={{ background: 'none', border: 'none', padding: '0 4px', fontSize: '12px', color: 'var(--color-sell)', cursor: 'pointer' }}
                            onClick={() => handleRemoveMappingItem(map.tv)}
                          >
                            &times;
                          </button>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </Modal>
      )}

    </div>
  );
};

export default Copier;
