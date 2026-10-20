import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  Activity,
  Check,
  ChevronDown,
  Layers,
  Plus,
  Repeat,
  UserCheck,
} from 'lucide-react';
import { api } from '../api/client';
import { useUser } from '../context/UserContext';
import { UserResponse } from '../types/contracts';

interface HeaderProps {
  onOpenCreate: () => void;
  onOpenOutbox: () => void;
}

export const Header: React.FC<HeaderProps> = ({ onOpenCreate, onOpenOutbox }) => {
  const {
    currentUser,
    users,
    setCurrentUser,
    teams,
    replayMode,
    setReplayMode,
  } = useUser();
  const [dropdownOpen, setDropdownOpen] = useState(false);

  // Poll outbox stats for the badge
  const { data: outboxData } = useQuery({
    queryKey: ['outboxQueue'],
    queryFn: () => api.getOutboxQueue(),
    refetchInterval: 5000,
  });

  const pendingOrFailedCount =
    (outboxData?.counts_by_status?.PENDING || 0) +
    (outboxData?.counts_by_status?.FAILED || 0) +
    (outboxData?.counts_by_status?.DEAD_LETTER || 0);

  const getUserRoleBadges = (user: UserResponse) => {
    const roles: string[] = [];
    teams.forEach((t) => {
      const m = t.memberships?.find((mem) => mem.user_id === user.id);
      if (m) {
        roles.push(`${t.name.split(' ')[0]}: ${m.role}`);
      }
    });
    return roles;
  };

  return (
    <header className="sticky top-0 z-40 w-full glass-panel border-b border-slate-800">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
        {/* Brand & System Status */}
        <div className="flex items-center space-x-4">
          <div className="flex items-center space-x-2.5">
            <div className="w-9 h-9 rounded-xl bg-gradient-to-tr from-brand-600 to-indigo-400 flex items-center justify-center text-white shadow-lg shadow-brand-500/25">
              <Layers className="w-5 h-5" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="font-extrabold text-white tracking-tight text-base">
                  NEWTONITE
                </span>
                <span className="text-[10px] px-2 py-0.5 font-bold uppercase rounded-full bg-indigo-500/10 text-indigo-400 border border-indigo-500/30">
                  Operations Console
                </span>
              </div>
              <p className="text-[11px] text-slate-400">Operations Under Pressure Platform</p>
            </div>
          </div>
        </div>

        {/* Evaluator Controls & Persona Switcher */}
        <div className="flex items-center space-x-3">
          {/* Idempotency Demo Toggle Pill */}
          <button
            onClick={() => setReplayMode((prev) => !prev)}
            title="When active, the next mutation will replay the previous Idempotency-Key to prove backend replay suppression."
            className={`hidden sm:flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-semibold border transition ${
              replayMode
                ? 'bg-amber-500/20 text-amber-300 border-amber-500/50 shadow-sm shadow-amber-500/20'
                : 'bg-slate-900/60 text-slate-400 border-slate-800 hover:border-slate-700'
            }`}
          >
            <Repeat className={`w-3.5 h-3.5 ${replayMode ? 'animate-spin' : ''}`} />
            <span>Replay Key Demo</span>
            <span
              className={`w-2 h-2 rounded-full ${
                replayMode ? 'bg-amber-400 animate-ping' : 'bg-slate-600'
              }`}
            />
          </button>

          {/* Outbox Drawer Button */}
          <button
            onClick={onOpenOutbox}
            className="flex items-center gap-2 px-3.5 py-1.5 bg-slate-900/80 hover:bg-slate-800 text-slate-200 border border-slate-700 rounded-xl text-xs font-semibold shadow-sm transition"
          >
            <Activity className="w-3.5 h-3.5 text-brand-400" />
            <span>Outbox Queue</span>
            {pendingOrFailedCount > 0 && (
              <span className="px-1.5 py-0.2 bg-amber-500 text-slate-950 text-[10px] font-bold rounded-full animate-status-pulse">
                {pendingOrFailedCount}
              </span>
            )}
          </button>

          {/* "+ New Work Item" Button */}
          <button
            onClick={onOpenCreate}
            className="flex items-center gap-1.5 px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-xl text-xs font-bold shadow-lg shadow-indigo-600/25 transition"
          >
            <Plus className="w-4 h-4" />
            <span>New Item</span>
          </button>

          {/* Persona Switcher Dropdown */}
          <div className="relative">
            <button
              onClick={() => setDropdownOpen(!dropdownOpen)}
              className="flex items-center gap-2.5 p-1.5 pr-3 bg-slate-900/80 hover:bg-slate-800 border border-slate-700 rounded-xl transition"
            >
              <div
                className="w-7 h-7 rounded-lg flex items-center justify-center text-xs font-bold text-white shadow-sm"
                style={{ backgroundColor: currentUser?.avatar_color || '#6366F1' }}
              >
                {currentUser?.full_name.slice(0, 2).toUpperCase() || 'OP'}
              </div>
              <div className="text-left hidden md:block">
                <div className="text-xs font-bold text-white leading-tight">
                  {currentUser?.full_name}
                </div>
                <div className="text-[10px] text-indigo-400 font-mono leading-tight">
                  {currentUser ? getUserRoleBadges(currentUser)[0] || 'Member' : 'Operator'}
                </div>
              </div>
              <ChevronDown className="w-3.5 h-3.5 text-slate-400" />
            </button>

            {/* Dropdown Menu */}
            {dropdownOpen && (
              <div className="absolute right-0 mt-2 w-80 bg-surface-dark border border-slate-700 rounded-2xl shadow-2xl py-2 z-50 animate-fade-in">
                <div className="px-4 py-2 border-b border-slate-800">
                  <div className="text-xs font-bold text-slate-300 uppercase tracking-wider flex items-center gap-1.5">
                    <UserCheck className="w-3.5 h-3.5 text-brand-400" />
                    Switch Operator Persona
                  </div>
                  <p className="text-[11px] text-slate-400 mt-0.5">
                    Select a seeded user to evaluate role-scoped RBAC permissions.
                  </p>
                </div>

                <div className="max-h-72 overflow-y-auto py-1">
                  {users.map((u) => {
                    const isSelected = currentUser?.id === u.id;
                    const badges = getUserRoleBadges(u);
                    return (
                      <button
                        key={u.id}
                        onClick={() => {
                          setCurrentUser(u);
                          setDropdownOpen(false);
                        }}
                        className={`w-full flex items-center gap-3 px-4 py-2.5 text-left transition ${
                          isSelected
                            ? 'bg-indigo-600/15 border-l-4 border-indigo-500'
                            : 'hover:bg-slate-800/60'
                        }`}
                      >
                        <div
                          className="w-8 h-8 rounded-lg flex-shrink-0 flex items-center justify-center text-xs font-bold text-white"
                          style={{ backgroundColor: u.avatar_color }}
                        >
                          {u.full_name.slice(0, 2).toUpperCase()}
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center justify-between">
                            <span className="text-xs font-semibold text-white truncate">
                              {u.full_name}
                            </span>
                            {isSelected && <Check className="w-3.5 h-3.5 text-indigo-400" />}
                          </div>
                          <div className="flex flex-wrap gap-1 mt-1">
                            {badges.map((b, idx) => (
                              <span
                                key={idx}
                                className="text-[10px] px-1.5 py-0.2 rounded bg-slate-800 text-slate-300 font-mono"
                              >
                                {b}
                              </span>
                            ))}
                          </div>
                        </div>
                      </button>
                    );
                  })}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </header>
  );
};
