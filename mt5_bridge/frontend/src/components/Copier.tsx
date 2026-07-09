import { useState, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import type { Instance } from '../types';
import NewsPanel from './NewsPanel';

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
        risk_usd: updatedInst.risk_usd !== undefined ? updatedInst.risk_usd : (original.risk_usd || 100),
        symbol_mapping: updatedInst.symbol_mapping !== undefined ? updatedInst.symbol_mapping : (original.symbol_mapping || '{}'),
        auto_trade: updatedInst.auto_trade !== undefined ? updatedInst.auto_trade : (original.auto_trade || 0),
        accepted_timeframe: updatedInst.accepted_timeframe !== undefined ? updatedInst.accepted_timeframe : (original.accepted_timeframe || 'all'),
        profit_limit: updatedInst.profit_limit !== undefined ? updatedInst.profit_limit : (original.profit_limit || 0),
        alert_drawdown_limit: updatedInst.alert_drawdown_limit !== undefined ? updatedInst.alert_drawdown_limit : (original.alert_drawdown_limit || 2.0),
        alert_daily_profit_target: updatedInst.alert_daily_profit_target !== undefined ? updatedInst.alert_daily_profit_target : (original.alert_daily_profit_target || 0),
        account_type: updatedInst.account_type !== undefined ? updatedInst.account_type : (original.account_type || 'PERSONAL'),
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
      risk_usd: 100,
      profit_limit: 0,
      accepted_timeframe: 'all',
      auto_trade: 0,
      symbol_mapping: '{}',
      alert_drawdown_limit: 2.0,
      alert_daily_profit_target: 0,
      account_type: 'PERSONAL',
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
          risk_usd: editingInstance.risk_usd || 100,
          profit_limit: editingInstance.profit_limit || 0,
          accepted_timeframe: editingInstance.accepted_timeframe || 'all',
          auto_trade: editingInstance.auto_trade || 0,
          symbol_mapping: editingInstance.symbol_mapping || '{}',
          alert_drawdown_limit: editingInstance.alert_drawdown_limit || 2.0,
          alert_daily_profit_target: editingInstance.alert_daily_profit_target || 0,
          account_type: editingInstance.account_type || 'PERSONAL',
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
          risk_usd: editingInstance.risk_usd,
          profit_limit: editingInstance.profit_limit,
          accepted_timeframe: editingInstance.accepted_timeframe,
          auto_trade: editingInstance.auto_trade,
          alert_drawdown_limit: editingInstance.alert_drawdown_limit,
          alert_daily_profit_target: editingInstance.alert_daily_profit_target,
          account_type: editingInstance.account_type,
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
    <div className="workspace" style={{ padding: '8px', overflow: 'hidden', display: 'flex', flexDirection: 'column', gap: '8px', height: 'calc(100vh - 36px)' }}>

      <NewsPanel />

      {/* Grid Desk Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', background: 'var(--bg-toolbar)', border: '1px solid var(--border-color)', padding: '6px 12px', borderRadius: '2px', flexShrink: 0 }}>
        <div>
          <span style={{ fontSize: '12px', fontWeight: 'bold', color: 'var(--text-main)', letterSpacing: '0.5px' }}>COPIER ROUTING MATRIX</span>
          <span style={{ color: 'var(--text-muted)', fontSize: '10px', marginLeft: '10px' }}>Spreadsheet Desk configuration of Master/Sub accounts</span>
        </div>
        <button className="btn-toolbar" style={{ borderColor: 'var(--color-active)', color: 'var(--color-active)', fontWeight: 'bold', display: 'flex', alignItems: 'center', gap: '4px' }} onClick={handleOpenAddModal}>
          <span>+ Add Instance</span>
        </button>
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
                <th style={{ width: '80px', textAlign: 'center' }}>Auto Trade</th>
                <th style={{ width: '110px' }}>Timeframe</th>
                <th style={{ width: '100px', textAlign: 'right' }}>Profit Limit</th>
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
                  const roleColor = isMaster ? '#f39c12' : isSub ? '#3498db' : 'var(--text-muted)';
                  
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
                          <option value="PROVIDER" disabled={hasProvider && !isMaster} style={{ color: '#f39c12' }}>Master (ZMQ Out)</option>
                          <option value="CONSUMER" style={{ color: '#3498db' }}>Sub (ZMQ In)</option>
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

                      {/* Auto Trade (Switch) */}
                      <td style={{ textAlign: 'center' }}>
                        <input
                          type="checkbox"
                          checked={inst.auto_trade === 1}
                          onChange={(e) => updateInstanceMutation.mutate({ id: inst.id, auto_trade: e.target.checked ? 1 : 0 })}
                          style={{ cursor: 'pointer', accentColor: 'var(--color-active)' }}
                        />
                      </td>

                      {/* Timeframe */}
                      <td>
                        <select
                          value={inst.accepted_timeframe || 'all'}
                          onChange={(e) => updateInstanceMutation.mutate({ id: inst.id, accepted_timeframe: e.target.value })}
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
                          <option value="all">All Timeframes</option>
                          <option value="1">1 min</option>
                          <option value="3">3 mins</option>
                          <option value="5">5 mins</option>
                          <option value="15">15 mins</option>
                          <option value="30">30 mins</option>
                          <option value="60">1 hour</option>
                          <option value="240">4 hours</option>
                          <option value="D">Daily</option>
                        </select>
                      </td>

                      {/* Profit Limit */}
                      <td style={{ textAlign: 'right' }}>
                        <ControlledNumericInput
                          value={inst.profit_limit || 0}
                          prefix="$"
                          onChange={(val) => {
                            updateInstanceMutation.mutate({ id: inst.id, profit_limit: val });
                          }}
                          style={{
                            width: '80px',
                            marginLeft: 'auto',
                          }}
                        />
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
        <div className="modal-overlay active" style={{ position: 'fixed', top: 0, left: 0, width: '100vw', height: '100vh', background: 'rgba(0, 0, 0, 0.65)', display: 'flex', justifyContent: 'center', alignItems: 'center', zIndex: 1100 }}>
          <div className="modal" style={{ width: '460px', background: 'var(--bg-panel)', border: '1px solid var(--border-dark)', overflow: 'hidden' }}>
            <div className="modal-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 12px', background: 'var(--bg-toolbar)', borderBottom: '1px solid var(--border-color)' }}>
              <strong style={{ fontSize: '11px', color: 'var(--text-main)' }}>
                {editingInstance.id === -1 ? 'ADD NEW INSTANCE NODE' : `EDIT NODE: ${editingInstance.name.toUpperCase()}`}
              </strong>
              <button
                className="btn-close-modal"
                style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: '16px' }}
                onClick={() => setEditingInstance(null)}
              >
                &times;
              </button>
            </div>
            <div className="modal-body" style={{ padding: '12px', display: 'flex', flexDirection: 'column', gap: '10px' }}>
              
              {/* Form Grid */}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px' }}>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '3px' }}>
                  <label style={{ color: 'var(--text-muted)', fontSize: '9px', fontWeight: 'bold' }}>Instance Name</label>
                  <input
                    type="text"
                    value={editingInstance.name}
                    onChange={(e) => setEditingInstance((prev) => prev ? { ...prev, name: e.target.value } : null)}
                    placeholder="e.g. IC Markets Live"
                    style={{ background: 'var(--bg-app)', color: 'var(--text-main)', border: '1px solid var(--border-color)', padding: '4px', fontSize: '10px', fontFamily: 'monospace', outline: 'none' }}
                  />
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '3px' }}>
                  <label style={{ color: 'var(--text-muted)', fontSize: '9px', fontWeight: 'bold' }}>Default Risk ($)</label>
                  <input
                    type="number"
                    value={editingInstance.risk_usd || 100}
                    onChange={(e) => setEditingInstance((prev) => prev ? { ...prev, risk_usd: parseFloat(e.target.value) } : null)}
                    style={{ background: 'var(--bg-app)', color: 'var(--text-main)', border: '1px solid var(--border-color)', padding: '4px', fontSize: '10px', fontFamily: 'monospace', outline: 'none' }}
                  />
                </div>
              </div>

              {/* Path Browser */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: '3px' }}>
                <label style={{ color: 'var(--text-muted)', fontSize: '9px', fontWeight: 'bold' }}>MetaTrader 5 Executable Path</label>
                <div style={{ display: 'flex', gap: '4px' }}>
                  <input
                    type="text"
                    value={editingInstance.path}
                    onChange={(e) => setEditingInstance((prev) => prev ? { ...prev, path: e.target.value } : null)}
                    placeholder="C:\Program Files\...\terminal64.exe"
                    style={{ flex: 1, background: 'var(--bg-app)', color: 'var(--text-main)', border: '1px solid var(--border-color)', padding: '4px', fontSize: '10px', fontFamily: 'monospace', outline: 'none' }}
                  />
                  <button className="btn-toolbar" style={{ borderColor: 'var(--color-active)', color: 'var(--color-active)' }} onClick={handleBrowsePath}>
                    Browse...
                  </button>
                </div>
              </div>

              {/* Secondary Details Grid */}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px' }}>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '3px' }}>
                  <label style={{ color: 'var(--text-muted)', fontSize: '9px', fontWeight: 'bold' }}>Profit Limit ($)</label>
                  <input
                    type="number"
                    value={editingInstance.profit_limit || 0}
                    onChange={(e) => setEditingInstance((prev) => prev ? { ...prev, profit_limit: parseFloat(e.target.value) } : null)}
                    placeholder="0 = No Limit"
                    style={{ background: 'var(--bg-app)', color: 'var(--text-main)', border: '1px solid var(--border-color)', padding: '4px', fontSize: '10px', fontFamily: 'monospace', outline: 'none' }}
                  />
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '3px' }}>
                  <label style={{ color: 'var(--text-muted)', fontSize: '9px', fontWeight: 'bold' }}>Accepted Timeframe</label>
                  <select
                    value={editingInstance.accepted_timeframe || 'all'}
                    onChange={(e) => setEditingInstance((prev) => prev ? { ...prev, accepted_timeframe: e.target.value } : null)}
                    style={{ background: 'var(--bg-app)', color: 'var(--text-main)', border: '1px solid var(--border-color)', padding: '4px', fontSize: '10px', outline: 'none' }}
                  >
                    <option value="all">All Timeframes</option>
                    <option value="1">1 min</option>
                    <option value="3">3 mins</option>
                    <option value="5">5 mins</option>
                    <option value="15">15 mins</option>
                    <option value="30">30 mins</option>
                    <option value="60">1 hour</option>
                    <option value="240">4 hours</option>
                    <option value="D">Daily</option>
                  </select>
                </div>
              </div>

              {/* Account Classification */}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px' }}>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '3px' }}>
                  <label style={{ color: 'var(--text-muted)', fontSize: '9px', fontWeight: 'bold' }}>Account Type</label>
                  <select
                    value={editingInstance.account_type || 'PERSONAL'}
                    onChange={(e) => setEditingInstance((prev) => prev ? { ...prev, account_type: e.target.value } : null)}
                    style={{ background: 'var(--bg-app)', color: 'var(--text-main)', border: '1px solid var(--border-color)', padding: '4px', fontSize: '10px', outline: 'none' }}
                  >
                    <option value="PERSONAL">Personal</option>
                    <option value="PROPFIRM">Prop Firm</option>
                  </select>
                </div>
              </div>

              {/* Alert Configs */}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px' }}>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '3px' }}>
                  <label style={{ color: 'var(--text-muted)', fontSize: '9px', fontWeight: 'bold' }}>Telegram: Alert Drawdown Limit (%)</label>
                  <input
                    type="number"
                    value={editingInstance.alert_drawdown_limit ?? 2.0}
                    onChange={(e) => setEditingInstance((prev) => prev ? { ...prev, alert_drawdown_limit: parseFloat(e.target.value) } : null)}
                    placeholder="2.0"
                    step="0.1"
                    style={{ background: 'var(--bg-app)', color: 'var(--text-main)', border: '1px solid var(--border-color)', padding: '4px', fontSize: '10px', fontFamily: 'monospace', outline: 'none' }}
                  />
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '3px' }}>
                  <label style={{ color: 'var(--text-muted)', fontSize: '9px', fontWeight: 'bold' }}>Telegram: Daily Profit Target ($)</label>
                  <input
                    type="number"
                    value={editingInstance.alert_daily_profit_target ?? 0}
                    onChange={(e) => setEditingInstance((prev) => prev ? { ...prev, alert_daily_profit_target: parseFloat(e.target.value) } : null)}
                    placeholder="0 = Disabled"
                    style={{ background: 'var(--bg-app)', color: 'var(--text-main)', border: '1px solid var(--border-color)', padding: '4px', fontSize: '10px', fontFamily: 'monospace', outline: 'none' }}
                  />
                </div>
              </div>

              {/* Inline switches */}
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', background: 'var(--bg-app)', border: '1px solid var(--border-color)', padding: '6px 8px', marginTop: '4px' }}>
                <div style={{ display: 'flex', flexDirection: 'column' }}>
                  <span style={{ fontSize: '10px', color: 'var(--text-main)', fontWeight: 'bold' }}>ZMQ Auto-Trading Mode</span>
                  <span style={{ fontSize: '8px', color: 'var(--text-muted)' }}>Executes trades instantly without popup dialogs</span>
                </div>
                <input
                  type="checkbox"
                  checked={editingInstance.auto_trade === 1}
                  onChange={(e) => setEditingInstance((prev) => prev ? { ...prev, auto_trade: e.target.checked ? 1 : 0 } : null)}
                  style={{ cursor: 'pointer', accentColor: 'var(--color-active)', marginLeft: 'auto' }}
                />
              </div>

            </div>
            <div className="modal-footer" style={{ padding: '8px 12px', background: 'var(--bg-toolbar)', borderTop: '1px solid var(--border-color)', display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
              <button className="btn-toolbar" style={{ borderColor: 'var(--border-color)' }} onClick={() => setEditingInstance(null)}>
                Cancel
              </button>
              <button className="btn-toolbar" style={{ borderColor: 'var(--color-active)', color: 'var(--color-active)', fontWeight: 'bold' }} onClick={handleSaveInstance}>
                {editingInstance.id === -1 ? 'Add Node' : 'Save Changes'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* MODAL 2: SYMBOL MAPPING MATRIX CONFIG */}
      {mappingInstance && (
        <div className="modal-overlay active" style={{ position: 'fixed', top: 0, left: 0, width: '100vw', height: '100vh', background: 'rgba(0, 0, 0, 0.65)', display: 'flex', justifyContent: 'center', alignItems: 'center', zIndex: 1100 }}>
          <div className="modal" style={{ width: '420px', background: 'var(--bg-panel)', border: '1px solid var(--border-dark)', overflow: 'hidden' }}>
            <div className="modal-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 12px', background: 'var(--bg-toolbar)', borderBottom: '1px solid var(--border-color)' }}>
              <strong style={{ fontSize: '11px', color: 'var(--text-main)' }}>
                SYMBOL MAPPING DESK: {mappingInstance.name.toUpperCase()}
              </strong>
              <button
                className="btn-close-modal"
                style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: '16px' }}
                onClick={() => setMappingInstance(null)}
              >
                &times;
              </button>
            </div>
            <div className="modal-body" style={{ padding: '12px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
              
              <span style={{ fontSize: '9px', color: 'var(--text-muted)' }}>
                Map incoming signals (e.g. TradingView tickers) to MT5 specific symbols.
              </span>

              {/* Add Mapping Row */}
              <div style={{ display: 'flex', gap: '4px', background: 'var(--bg-app)', border: '1px solid var(--border-color)', padding: '6px' }}>
                <input
                  type="text"
                  placeholder="TV Ticker (e.g. XAUUSD)"
                  value={newTvSymbol}
                  onChange={(e) => setNewTvSymbol(e.target.value)}
                  style={{ flex: 1, background: 'var(--bg-panel)', color: 'var(--text-main)', border: '1px solid var(--border-color)', padding: '3px', fontSize: '10px', outline: 'none' }}
                />
                <span style={{ color: 'var(--text-muted)', alignSelf: 'center' }}>→</span>
                <input
                  type="text"
                  placeholder="MT5 Symbol (e.g. GOLD.m)"
                  value={newMt5Symbol}
                  onChange={(e) => setNewMt5Symbol(e.target.value)}
                  style={{ flex: 1, background: 'var(--bg-panel)', color: 'var(--text-main)', border: '1px solid var(--border-color)', padding: '3px', fontSize: '10px', outline: 'none' }}
                />
                <button className="btn-toolbar" style={{ borderColor: 'var(--color-buy)', color: 'var(--color-buy)' }} onClick={handleAddMappingItem}>
                  + Add
                </button>
              </div>

              {/* Existing Mappings List */}
              <div style={{ border: '1px solid var(--border-color)', background: 'var(--bg-app)', maxHeight: '180px', overflowY: 'auto' }}>
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
                        <td colSpan={3} style={{ textAlign: 'center', padding: '12px', color: 'var(--text-muted)' }}>
                          No symbol mappings defined. Executes raw ticker by default.
                        </td>
                      </tr>
                    ) : (
                      tempMappings.map((map) => (
                        <tr key={map.tv}>
                          <td style={{ fontWeight: 'bold' }}>{map.tv}</td>
                          <td style={{ color: 'var(--color-active)' }}>{map.mt5}</td>
                          <td style={{ textAlign: 'center' }}>
                            <button
                              className="btn-toolbar"
                              style={{ padding: '0px 4px', fontSize: '8px', color: 'var(--color-sell)', borderColor: 'transparent' }}
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
            <div className="modal-footer" style={{ padding: '8px 12px', background: 'var(--bg-toolbar)', borderTop: '1px solid var(--border-color)', display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
              <button className="btn-toolbar" style={{ borderColor: 'var(--border-color)' }} onClick={() => setMappingInstance(null)}>
                Cancel
              </button>
              <button className="btn-toolbar" style={{ borderColor: 'var(--color-active)', color: 'var(--color-active)', fontWeight: 'bold' }} onClick={handleSaveMapping}>
                Save Mapping Desk
              </button>
            </div>
          </div>
        </div>
      )}

    </div>
  );
};

export default Copier;
