import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Activity,
  AlertOctagon,
  AlertTriangle,
  CheckCircle2,
  Clock,
  Play,
  RefreshCw,
  X,
  Zap,
} from 'lucide-react';
import { api } from '../api/client';
import { OutboxEventResponse, OutboxStatus } from '../types/contracts';

interface OutboxDrawerProps {
  isOpen: boolean;
  onClose: () => void;
}

export const OutboxDrawer: React.FC<OutboxDrawerProps> = ({ isOpen, onClose }) => {
  const queryClient = useQueryClient();
  const [selectedStatus, setSelectedStatus] = useState<string>('');

  // Fetch outbox queue status & events
  const { data, isLoading, refetch } = useQuery({
    queryKey: ['outboxQueue', selectedStatus],
    queryFn: () => api.getOutboxQueue(selectedStatus || undefined),
    refetchInterval: isOpen ? 3000 : false, // Auto-poll every 3s when drawer is open
  });

  // Mutation: Trigger immediate batch processing
  const processBatchMutation = useMutation({
    mutationFn: api.triggerOutboxProcess,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['outboxQueue'] });
      queryClient.invalidateQueries({ queryKey: ['dashboardStats'] });
    },
  });

  // Mutation: Simulate failing task
  const simulateFailMutation = useMutation({
    mutationFn: () => api.simulateOutboxFailure(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['outboxQueue'] });
    },
  });

  // Mutation: Retry dead-letter event
  const retryMutation = useMutation({
    mutationFn: (eventId: string) => api.retryOutboxEvent(eventId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['outboxQueue'] });
      queryClient.invalidateQueries({ queryKey: ['dashboardStats'] });
    },
  });

  if (!isOpen) return null;

  const counts = data?.counts_by_status || {
    PENDING: 0,
    PROCESSING: 0,
    COMPLETED: 0,
    FAILED: 0,
    DEAD_LETTER: 0,
  };

  const getStatusBadge = (status: OutboxStatus, attempts: number, maxAttempts: number) => {
    switch (status) {
      case 'COMPLETED':
        return (
          <span className="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/30">
            <CheckCircle2 className="w-3.5 h-3.5" />
            COMPLETED
          </span>
        );
      case 'PENDING':
        return (
          <span className="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-amber-500/10 text-amber-400 border border-amber-500/30">
            <Clock className="w-3.5 h-3.5" />
            PENDING
          </span>
        );
      case 'FAILED':
        return (
          <span className="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-orange-500/10 text-orange-400 border border-orange-500/30">
            <AlertTriangle className="w-3.5 h-3.5" />
            FAILED ({attempts}/{maxAttempts})
          </span>
        );
      case 'DEAD_LETTER':
        return (
          <span className="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-rose-500/20 text-rose-300 border border-rose-500/40 animate-pulse">
            <AlertOctagon className="w-3.5 h-3.5" />
            DEAD LETTER (DLQ)
          </span>
        );
      case 'PROCESSING':
        return (
          <span className="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-blue-500/10 text-blue-400 border border-blue-500/30">
            <RefreshCw className="w-3.5 h-3.5 animate-spin" />
            PROCESSING
          </span>
        );
    }
  };

  return (
    <div className="fixed inset-0 z-50 overflow-hidden bg-black/60 backdrop-blur-sm animate-fade-in">
      <div className="absolute inset-y-0 right-0 flex max-w-full pl-10">
        <div className="w-screen max-w-2xl bg-surface-dark border-l border-slate-800 shadow-2xl flex flex-col">
          {/* Header */}
          <div className="flex items-center justify-between p-6 bg-slate-900/60 border-b border-slate-800">
            <div className="flex items-center gap-3">
              <div className="p-2.5 bg-brand-500/20 text-brand-400 rounded-xl">
                <Activity className="w-6 h-6 animate-pulse" />
              </div>
              <div>
                <h2 className="text-lg font-bold text-white flex items-center gap-2">
                  Transactional Outbox Queue
                  <span className="text-xs px-2 py-0.5 rounded-full bg-slate-800 text-slate-300 font-mono">
                    Protocol 5
                  </span>
                </h2>
                <p className="text-xs text-slate-400">
                  Reliable asynchronous secondary side effects with exponential backoff & DLQ
                </p>
              </div>
            </div>
            <button
              onClick={onClose}
              className="text-slate-400 hover:text-white p-2 rounded-lg hover:bg-slate-800 transition"
            >
              <X className="w-5 h-5" />
            </button>
          </div>

          {/* Quick Metrics Bar */}
          <div className="grid grid-cols-4 gap-2 p-4 bg-slate-950/60 border-b border-slate-800 text-center">
            <div
              onClick={() => setSelectedStatus('')}
              className={`p-2.5 rounded-xl cursor-pointer transition ${
                selectedStatus === '' ? 'bg-indigo-600/20 border border-indigo-500/40' : 'bg-slate-900/50 hover:bg-slate-900'
              }`}
            >
              <div className="text-xs text-slate-400">Total</div>
              <div className="text-lg font-bold text-white">{data?.total || 0}</div>
            </div>
            <div
              onClick={() => setSelectedStatus('COMPLETED')}
              className={`p-2.5 rounded-xl cursor-pointer transition ${
                selectedStatus === 'COMPLETED' ? 'bg-emerald-500/20 border border-emerald-500/40' : 'bg-slate-900/50 hover:bg-slate-900'
              }`}
            >
              <div className="text-xs text-emerald-400">Completed</div>
              <div className="text-lg font-bold text-emerald-300">{counts.COMPLETED}</div>
            </div>
            <div
              onClick={() => setSelectedStatus('FAILED')}
              className={`p-2.5 rounded-xl cursor-pointer transition ${
                selectedStatus === 'FAILED' ? 'bg-amber-500/20 border border-amber-500/40' : 'bg-slate-900/50 hover:bg-slate-900'
              }`}
            >
              <div className="text-xs text-amber-400">Retrying</div>
              <div className="text-lg font-bold text-amber-300">{counts.FAILED}</div>
            </div>
            <div
              onClick={() => setSelectedStatus('DEAD_LETTER')}
              className={`p-2.5 rounded-xl cursor-pointer transition ${
                selectedStatus === 'DEAD_LETTER' ? 'bg-rose-500/20 border border-rose-500/40' : 'bg-slate-900/50 hover:bg-slate-900'
              }`}
            >
              <div className="text-xs text-rose-400">Dead Letter</div>
              <div className="text-lg font-bold text-rose-300">{counts.DEAD_LETTER}</div>
            </div>
          </div>

          {/* Controls Bar */}
          <div className="flex items-center justify-between p-4 bg-slate-900/40 border-b border-slate-800">
            <div className="flex items-center gap-2">
              <button
                onClick={() => processBatchMutation.mutate()}
                disabled={processBatchMutation.isPending}
                className="flex items-center gap-2 px-3.5 py-1.5 text-xs font-semibold text-white bg-indigo-600 hover:bg-indigo-500 rounded-lg shadow transition disabled:opacity-50"
              >
                <Play className="w-3.5 h-3.5" />
                {processBatchMutation.isPending ? 'Processing...' : 'Trigger Worker Batch'}
              </button>
              <button
                onClick={() => simulateFailMutation.mutate()}
                disabled={simulateFailMutation.isPending}
                className="flex items-center gap-2 px-3.5 py-1.5 text-xs font-semibold text-amber-300 bg-amber-500/10 hover:bg-amber-500/20 border border-amber-500/30 rounded-lg transition disabled:opacity-50"
              >
                <Zap className="w-3.5 h-3.5" />
                {simulateFailMutation.isPending ? 'Injecting...' : 'Simulate Failing Task'}
              </button>
            </div>
            <button
              onClick={() => refetch()}
              className="p-1.5 text-slate-400 hover:text-white hover:bg-slate-800 rounded-lg transition"
              title="Refresh Queue"
            >
              <RefreshCw className="w-4 h-4" />
            </button>
          </div>

          {/* Event Listing */}
          <div className="flex-1 overflow-y-auto p-4 space-y-3">
            {isLoading ? (
              <div className="flex items-center justify-center p-12 text-slate-400 text-sm">
                <RefreshCw className="w-5 h-5 animate-spin mr-2 text-indigo-400" />
                Loading outbox events...
              </div>
            ) : data?.events.length === 0 ? (
              <div className="text-center p-12 text-slate-500 text-sm">
                No events matching filter.
              </div>
            ) : (
              data?.events.map((event: OutboxEventResponse) => (
                <div
                  key={event.id}
                  className="p-4 bg-slate-900/70 border border-slate-800 rounded-xl space-y-2.5 hover:border-slate-700 transition"
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-xs font-bold text-slate-200">
                        {event.event_type}
                      </span>
                      {getStatusBadge(event.status, event.attempts, event.max_attempts)}
                    </div>
                    <span className="text-[11px] text-slate-500 font-mono">
                      {new Date(event.created_at).toLocaleTimeString()}
                    </span>
                  </div>

                  <div className="text-xs font-mono text-slate-400 truncate">
                    <span className="text-slate-500">Dedup Key:</span> {event.dedup_key}
                  </div>

                  {event.last_error && (
                    <div className="text-xs text-rose-300 bg-rose-950/40 p-2.5 rounded-lg border border-rose-500/30 font-mono">
                      {event.last_error}
                    </div>
                  )}

                  {['FAILED', 'DEAD_LETTER'].includes(event.status) && (
                    <div className="flex justify-end pt-1">
                      <button
                        onClick={() => retryMutation.mutate(event.id)}
                        disabled={retryMutation.isPending}
                        className="flex items-center gap-1.5 px-3 py-1 text-xs font-semibold text-white bg-slate-800 hover:bg-slate-700 border border-slate-700 rounded-lg transition"
                      >
                        <RefreshCw className="w-3 h-3" />
                        Retry Now
                      </button>
                    </div>
                  )}
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
