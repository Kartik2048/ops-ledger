import React from 'react';
import { AlertTriangle, ArrowRight, RefreshCw, X } from 'lucide-react';
import { ConflictErrorDetail } from '../types/contracts';

interface ConflictDiffModalProps {
  conflict: ConflictErrorDetail;
  onClose: () => void;
  onReconcile: () => void;
  onForceOverwrite?: () => void;
  isOverwriting?: boolean;
}

export const ConflictDiffModal: React.FC<ConflictDiffModalProps> = ({
  conflict,
  onClose,
  onReconcile,
  onForceOverwrite,
  isOverwriting = false,
}) => {
  const isClaimCollision = conflict.error_code === 'ALREADY_CLAIMED';
  const serverState = conflict.current_state as any;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm animate-fade-in">
      <div className="relative w-full max-w-2xl bg-surface-dark border border-amber-500/50 rounded-2xl shadow-2xl overflow-hidden">
        {/* Header Banner */}
        <div className="flex items-center justify-between px-6 py-4 bg-amber-500/10 border-b border-amber-500/30">
          <div className="flex items-center space-x-3">
            <div className="p-2 bg-amber-500/20 text-amber-400 rounded-lg">
              <AlertTriangle className="w-6 h-6 animate-pulse" />
            </div>
            <div>
              <h3 className="text-lg font-bold text-white flex items-center gap-2">
                {isClaimCollision ? 'Simultaneous Claim Collision' : 'Optimistic Concurrency Conflict (HTTP 409)'}
                <span className="text-xs px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-300 font-mono border border-amber-500/30">
                  Server at v{conflict.current_version}
                </span>
              </h3>
              <p className="text-xs text-amber-200/80">
                {isClaimCollision
                  ? 'Another team member claimed this work item while you were viewing it.'
                  : 'A colleague updated this work item concurrently. Your edit was safely prevented from overwriting their changes.'}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-white p-1 rounded-lg hover:bg-slate-800 transition"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Content Body */}
        <div className="p-6 space-y-5">
          {/* Detailed Explanation */}
          <div className="text-sm text-slate-300 bg-slate-900/60 p-4 rounded-xl border border-slate-800">
            <p className="font-medium text-slate-200 mb-1">{conflict.message}</p>
            {isClaimCollision && conflict.claimed_by && (
              <div className="mt-3 flex items-center gap-3 p-3 bg-indigo-950/40 rounded-lg border border-indigo-500/30">
                <div
                  className="w-9 h-9 rounded-full flex items-center justify-center text-sm font-bold text-white shadow-inner"
                  style={{ backgroundColor: conflict.claimed_by.avatar_color }}
                >
                  {conflict.claimed_by.full_name.slice(0, 2).toUpperCase()}
                </div>
                <div>
                  <div className="text-sm font-semibold text-white">
                    {conflict.claimed_by.full_name}
                  </div>
                  <div className="text-xs text-indigo-300">{conflict.claimed_by.email}</div>
                </div>
                <div className="ml-auto text-xs text-slate-400">Assigned Owner</div>
              </div>
            )}
          </div>

          {/* Side-by-Side Diff Section */}
          {!isClaimCollision && serverState && (
            <div className="space-y-3">
              <h4 className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
                Current Server Reality (Committed by Colleague)
              </h4>
              <div className="grid grid-cols-2 gap-4">
                <div className="p-3 bg-slate-900/80 rounded-xl border border-slate-800 text-xs">
                  <div className="text-slate-400 mb-1">Title</div>
                  <div className="font-medium text-slate-200">{serverState.title || '—'}</div>
                </div>
                <div className="p-3 bg-slate-900/80 rounded-xl border border-slate-800 text-xs">
                  <div className="text-slate-400 mb-1">Status / Priority</div>
                  <div className="flex gap-2">
                    <span className="px-2 py-0.5 bg-blue-500/20 text-blue-300 rounded font-medium">
                      {serverState.status}
                    </span>
                    <span className="px-2 py-0.5 bg-rose-500/20 text-rose-300 rounded font-medium">
                      {serverState.priority}
                    </span>
                  </div>
                </div>
                <div className="col-span-2 p-3 bg-slate-900/80 rounded-xl border border-amber-500/30 text-xs bg-amber-500/5">
                  <div className="text-amber-400 font-semibold mb-1 flex items-center gap-1.5">
                    <ArrowRight className="w-3.5 h-3.5" />
                    Colleague's Updated Next Action:
                  </div>
                  <div className="text-slate-200 font-mono text-xs">
                    {serverState.next_action_required || 'None specified'}
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Footer Actions */}
        <div className="flex items-center justify-between px-6 py-4 bg-slate-900/80 border-t border-slate-800">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm text-slate-400 hover:text-slate-200 transition"
          >
            Cancel Draft
          </button>
          <div className="flex items-center gap-3">
            {onForceOverwrite && !isClaimCollision && (
              <button
                onClick={onForceOverwrite}
                disabled={isOverwriting}
                className="px-4 py-2 text-xs font-semibold text-amber-300 bg-amber-500/10 hover:bg-amber-500/20 border border-amber-500/40 rounded-xl transition disabled:opacity-50"
              >
                {isOverwriting ? 'Overwriting...' : `Overwrite at v${conflict.current_version}`}
              </button>
            )}
            <button
              onClick={onReconcile}
              className="flex items-center gap-2 px-5 py-2 text-sm font-semibold text-white bg-indigo-600 hover:bg-indigo-500 rounded-xl shadow-lg shadow-indigo-600/30 transition"
            >
              <RefreshCw className="w-4 h-4" />
              Reconcile & Load Latest Server State
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
