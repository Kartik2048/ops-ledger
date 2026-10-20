import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  AlertCircle,
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Clock,
  FileText,
  Send,
  Shield,
  UserPlus,
  X,
  Zap,
} from 'lucide-react';
import { api, ApiError } from '../api/client';
import { useUser } from '../context/UserContext';
import {
  AuditLogResponse,
  ConflictErrorDetail,
  TeamRole,
  WorkItemStatus,
} from '../types/contracts';
import { ConflictDiffModal } from './ConflictDiffModal';

interface WorkItemDetailProps {
  itemId: string;
  onClose: () => void;
}

const ALLOWED_TRANSITIONS: Record<string, WorkItemStatus[]> = {
  TRIAGE: ['IN_PROGRESS', 'CANCELLED'],
  IN_PROGRESS: ['BLOCKED', 'PENDING_APPROVAL', 'RESOLVED', 'CANCELLED'],
  BLOCKED: ['IN_PROGRESS', 'CANCELLED'],
  PENDING_APPROVAL: ['RESOLVED', 'IN_PROGRESS', 'CANCELLED'],
  RESOLVED: ['IN_PROGRESS'],
  CANCELLED: [],
};

export const WorkItemDetail: React.FC<WorkItemDetailProps> = ({ itemId, onClose }) => {
  const { currentUser, getUserTeamRole, replayMode, lastIdempotencyKey } = useUser();
  const queryClient = useQueryClient();

  const [activeTab, setActiveTab] = useState<'details' | 'timeline'>('details');
  const [commentText, setCommentText] = useState('');
  const [activeConflict, setActiveConflict] = useState<ConflictErrorDetail | null>(null);
  const [transitionModalOpen, setTransitionModalOpen] = useState(false);
  const [targetStatus, setTargetStatus] = useState<WorkItemStatus>('IN_PROGRESS');
  const [actionReason, setActionReason] = useState('');
  const [actionNextAction, setActionNextAction] = useState('');
  const [errorBanner, setErrorBanner] = useState<string | null>(null);
  const [successToast, setSuccessToast] = useState<string | null>(null);
  const [transitionModalError, setTransitionModalError] = useState<string | null>(null);

  // Stale state simulation indicator
  const [isStaleSimulated, setIsStaleSimulated] = useState(false);

  // Reset modal and draft states when switching work items
  React.useEffect(() => {
    setActiveTab('details');
    setCommentText('');
    setActionReason('');
    setActionNextAction('');
    setTransitionModalError(null);
    setTransitionModalOpen(false);
    setErrorBanner(null);
    setActiveConflict(null);
    setIsStaleSimulated(false);
  }, [itemId]);

  // Fetch full work item detail including audit logs and outbox events
  const { data: item, isLoading, refetch } = useQuery({
    queryKey: ['workItemDetail', itemId],
    queryFn: () => api.getWorkItemDetail(itemId, currentUser?.id),
    refetchInterval: isStaleSimulated ? false : 5000, // pause background refresh when testing stale collision
  });

  const owningTeamRole: TeamRole | null = item ? getUserTeamRole(item.team_id) : null;
  const isMemberOfOwningTeam = Boolean(owningTeamRole);
  const isApproverOrLead = owningTeamRole === 'APPROVER' || owningTeamRole === 'LEAD';

  const showSuccess = (msg: string) => {
    setSuccessToast(msg);
    setTimeout(() => setSuccessToast(null), 4000);
  };

  // Helper to handle mutation errors (catches 409 OCC Conflict, 403, 422)
  const handleMutationError = (err: any) => {
    if (err instanceof ApiError && err.status === 409 && err.conflictDetail) {
      setActiveConflict(err.conflictDetail);
      setIsStaleSimulated(false);
    } else {
      setErrorBanner(err.message || 'Action failed.');
      setTimeout(() => setErrorBanner(null), 6000);
    }
  };

  // Mutation: Claim Work Item
  const claimMutation = useMutation({
    mutationFn: () => {
      if (!item) throw new Error('Item not loaded');
      const key = replayMode && lastIdempotencyKey ? lastIdempotencyKey : undefined;
      return api.claimWorkItem(item.id, { expected_version: item.version }, currentUser?.id, key);
    },
    onSuccess: (data: any) => {
      queryClient.invalidateQueries({ queryKey: ['workItems'] });
      queryClient.invalidateQueries({ queryKey: ['workItemDetail', itemId] });
      queryClient.invalidateQueries({ queryKey: ['dashboardStats'] });
      showSuccess(data._isIdempotentReplay ? 'Idempotent Replay Verified: Returned cached claim state' : 'Successfully claimed work item responsibility.');
      refetch();
    },
    onError: handleMutationError,
  });

  // Mutation: Transition Status
  const transitionMutation = useMutation({
    mutationFn: () => {
      if (!item) throw new Error('Item not loaded');
      const key = replayMode && lastIdempotencyKey ? lastIdempotencyKey : undefined;
      return api.transitionStatus(
        item.id,
        {
          expected_version: item.version,
          target_status: targetStatus,
          reason: actionReason.trim() || 'Workflow transition',
          next_action_required: actionNextAction.trim() || undefined,
        },
        currentUser?.id,
        key
      );
    },
    onSuccess: (data: any) => {
      queryClient.invalidateQueries({ queryKey: ['workItems'] });
      queryClient.invalidateQueries({ queryKey: ['workItemDetail', itemId] });
      queryClient.invalidateQueries({ queryKey: ['dashboardStats'] });
      setTransitionModalOpen(false);
      setActionReason('');
      setActionNextAction('');
      setTransitionModalError(null);
      showSuccess(data._isIdempotentReplay ? 'Idempotent Replay: Cached transition response returned' : `Status changed to ${targetStatus}`);
      refetch();
    },
    onError: (err: any) => {
      if (err instanceof ApiError && err.status === 409 && err.conflictDetail) {
        setTransitionModalOpen(false);
        setActiveConflict(err.conflictDetail);
        setIsStaleSimulated(false);
      } else {
        setTransitionModalError(err.message || 'Workflow transition failed.');
        setErrorBanner(err.message || 'Action failed.');
        setTimeout(() => setErrorBanner(null), 6000);
      }
    },
  });

  // Mutation: Formal Approval Decision
  const approveMutation = useMutation({
    mutationFn: (decision: 'APPROVED' | 'REJECTED') => {
      if (!item) throw new Error('Item not loaded');
      const key = replayMode && lastIdempotencyKey ? lastIdempotencyKey : undefined;
      return api.approveWorkItem(
        item.id,
        {
          expected_version: item.version,
          decision,
          reason: actionReason.trim() || `Decision: ${decision} by ${currentUser?.full_name}`,
        },
        currentUser?.id,
        key
      );
    },
    onSuccess: (data: any) => {
      queryClient.invalidateQueries({ queryKey: ['workItems'] });
      queryClient.invalidateQueries({ queryKey: ['workItemDetail', itemId] });
      queryClient.invalidateQueries({ queryKey: ['dashboardStats'] });
      showSuccess(data._isIdempotentReplay ? 'Idempotent Replay: Cached approval decision returned' : 'Formal approval recorded and item resolved.');
      refetch();
    },
    onError: handleMutationError,
  });

  // Mutation: Add Comment
  const commentMutation = useMutation({
    mutationFn: () => {
      if (!commentText.trim()) throw new Error('Comment cannot be empty');
      return api.addComment(itemId, { comment: commentText.trim() }, currentUser?.id);
    },
    onSuccess: () => {
      setCommentText('');
      queryClient.invalidateQueries({ queryKey: ['workItemDetail', itemId] });
      showSuccess('Investigation comment appended to audit history.');
      refetch();
    },
    onError: handleMutationError,
  });

  // Mutation: Simulate Colleague Background Mutation (Test Hook for 409 Conflict)
  const simulateColleagueMutation = useMutation({
    mutationFn: () => api.simulateColleagueEdit(itemId, currentUser?.id),
    onSuccess: (updatedOnServer) => {
      // Intentionally DO NOT refresh local state!
      setIsStaleSimulated(true);
      showSuccess(
        `Simulation active! Colleague modified item to v${updatedOnServer.version}. Your view is now at STALE v${item?.version}. Try mutating it now to trigger 409 Conflict!`
      );
    },
    onError: handleMutationError,
  });

  if (isLoading || !item) {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
        <div className="p-8 bg-surface-dark border border-slate-800 rounded-2xl flex items-center gap-3 text-slate-300">
          <Clock className="w-5 h-5 animate-spin text-brand-400" />
          <span>Loading work item details...</span>
        </div>
      </div>
    );
  }

  const allowedTransitions = ALLOWED_TRANSITIONS[item.status] || [];

  return (
    <div className="fixed inset-0 z-50 overflow-hidden bg-black/60 backdrop-blur-sm animate-fade-in">
      <div className="absolute inset-y-0 right-0 flex max-w-full pl-10">
        <div className="w-screen max-w-3xl bg-surface-dark border-l border-slate-800 shadow-2xl flex flex-col">
          {/* Header Bar */}
          <div className="p-6 bg-slate-900/80 border-b border-slate-800 flex items-start justify-between">
            <div className="space-y-2">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-xs px-2.5 py-0.5 rounded-full font-mono font-semibold bg-slate-800 text-slate-300">
                  {item.category.replace(/_/g, ' ')}
                </span>
                <span
                  className={`text-xs px-2.5 py-0.5 rounded-full font-bold font-mono ${
                    item.priority === 'CRITICAL'
                      ? 'bg-rose-500/20 text-rose-300 border border-rose-500/40 animate-pulse'
                      : item.priority === 'HIGH'
                      ? 'bg-amber-500/20 text-amber-300 border border-amber-500/40'
                      : item.priority === 'MEDIUM'
                      ? 'bg-blue-500/20 text-blue-300 border border-blue-500/40'
                      : 'bg-slate-800 text-slate-400'
                  }`}
                >
                  {item.priority}
                </span>
                <span className="text-xs px-2.5 py-0.5 rounded-full font-semibold bg-indigo-500/20 text-indigo-300 border border-indigo-500/30">
                  {item.status}
                </span>
                <span className="text-xs px-2.5 py-0.5 rounded-full font-mono font-bold bg-slate-800 text-slate-300 border border-slate-700 flex items-center gap-1.5">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                  Version {item.version}
                </span>
              </div>
              <h1 className="text-xl font-bold text-white tracking-tight leading-snug">
                {item.title}
              </h1>
            </div>

            <button
              onClick={onClose}
              className="text-slate-400 hover:text-white p-2 rounded-lg hover:bg-slate-800 transition"
            >
              <X className="w-5 h-5" />
            </button>
          </div>

          {/* Toast / Banner Messages */}
          {errorBanner && (
            <div className="mx-6 mt-4 p-3 bg-rose-500/15 border border-rose-500/40 rounded-xl text-rose-300 text-xs flex items-center gap-2">
              <AlertCircle className="w-4 h-4 flex-shrink-0" />
              <span>{errorBanner}</span>
            </div>
          )}
          {successToast && (
            <div className="mx-6 mt-4 p-3 bg-emerald-500/15 border border-emerald-500/40 rounded-xl text-emerald-300 text-xs flex items-center gap-2 animate-fade-in">
              <CheckCircle2 className="w-4 h-4 flex-shrink-0" />
              <span>{successToast}</span>
            </div>
          )}

          {/* Prominent Next Action Banner */}
          <div className="mx-6 mt-4 p-4 rounded-xl bg-gradient-to-r from-amber-500/10 via-amber-500/5 to-transparent border border-amber-500/30">
            <div className="flex items-center gap-2 text-xs font-bold text-amber-400 uppercase tracking-wider mb-1">
              <AlertTriangle className="w-4 h-4" />
              What Requires Attention Next:
            </div>
            <div className="text-sm font-medium text-amber-100 font-mono">
              {item.next_action_required || 'No explicit next action defined.'}
            </div>
          </div>

          {/* Concurrency Simulator Test Card */}
          <div className="mx-6 mt-4 p-3.5 bg-indigo-950/40 border border-indigo-500/30 rounded-xl flex items-center justify-between">
            <div className="space-y-0.5">
              <div className="text-xs font-bold text-indigo-300 flex items-center gap-1.5">
                <Zap className="w-3.5 h-3.5 text-amber-400" />
                Evaluator Test Hook: Concurrency Collision (Protocol 1 & 6)
              </div>
              <p className="text-[11px] text-slate-400">
                Click to simulate another colleague updating this ticket in the database.
              </p>
            </div>
            <button
              onClick={() => simulateColleagueMutation.mutate()}
              disabled={simulateColleagueMutation.isPending}
              className={`px-3 py-1.5 text-xs font-semibold rounded-lg border transition ${
                isStaleSimulated
                  ? 'bg-rose-500/20 text-rose-300 border-rose-500/50 animate-pulse'
                  : 'bg-indigo-600/30 hover:bg-indigo-600/50 text-indigo-200 border-indigo-500/40'
              }`}
            >
              {simulateColleagueMutation.isPending
                ? 'Simulating...'
                : isStaleSimulated
                ? 'Stale State Injected! Click Below to Trigger 409'
                : 'Simulate Colleague Edit'}
            </button>
          </div>

          {/* Navigation Tabs */}
          <div className="flex items-center space-x-6 px-6 mt-4 border-b border-slate-800 text-xs font-semibold">
            <button
              onClick={() => setActiveTab('details')}
              className={`pb-3 flex items-center gap-2 transition border-b-2 ${
                activeTab === 'details'
                  ? 'border-brand-500 text-brand-400'
                  : 'border-transparent text-slate-400 hover:text-slate-200'
              }`}
            >
              <FileText className="w-4 h-4" />
              Overview & Context
            </button>
            <button
              onClick={() => setActiveTab('timeline')}
              className={`pb-3 flex items-center gap-2 transition border-b-2 ${
                activeTab === 'timeline'
                  ? 'border-brand-500 text-brand-400'
                  : 'border-transparent text-slate-400 hover:text-slate-200'
              }`}
            >
              <Clock className="w-4 h-4" />
              Immutable Audit Trail ({item.audit_logs?.length || 0})
            </button>
          </div>

          {/* Tab Content */}
          <div className="flex-1 overflow-y-auto p-6 space-y-6">
            {activeTab === 'details' ? (
              <>
                {/* Description */}
                <div>
                  <h3 className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-2">
                    Description & Diagnostic Notes
                  </h3>
                  <div className="p-4 bg-slate-900/70 border border-slate-800 rounded-xl text-sm text-slate-200 whitespace-pre-wrap leading-relaxed">
                    {item.description}
                  </div>
                </div>

                {/* Team & Ownership Grid */}
                <div className="grid grid-cols-2 gap-4">
                  <div className="p-4 bg-slate-900/60 border border-slate-800 rounded-xl">
                    <div className="text-xs text-slate-400 mb-1">Owning Team</div>
                    <div className="text-sm font-semibold text-white">{item.team?.name || 'Unassigned Team'}</div>
                    <div className="text-xs text-indigo-400 mt-1">
                      Your Role: <span className="font-mono font-bold">{owningTeamRole || 'NON_MEMBER'}</span>
                    </div>
                  </div>

                  <div className="p-4 bg-slate-900/60 border border-slate-800 rounded-xl">
                    <div className="text-xs text-slate-400 mb-1">Assigned Owner</div>
                    {item.assignee ? (
                      <div className="flex items-center gap-2.5">
                        <div
                          className="w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-bold text-white"
                          style={{ backgroundColor: item.assignee.avatar_color }}
                        >
                          {item.assignee.full_name.slice(0, 2).toUpperCase()}
                        </div>
                        <div className="text-sm font-semibold text-white truncate">
                          {item.assignee.full_name}
                        </div>
                      </div>
                    ) : (
                      <div className="text-xs text-amber-400 font-semibold flex items-center gap-1.5">
                        <AlertCircle className="w-3.5 h-3.5" />
                        Unassigned (Queue Triage Needed)
                      </div>
                    )}
                  </div>
                </div>

                {/* Approval Status Section */}
                {item.requires_approval && (
                  <div className="p-4 bg-slate-900/80 border border-slate-800 rounded-xl space-y-2">
                    <div className="flex items-center justify-between">
                      <div className="text-xs font-bold text-slate-300 uppercase tracking-wider flex items-center gap-1.5">
                        <Shield className="w-4 h-4 text-indigo-400" />
                        Formal Approval Gate
                      </div>
                      <span
                        className={`text-xs px-2.5 py-0.5 rounded-full font-bold font-mono ${
                          item.approval_status === 'APPROVED'
                            ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40'
                            : item.approval_status === 'REJECTED'
                            ? 'bg-rose-500/20 text-rose-300 border border-rose-500/40'
                            : 'bg-amber-500/20 text-amber-300 border border-amber-500/40 animate-pulse'
                        }`}
                      >
                        {item.approval_status}
                      </span>
                    </div>
                    <p className="text-xs text-slate-400">
                      {item.approval_status === 'APPROVED'
                        ? `Approved and certified by ${item.approved_by?.full_name || 'Team Authority'}.`
                        : item.approval_status === 'PENDING'
                        ? 'Item requires explicit sign-off by a designated Team Approver or Lead before entering RESOLVED.'
                        : 'Approval was rejected. Corrective action required before re-evaluation.'}
                    </p>
                  </div>
                )}

                {/* Role-Aware Action Matrix */}
                <div className="space-y-3 pt-2">
                  <h3 className="text-xs font-bold text-slate-400 uppercase tracking-wider">
                    Role-Aware Operational Controls
                  </h3>

                  <div className="flex flex-wrap gap-2.5">
                    {/* Claim Button */}
                    {!item.assignee_id && (
                      <button
                        onClick={() => claimMutation.mutate()}
                        disabled={claimMutation.isPending || !isMemberOfOwningTeam}
                        title={!isMemberOfOwningTeam ? 'Only members of this team can claim' : ''}
                        className="flex items-center gap-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-xl text-xs font-semibold shadow-lg shadow-indigo-600/25 transition disabled:opacity-40 disabled:cursor-not-allowed"
                      >
                        <UserPlus className="w-4 h-4" />
                        {claimMutation.isPending ? 'Claiming...' : 'Claim Responsibility'}
                      </button>
                    )}

                    {/* Transition Status Button */}
                    {allowedTransitions.length > 0 && (
                      <button
                        onClick={() => {
                          setTargetStatus(allowedTransitions[0]);
                          setTransitionModalError(null);
                          setTransitionModalOpen(true);
                        }}
                        disabled={!isMemberOfOwningTeam}
                        className="flex items-center gap-2 px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 rounded-xl text-xs font-semibold transition disabled:opacity-40 disabled:cursor-not-allowed"
                      >
                        <ArrowRight className="w-4 h-4 text-brand-400" />
                        Advance Status
                      </button>
                    )}

                    {/* Formal Approval Decision Buttons */}
                    {item.status === 'PENDING_APPROVAL' && (
                      <div className="flex items-center gap-2">
                        <button
                          onClick={() => approveMutation.mutate('APPROVED')}
                          disabled={approveMutation.isPending || !isApproverOrLead}
                          title={!isApproverOrLead ? 'Requires APPROVER or LEAD role in this team' : ''}
                          className="flex items-center gap-1.5 px-4 py-2 bg-emerald-600 hover:bg-emerald-500 text-white rounded-xl text-xs font-semibold shadow-lg shadow-emerald-600/25 transition disabled:opacity-40 disabled:cursor-not-allowed"
                        >
                          <CheckCircle2 className="w-4 h-4" />
                          Approve & Resolve
                        </button>
                        <button
                          onClick={() => approveMutation.mutate('REJECTED')}
                          disabled={approveMutation.isPending || !isApproverOrLead}
                          title={!isApproverOrLead ? 'Requires APPROVER or LEAD role in this team' : ''}
                          className="flex items-center gap-1.5 px-4 py-2 bg-rose-600/20 hover:bg-rose-600/30 text-rose-300 border border-rose-500/40 rounded-xl text-xs font-semibold transition disabled:opacity-40 disabled:cursor-not-allowed"
                        >
                          <X className="w-4 h-4" />
                          Reject Request
                        </button>
                      </div>
                    )}
                  </div>

                  {!isMemberOfOwningTeam && (
                    <div className="text-[11px] text-slate-500 italic">
                      * You are viewing as {currentUser?.full_name} (non-member of {item.team?.name}). Action controls are read-only per resource-level RBAC.
                    </div>
                  )}
                  {item.status === 'PENDING_APPROVAL' && !isApproverOrLead && isMemberOfOwningTeam && (
                    <div className="text-[11px] text-amber-400 italic">
                      * Approval requires APPROVER or LEAD role on this team (your role: {owningTeamRole}).
                    </div>
                  )}
                </div>
              </>
            ) : (
              /* Immutable Audit Trail Timeline */
              <div className="space-y-6">
                <div className="relative pl-6 space-y-6 before:absolute before:inset-0 before:left-2 before:w-0.5 before:bg-slate-800">
                  {item.audit_logs?.map((log: AuditLogResponse, idx: number) => (
                    <div key={log.id || idx} className="relative group">
                      {/* Timeline Dot */}
                      <div className="absolute -left-6 mt-1 w-4 h-4 rounded-full border-2 border-surface-dark bg-brand-500 ring-4 ring-surface-darkest" />

                      <div className="p-4 bg-slate-900/60 border border-slate-800 rounded-xl space-y-2 hover:border-slate-700 transition">
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2">
                            <span className="text-xs font-bold font-mono px-2 py-0.5 rounded bg-slate-800 text-slate-200">
                              {log.action_type}
                            </span>
                            <span className="text-xs text-slate-300 font-semibold">
                              {log.actor?.full_name || 'System Operator'}
                            </span>
                          </div>
                          <span className="text-[11px] text-slate-500 font-mono">
                            {new Date(log.created_at).toLocaleString()}
                          </span>
                        </div>

                        {log.reason && (
                          <div className="text-xs text-slate-300 bg-slate-950/40 p-2.5 rounded-lg border border-slate-800/80">
                            {log.reason}
                          </div>
                        )}

                        {/* State Change Diffs */}
                        {Boolean(log.previous_state?.status) && Boolean(log.new_state?.status) && (
                          <div className="flex items-center gap-2 text-[11px] font-mono text-slate-400">
                            <span className="px-1.5 py-0.5 bg-slate-800 rounded">
                              {String(log.previous_state.status)}
                            </span>
                            <ArrowRight className="w-3 h-3 text-slate-500" />
                            <span className="px-1.5 py-0.5 bg-brand-500/20 text-brand-300 rounded">
                              {String(log.new_state.status)}
                            </span>
                          </div>
                        )}
                      </div>
                    </div>
                  ))}
                </div>

                {/* Comment Box */}
                <div className="pt-4 border-t border-slate-800">
                  <div className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-2">
                    Add Investigation Note or Comment
                  </div>
                  <div className="space-y-2">
                    <textarea
                      rows={2}
                      placeholder="Record investigation findings, root cause hypotheses, or reproduction steps..."
                      value={commentText}
                      onChange={(e) => setCommentText(e.target.value)}
                      className="w-full px-3.5 py-2.5 bg-slate-900/90 border border-slate-700 rounded-xl text-xs text-white placeholder-slate-500 focus:outline-none focus:border-brand-500 transition resize-none"
                    />
                    <div className="flex justify-end">
                      <button
                        onClick={() => commentMutation.mutate()}
                        disabled={commentMutation.isPending || !commentText.trim()}
                        className="flex items-center gap-1.5 px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-xl text-xs font-semibold transition disabled:opacity-50"
                      >
                        <Send className="w-3.5 h-3.5" />
                        {commentMutation.isPending ? 'Posting...' : 'Post Comment'}
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* State Transition Modal Dialog */}
      {transitionModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm animate-fade-in">
          <div className="relative w-full max-w-md bg-surface-dark border border-slate-700 rounded-2xl p-6 space-y-4 shadow-2xl">
            <div className="flex items-center justify-between pb-2 border-b border-slate-800">
              <h3 className="text-base font-bold text-white flex items-center gap-2">
                <ArrowRight className="w-5 h-5 text-brand-400" />
                Advance Workflow State
              </h3>
              <button
                onClick={() => {
                  setTransitionModalError(null);
                  setTransitionModalOpen(false);
                }}
                className="text-slate-400 hover:text-white"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {/* Error Message Displayed Directly in the Dialog */}
            {transitionModalError && (
              <div className="p-3 bg-rose-500/15 border border-rose-500/40 rounded-xl text-rose-300 text-xs flex items-start gap-2.5">
                <AlertCircle className="w-4 h-4 text-rose-400 flex-shrink-0 mt-0.5" />
                <div className="flex-1 text-[11px] leading-relaxed">
                  <strong className="block text-rose-200 font-semibold mb-0.5">Workflow Transition Blocked:</strong>
                  {transitionModalError}
                </div>
              </div>
            )}

            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1.5">
                Target Status
              </label>
              <select
                value={targetStatus}
                onChange={(e) => {
                  setTargetStatus(e.target.value as WorkItemStatus);
                  setTransitionModalError(null);
                }}
                className="w-full px-3 py-2 bg-slate-900 border border-slate-700 rounded-xl text-xs text-white focus:outline-none focus:border-brand-500"
              >
                {allowedTransitions.map((st) => (
                  <option key={st} value={st}>
                    {st}
                  </option>
                ))}
              </select>
            </div>

            {/* Warning if trying to select RESOLVED on an item that requires approval */}
            {targetStatus === 'RESOLVED' && item.requires_approval && item.approval_status !== 'APPROVED' && (
              <div className="p-2.5 bg-amber-500/15 border border-amber-500/30 rounded-xl text-amber-300 text-[11px] flex items-start gap-2">
                <AlertTriangle className="w-4 h-4 text-amber-400 flex-shrink-0 mt-0.5" />
                <span>
                  <strong>Approval Gate:</strong> This item requires formal approval before resolution. Transitioning to RESOLVED without prior sign-off will be rejected.
                </span>
              </div>
            )}

            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1.5">
                Mandatory Audit Justification / Reason *
              </label>
              <textarea
                required
                rows={2}
                placeholder="Explain the technical or business rationale for this state transition..."
                value={actionReason}
                onChange={(e) => {
                  setActionReason(e.target.value);
                  if (transitionModalError) setTransitionModalError(null);
                }}
                className="w-full px-3 py-2 bg-slate-900 border border-slate-700 rounded-xl text-xs text-white placeholder-slate-500 focus:outline-none focus:border-brand-500 resize-none"
              />
            </div>

            <div>
              <label className="block text-xs font-semibold text-amber-300 mb-1.5">
                Update "What Requires Attention Next"
              </label>
              <input
                type="text"
                placeholder={item.next_action_required}
                value={actionNextAction}
                onChange={(e) => setActionNextAction(e.target.value)}
                className="w-full px-3 py-2 bg-slate-900 border border-slate-700 rounded-xl text-xs text-white placeholder-slate-500 focus:outline-none focus:border-amber-400"
              />
            </div>

            <div className="flex items-center justify-end gap-3 pt-3 border-t border-slate-800">
              <button
                onClick={() => {
                  setTransitionModalError(null);
                  setTransitionModalOpen(false);
                }}
                className="px-4 py-2 text-xs text-slate-400 hover:text-white"
              >
                Cancel
              </button>
              <button
                onClick={() => transitionMutation.mutate()}
                disabled={transitionMutation.isPending || !actionReason.trim()}
                className="px-5 py-2 text-xs font-semibold text-white bg-indigo-600 hover:bg-indigo-500 rounded-xl shadow transition disabled:opacity-50"
              >
                {transitionMutation.isPending ? 'Updating...' : 'Confirm Transition'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 409 Visual Conflict Reconciliation Modal */}
      {activeConflict && (
        <ConflictDiffModal
          conflict={activeConflict}
          onClose={() => setActiveConflict(null)}
          onReconcile={() => {
            setActiveConflict(null);
            refetch();
            queryClient.invalidateQueries({ queryKey: ['workItems'] });
            showSuccess('Reconciled: Loaded current server state.');
          }}
          onForceOverwrite={() => {
            // Re-send transition or update with server's current version
            setActiveConflict(null);
            refetch();
          }}
        />
      )}
    </div>
  );
};
