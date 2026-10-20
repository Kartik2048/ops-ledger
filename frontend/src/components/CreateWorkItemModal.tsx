import React, { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import {
  AlertCircle,
  AlertTriangle,
  CheckCircle2,
  FileCheck,
  FileCode,
  HelpCircle,
  Lock,
  PlusCircle,
  ShieldAlert,
  Wallet,
  X,
} from 'lucide-react';
import { api } from '../api/client';
import { useUser } from '../context/UserContext';
import { Priority, WorkItemCategory, WorkItemCreateRequest } from '../types/contracts';

interface CreateWorkItemModalProps {
  isOpen: boolean;
  onClose: () => void;
  onCreated?: (newItemId: string) => void;
}

const CATEGORIES: { value: WorkItemCategory; label: string; icon: React.ElementType }[] = [
  { value: 'CUSTOMER_ISSUE', label: 'Customer Issue', icon: HelpCircle },
  { value: 'ENGINEERING_PROBLEM', label: 'Engineering Problem', icon: FileCode },
  { value: 'PAYMENT_INVESTIGATION', label: 'Payment Investigation', icon: Wallet },
  { value: 'PRODUCTION_INCIDENT', label: 'Production Incident', icon: ShieldAlert },
  { value: 'COMPLIANCE_REQUEST', label: 'Compliance Request', icon: FileCheck },
  { value: 'OPERATIONAL_APPROVAL', label: 'Operational Approval', icon: Lock },
];

const PRIORITIES: { value: Priority; label: string; color: string }[] = [
  { value: 'LOW', label: 'Low', color: 'text-slate-400 border-slate-700' },
  { value: 'MEDIUM', label: 'Medium', color: 'text-blue-400 border-blue-500/40' },
  { value: 'HIGH', label: 'High', color: 'text-amber-400 border-amber-500/40' },
  { value: 'CRITICAL', label: 'Critical', color: 'text-rose-400 border-rose-500/40 bg-rose-500/10' },
];

export const CreateWorkItemModal: React.FC<CreateWorkItemModalProps> = ({
  isOpen,
  onClose,
  onCreated,
}) => {
  const { currentUser, teams } = useUser();
  const queryClient = useQueryClient();

  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [teamId, setTeamId] = useState(teams[0]?.id || '');
  const [category, setCategory] = useState<WorkItemCategory>('CUSTOMER_ISSUE');
  const [priority, setPriority] = useState<Priority>('MEDIUM');
  const [nextAction, setNextAction] = useState('Initial triage required');
  const [requiresApproval, setRequiresApproval] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  // Sync teamId when teams load
  React.useEffect(() => {
    if (!teamId && teams.length > 0) {
      setTeamId(teams[0].id);
    }
  }, [teams, teamId]);

  const resetForm = () => {
    setTitle('');
    setDescription('');
    setCategory('CUSTOMER_ISSUE');
    setPriority('MEDIUM');
    setNextAction('Initial triage required');
    setRequiresApproval(false);
    setErrorMsg(null);
    if (teams.length > 0) {
      setTeamId(teams[0].id);
    }
  };

  const handleClose = () => {
    setErrorMsg(null);
    onClose();
  };

  const createMutation = useMutation({
    mutationFn: (payload: WorkItemCreateRequest) =>
      api.createWorkItem(payload, currentUser?.id),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['workItems'] });
      queryClient.invalidateQueries({ queryKey: ['dashboardStats'] });
      resetForm();
      onClose();
      if (onCreated) onCreated(data.id);
    },
    onError: (err: any) => {
      setErrorMsg(err.message || 'Failed to create work item');
    },
  });

  if (!isOpen) return null;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMsg(null);

    if (!title.trim() || title.length < 3) {
      setErrorMsg('Title must be at least 3 characters.');
      return;
    }
    if (!description.trim()) {
      setErrorMsg('Description is required.');
      return;
    }
    if (!teamId) {
      setErrorMsg('Please select an owning team.');
      return;
    }

    createMutation.mutate({
      title: title.trim(),
      description: description.trim(),
      category,
      priority,
      team_id: teamId,
      requires_approval: requiresApproval,
      next_action_required: nextAction.trim() || 'Initial triage required',
    });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm animate-fade-in overflow-y-auto">
      <div className="relative w-full max-w-2xl bg-surface-dark border border-slate-700 rounded-2xl shadow-2xl overflow-hidden my-8">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 bg-slate-900/80 border-b border-slate-800">
          <div className="flex items-center space-x-3">
            <div className="p-2 bg-brand-500/20 text-brand-400 rounded-lg">
              <PlusCircle className="w-5 h-5" />
            </div>
            <div>
              <h3 className="text-base font-bold text-white">Create Operational Work Item</h3>
              <p className="text-xs text-slate-400">
                Logged under authenticated persona: <span className="text-indigo-400 font-medium">{currentUser?.full_name}</span>
              </p>
            </div>
          </div>
          <button
            onClick={handleClose}
            className="text-slate-400 hover:text-white p-1 rounded-lg hover:bg-slate-800 transition"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Form Body */}
        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          {errorMsg && (
            <div className="flex items-center gap-2 p-3 text-xs text-rose-300 bg-rose-500/10 border border-rose-500/30 rounded-xl">
              <AlertCircle className="w-4 h-4 flex-shrink-0" />
              <span>{errorMsg}</span>
            </div>
          )}

          {/* Title */}
          <div>
            <label className="block text-xs font-semibold text-slate-300 mb-1.5 uppercase tracking-wider">
              Title / Short Summary *
            </label>
            <input
              type="text"
              required
              placeholder="e.g., Stripe Gateway 504 Timeout during webhook ingestion"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              className="w-full px-3.5 py-2.5 bg-slate-900/90 border border-slate-700 rounded-xl text-sm text-white placeholder-slate-500 focus:outline-none focus:border-brand-500 transition"
            />
          </div>

          {/* Team & Priority Row */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1.5 uppercase tracking-wider">
                Owning Operational Team *
              </label>
              <select
                value={teamId}
                onChange={(e) => setTeamId(e.target.value)}
                className="w-full px-3.5 py-2.5 bg-slate-900/90 border border-slate-700 rounded-xl text-sm text-white focus:outline-none focus:border-brand-500 transition"
              >
                {teams.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1.5 uppercase tracking-wider">
                Priority Tier *
              </label>
              <div className="grid grid-cols-4 gap-1.5">
                {PRIORITIES.map((p) => (
                  <button
                    key={p.value}
                    type="button"
                    onClick={() => setPriority(p.value)}
                    className={`py-2 px-1 text-xs font-semibold rounded-lg border text-center transition ${
                      priority === p.value
                        ? 'border-indigo-500 bg-indigo-500/20 text-white shadow-sm'
                        : `${p.color} bg-slate-900/60 hover:bg-slate-800`
                    }`}
                  >
                    {p.label}
                  </button>
                ))}
              </div>
            </div>
          </div>

          {/* Category Selector */}
          <div>
            <label className="block text-xs font-semibold text-slate-300 mb-1.5 uppercase tracking-wider">
              Work Category *
            </label>
            <div className="grid grid-cols-3 gap-2">
              {CATEGORIES.map((c) => {
                const IconComponent = c.icon;
                const isSelected = category === c.value;
                return (
                  <button
                    key={c.value}
                    type="button"
                    onClick={() => {
                      setCategory(c.value);
                      if (c.value === 'OPERATIONAL_APPROVAL' || c.value === 'COMPLIANCE_REQUEST') {
                        setRequiresApproval(true);
                      }
                    }}
                    className={`flex items-center gap-2 p-2.5 rounded-xl border text-xs font-medium text-left transition ${
                      isSelected
                        ? 'bg-brand-500/20 border-brand-500 text-white shadow'
                        : 'bg-slate-900/60 border-slate-800 text-slate-300 hover:border-slate-700'
                    }`}
                  >
                    <IconComponent className={`w-4 h-4 ${isSelected ? 'text-brand-400' : 'text-slate-400'}`} />
                    <span className="truncate">{c.label}</span>
                  </button>
                );
              })}
            </div>
          </div>

          {/* What Requires Attention Next */}
          <div>
            <label className="block text-xs font-semibold text-amber-300 mb-1.5 uppercase tracking-wider flex items-center gap-1.5">
              <AlertTriangle className="w-3.5 h-3.5" />
              What Requires Attention Next *
            </label>
            <input
              type="text"
              required
              placeholder="e.g., On-call engineer must verify primary DB connection pool saturation"
              value={nextAction}
              onChange={(e) => setNextAction(e.target.value)}
              className="w-full px-3.5 py-2.5 bg-slate-900/90 border border-amber-500/30 rounded-xl text-sm text-amber-200 placeholder-slate-500 focus:outline-none focus:border-amber-400 transition"
            />
          </div>

          {/* Description */}
          <div>
            <label className="block text-xs font-semibold text-slate-300 mb-1.5 uppercase tracking-wider">
              Exhaustive Description & Context *
            </label>
            <textarea
              required
              rows={3}
              placeholder="Detail error logs, symptoms, affected customers, and steps taken so far..."
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              className="w-full px-3.5 py-2.5 bg-slate-900/90 border border-slate-700 rounded-xl text-sm text-white placeholder-slate-500 focus:outline-none focus:border-brand-500 transition resize-none"
            />
          </div>

          {/* Requires Approval Toggle */}
          <div className="flex items-start gap-3 p-3.5 bg-indigo-950/30 border border-indigo-500/30 rounded-xl">
            <input
              type="checkbox"
              id="requires_approval"
              checked={requiresApproval}
              onChange={(e) => setRequiresApproval(e.target.checked)}
              className="mt-1 w-4 h-4 text-brand-600 bg-slate-900 border-slate-700 rounded focus:ring-brand-500 cursor-pointer"
            />
            <label htmlFor="requires_approval" className="text-xs cursor-pointer">
              <div className="font-semibold text-indigo-200">
                Requires Formal Approval before Resolution (Approval Gate)
              </div>
              <div className="text-slate-400 text-[11px] mt-0.5">
                When enabled, the deterministic state machine prevents entering <span className="font-mono text-emerald-400">RESOLVED</span> directly. Only users with <span className="text-indigo-300 font-semibold">APPROVER</span> or <span className="text-indigo-300 font-semibold">LEAD</span> role in the owning team can authorize resolution.
              </div>
            </label>
          </div>

          {/* Actions */}
          <div className="flex items-center justify-end gap-3 pt-3 border-t border-slate-800">
            <button
              type="button"
              onClick={handleClose}
              className="px-4 py-2 text-sm text-slate-400 hover:text-white transition"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={createMutation.isPending}
              className="flex items-center gap-2 px-6 py-2.5 text-sm font-semibold text-white bg-indigo-600 hover:bg-indigo-500 rounded-xl shadow-lg shadow-indigo-600/30 transition disabled:opacity-50"
            >
              <CheckCircle2 className="w-4 h-4" />
              {createMutation.isPending ? 'Submitting...' : 'Create Work Item'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
