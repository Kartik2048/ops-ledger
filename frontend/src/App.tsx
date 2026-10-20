import React, { useEffect, useState } from 'react';
import { Header } from './components/Header';
import { Dashboard } from './components/Dashboard';
import { WorkItemDetail } from './components/WorkItemDetail';
import { CreateWorkItemModal } from './components/CreateWorkItemModal';
import { OutboxDrawer } from './components/OutboxDrawer';
import { useUser } from './context/UserContext';
import { AlertTriangle, CheckCircle2, Info, Loader2, X } from 'lucide-react';
import { buildApiUrl } from './api/client';

export const App: React.FC = () => {
  const { currentUser, replayMode, lastIdempotencyKey } = useUser();
  const [selectedItemId, setSelectedItemId] = useState<string | null>(null);
  const [isCreateOpen, setIsCreateOpen] = useState<boolean>(false);
  const [isOutboxOpen, setIsOutboxOpen] = useState<boolean>(false);
  const [isBackendConnecting, setIsBackendConnecting] = useState<boolean>(false);
  const [backendReady, setBackendReady] = useState<boolean>(false);
  const [toastMessage, setToastMessage] = useState<{
    type: 'success' | 'info' | 'warning' | 'error';
    title: string;
    description: string;
  } | null>(null);

  // Active-tab heartbeat & cold-start indicator
  useEffect(() => {
    let isMounted = true;
    const coldStartTimer = setTimeout(() => {
      if (!backendReady && isMounted) {
        setIsBackendConnecting(true);
      }
    }, 1500);

    const pingHealth = async () => {
      try {
        const healthUrl = buildApiUrl('/health');
        const res = await fetch(healthUrl);
        if (res.ok && isMounted) {
          setBackendReady(true);
          setIsBackendConnecting(false);
        }
      } catch {
        // Backend still starting up or transient network glitch
      }
    };

    pingHealth();
    // Heartbeat every 5 minutes (300,000 ms) while tab is open to keep Render Web Service & Supabase warm
    const interval = setInterval(pingHealth, 300000);

    return () => {
      isMounted = false;
      clearTimeout(coldStartTimer);
      clearInterval(interval);
    };
  }, [backendReady]);

  const handleCreated = (newItemId: string) => {
    setSelectedItemId(newItemId);
    setToastMessage({
      type: 'success',
      title: 'Work Item Created',
      description: `New operational request created with atomic audit log and outbox event.`,
    });
    setTimeout(() => setToastMessage(null), 5000);
  };

  return (
    <div className="min-h-screen bg-[#090D16] text-slate-100 flex flex-col antialiased selection:bg-brand-500 selection:text-white">
      {/* Top Navigation & Evaluator Bar */}
      <Header
        onOpenCreate={() => setIsCreateOpen(true)}
        onOpenOutbox={() => setIsOutboxOpen(true)}
      />

      {/* Cold-Start Connection Alert (Dismisses automatically once backend responds) */}
      {isBackendConnecting && !backendReady && (
        <div className="bg-sky-500/10 border-b border-sky-500/30 px-4 py-2 flex items-center justify-between text-xs text-sky-300 animate-pulse">
          <div className="flex items-center gap-2 max-w-7xl mx-auto w-full">
            <Loader2 className="w-4 h-4 text-sky-400 animate-spin flex-shrink-0" />
            <span className="font-semibold">Connecting to cloud backend instance...</span>
            <span className="text-sky-200/70 hidden sm:inline">
              (Free-tier instances may require a brief cold start wakeup; establishing database pool connection)
            </span>
          </div>
        </div>
      )}

      {/* Global Banner for Active Persona / Idempotency Mode */}
      {replayMode && (
        <div className="bg-amber-500/10 border-b border-amber-500/30 px-4 py-2 flex items-center justify-between text-xs text-amber-300">
          <div className="flex items-center gap-2 max-w-7xl mx-auto w-full">
            <AlertTriangle className="w-4 h-4 text-amber-400 flex-shrink-0 animate-bounce" />
            <span className="font-semibold">Idempotency Demo Active:</span>
            <span className="text-amber-200/80">
              Your next mutation will intentionally reuse key{' '}
              <code className="bg-amber-950/60 px-1.5 py-0.5 rounded font-mono text-[11px] border border-amber-600/40">
                {lastIdempotencyKey || 'generated-uuid'}
              </code>{' '}
              to demonstrate deterministic replay and deduplication.
            </span>
          </div>
        </div>
      )}

      {/* Main Content Area */}
      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-6">
        <Dashboard
          onSelectItem={(itemId) => setSelectedItemId(itemId)}
          selectedItemId={selectedItemId}
        />
      </main>

      {/* Work Item Detail Drawer / Modal */}
      {selectedItemId && (
        <div className="fixed inset-0 z-50 overflow-hidden bg-slate-950/70 backdrop-blur-sm flex justify-end animate-fade-in">
          <div className="relative w-full max-w-3xl h-full shadow-2xl animate-slide-left">
            <WorkItemDetail
              itemId={selectedItemId}
              onClose={() => setSelectedItemId(null)}
            />
          </div>
        </div>
      )}

      {/* Create Work Item Modal */}
      <CreateWorkItemModal
        isOpen={isCreateOpen}
        onClose={() => setIsCreateOpen(false)}
        onCreated={handleCreated}
      />

      {/* Outbox Drawer */}
      <OutboxDrawer
        isOpen={isOutboxOpen}
        onClose={() => setIsOutboxOpen(false)}
      />

      {/* Toast Alert */}
      {toastMessage && (
        <div className="fixed bottom-6 right-6 z-50 max-w-md bg-surface-dark border border-slate-700 rounded-xl p-4 shadow-2xl flex items-start gap-3 animate-fade-in">
          {toastMessage.type === 'success' && <CheckCircle2 className="w-5 h-5 text-emerald-400 flex-shrink-0 mt-0.5" />}
          {toastMessage.type === 'warning' && <AlertTriangle className="w-5 h-5 text-amber-400 flex-shrink-0 mt-0.5" />}
          {toastMessage.type === 'info' && <Info className="w-5 h-5 text-indigo-400 flex-shrink-0 mt-0.5" />}
          <div className="flex-1 min-w-0">
            <h4 className="text-xs font-bold text-white">{toastMessage.title}</h4>
            <p className="text-xs text-slate-400 mt-0.5">{toastMessage.description}</p>
          </div>
          <button
            onClick={() => setToastMessage(null)}
            className="text-slate-400 hover:text-white"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

      {/* Footer / System Status Bar */}
      <footer className="border-t border-slate-800/80 bg-slate-950/60 py-3 px-4 text-xs text-slate-500 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-3">
          <span className="flex items-center gap-1.5 font-medium text-slate-400">
            <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></span>
            Operational Console Engine
          </span>
          <span className="text-slate-700">|</span>
          <span>Role: <strong className="text-indigo-400 font-mono">{currentUser?.full_name || 'Loading...'}</strong></span>
          <span className="text-slate-700">|</span>
          <span>OCC: <strong className="text-slate-400">Strict Version Check</strong></span>
        </div>
        <div className="flex items-center gap-4 text-[11px] text-slate-400">
          <span>Backend: <code className="text-indigo-400">/api/v1</code></span>
          <span>Transactional Outbox: <code className="text-emerald-400">Active (5s polling)</code></span>
        </div>
      </footer>
    </div>
  );
};

export default App;
