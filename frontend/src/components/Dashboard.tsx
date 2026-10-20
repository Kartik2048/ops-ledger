import React, { useState, useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  AlertCircle,
  AlertOctagon,
  AlertTriangle,
  ChevronLeft,
  ChevronRight,
  Clock,
  Layers,
  Lock,
  RotateCcw,
  Search,
  Shield,
  ShieldAlert,
  UserCheck,
  UserPlus,
  Wallet,
} from 'lucide-react';
import { api } from '../api/client';
import { useUser } from '../context/UserContext';
import {
  DashboardStatsResponse,
  WorkItemCategory,
  WorkItemResponse,
} from '../types/contracts';

interface DashboardProps {
  onSelectItem: (itemId: string) => void;
  selectedItemId: string | null;
}

export const Dashboard: React.FC<DashboardProps> = ({ onSelectItem, selectedItemId }) => {
  const { currentUser, teams, users } = useUser();

  // Filters State
  const [searchTerm, setSearchTerm] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [selectedTeam, setSelectedTeam] = useState<string>('');
  const [selectedStatus, setSelectedStatus] = useState<string>('');
  const [selectedPriority, setSelectedPriority] = useState<string>('');
  const [selectedCategory, setSelectedCategory] = useState<string>('');
  const [selectedAssignee, setSelectedAssignee] = useState<string>('');
  const [needsAttention, setNeedsAttention] = useState<boolean>(false);
  const [page, setPage] = useState(0);
  const limit = 15;

  // Debounce search input
  useEffect(() => {
    const handler = setTimeout(() => {
      setDebouncedSearch(searchTerm);
      setPage(0);
    }, 300);
    return () => clearTimeout(handler);
  }, [searchTerm]);

  // Query: Dashboard KPI Stats
  const { data: stats } = useQuery<DashboardStatsResponse>({
    queryKey: ['dashboardStats'],
    queryFn: () => api.getDashboardStats(currentUser?.id),
    refetchInterval: 8000,
  });

  // Query: Paginated Work Items
  const { data: workItemsData, isLoading } = useQuery({
    queryKey: [
      'workItems',
      selectedTeam,
      selectedStatus,
      selectedPriority,
      selectedCategory,
      selectedAssignee,
      needsAttention,
      debouncedSearch,
      page,
      currentUser?.id,
    ],
    queryFn: () =>
      api.getWorkItems({
        teamId: selectedTeam || undefined,
        status: selectedStatus || undefined,
        priority: selectedPriority || undefined,
        category: selectedCategory || undefined,
        assignee: selectedAssignee || undefined,
        needsAttention: needsAttention || undefined,
        q: debouncedSearch || undefined,
        limit,
        offset: page * limit,
        userId: currentUser?.id,
      }),
  });

  const clearAllFilters = () => {
    setSearchTerm('');
    setDebouncedSearch('');
    setSelectedTeam('');
    setSelectedStatus('');
    setSelectedPriority('');
    setSelectedCategory('');
    setSelectedAssignee('');
    setNeedsAttention(false);
    setPage(0);
  };

  const hasActiveFilters =
    Boolean(searchTerm) ||
    Boolean(selectedTeam) ||
    Boolean(selectedStatus) ||
    Boolean(selectedPriority) ||
    Boolean(selectedCategory) ||
    Boolean(selectedAssignee) ||
    needsAttention;

  // Category Icon Renderer
  const renderCategoryIcon = (category: WorkItemCategory) => {
    switch (category) {
      case 'PRODUCTION_INCIDENT':
        return <ShieldAlert className="w-3.5 h-3.5 text-rose-400" />;
      case 'PAYMENT_INVESTIGATION':
        return <Wallet className="w-3.5 h-3.5 text-amber-400" />;
      case 'OPERATIONAL_APPROVAL':
        return <Lock className="w-3.5 h-3.5 text-indigo-400" />;
      case 'COMPLIANCE_REQUEST':
        return <Shield className="w-3.5 h-3.5 text-cyan-400" />;
      default:
        return <Layers className="w-3.5 h-3.5 text-slate-400" />;
    }
  };

  const total = workItemsData?.total || 0;
  const totalPages = Math.ceil(total / limit) || 1;

  return (
    <div className="space-y-6">
      {/* 5 Interactive KPI Metric Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-3.5">
        {/* 1. Needs Attention */}
        <div
          onClick={() => {
            clearAllFilters();
            setNeedsAttention(true);
          }}
          className={`p-4 rounded-2xl glass-card cursor-pointer transition ${
            needsAttention ? 'ring-2 ring-amber-500 bg-amber-500/10' : ''
          }`}
        >
          <div className="flex items-center justify-between text-xs text-amber-400 font-semibold mb-2">
            <span className="flex items-center gap-1.5">
              <AlertTriangle className="w-4 h-4" />
              Needs Attention
            </span>
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-500/20 font-mono">
              High / Crit
            </span>
          </div>
          <div className="text-2xl font-extrabold text-white">
            {(stats?.critical_count || 0) + (stats?.blocked_count || 0)}
          </div>
          <div className="text-[11px] text-slate-400 mt-1">Urgent or Blocked items</div>
        </div>

        {/* 2. Unassigned Triage */}
        <div
          onClick={() => {
            clearAllFilters();
            setSelectedAssignee('unassigned');
            setSelectedStatus('TRIAGE');
          }}
          className={`p-4 rounded-2xl glass-card cursor-pointer transition ${
            selectedAssignee === 'unassigned' && selectedStatus === 'TRIAGE'
              ? 'ring-2 ring-indigo-500 bg-indigo-500/10'
              : ''
          }`}
        >
          <div className="flex items-center justify-between text-xs text-indigo-400 font-semibold mb-2">
            <span className="flex items-center gap-1.5">
              <UserPlus className="w-4 h-4" />
              Unassigned Queue
            </span>
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-indigo-500/20 font-mono">Triage</span>
          </div>
          <div className="text-2xl font-extrabold text-white">{stats?.triage_count || 0}</div>
          <div className="text-[11px] text-slate-400 mt-1">Awaiting operator claim</div>
        </div>

        {/* 3. Awaiting Approval */}
        <div
          onClick={() => {
            clearAllFilters();
            setSelectedStatus('PENDING_APPROVAL');
          }}
          className={`p-4 rounded-2xl glass-card cursor-pointer transition ${
            selectedStatus === 'PENDING_APPROVAL' ? 'ring-2 ring-brand-500 bg-brand-500/10' : ''
          }`}
        >
          <div className="flex items-center justify-between text-xs text-brand-300 font-semibold mb-2">
            <span className="flex items-center gap-1.5">
              <Lock className="w-4 h-4" />
              Awaiting Approval
            </span>
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-brand-500/20 font-mono">Gate</span>
          </div>
          <div className="text-2xl font-extrabold text-white">
            {stats?.pending_approval_count || 0}
          </div>
          <div className="text-[11px] text-slate-400 mt-1">Requires Approver sign-off</div>
        </div>

        {/* 4. Blocked Work */}
        <div
          onClick={() => {
            clearAllFilters();
            setSelectedStatus('BLOCKED');
          }}
          className={`p-4 rounded-2xl glass-card cursor-pointer transition ${
            selectedStatus === 'BLOCKED' ? 'ring-2 ring-rose-500 bg-rose-500/10' : ''
          }`}
        >
          <div className="flex items-center justify-between text-xs text-rose-400 font-semibold mb-2">
            <span className="flex items-center gap-1.5">
              <AlertOctagon className="w-4 h-4" />
              Blocked Incidents
            </span>
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-rose-500/20 font-mono">Impeded</span>
          </div>
          <div className="text-2xl font-extrabold text-white">{stats?.blocked_count || 0}</div>
          <div className="text-[11px] text-slate-400 mt-1">Pending external unblock</div>
        </div>

        {/* 5. My Assigned Work */}
        <div
          onClick={() => {
            clearAllFilters();
            setSelectedAssignee('me');
          }}
          className={`p-4 rounded-2xl glass-card cursor-pointer transition ${
            selectedAssignee === 'me' ? 'ring-2 ring-emerald-500 bg-emerald-500/10' : ''
          }`}
        >
          <div className="flex items-center justify-between text-xs text-emerald-400 font-semibold mb-2">
            <span className="flex items-center gap-1.5">
              <UserCheck className="w-4 h-4" />
              My Assigned
            </span>
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/20 font-mono">Personal</span>
          </div>
          <div className="text-2xl font-extrabold text-white">
            {workItemsData?.items.filter((it: WorkItemResponse) => it.assignee_id === currentUser?.id).length || 0}
          </div>
          <div className="text-[11px] text-slate-400 mt-1">Under your active review</div>
        </div>
      </div>

      {/* Filter & Search Bar */}
      <div className="p-4 rounded-2xl glass-panel space-y-3">
        <div className="flex flex-col md:flex-row items-stretch md:items-center gap-3">
          {/* Search Input */}
          <div className="relative flex-1">
            <Search className="w-4 h-4 absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400" />
            <input
              type="text"
              placeholder="Search by title, description, or next action (server-side query)..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="w-full pl-10 pr-4 py-2 bg-slate-900/90 border border-slate-700 rounded-xl text-xs text-white placeholder-slate-400 focus:outline-none focus:border-brand-500 transition"
            />
          </div>

          {/* Team Dropdown */}
          <select
            value={selectedTeam}
            onChange={(e) => {
              setSelectedTeam(e.target.value);
              setPage(0);
            }}
            className="px-3 py-2 bg-slate-900/90 border border-slate-700 rounded-xl text-xs text-white focus:outline-none focus:border-brand-500 transition"
          >
            <option value="">All Teams</option>
            {teams.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
              </option>
            ))}
          </select>

          {/* Status Dropdown */}
          <select
            value={selectedStatus}
            onChange={(e) => {
              setSelectedStatus(e.target.value);
              setPage(0);
            }}
            className="px-3 py-2 bg-slate-900/90 border border-slate-700 rounded-xl text-xs text-white focus:outline-none focus:border-brand-500 transition"
          >
            <option value="">All Statuses</option>
            <option value="TRIAGE">TRIAGE</option>
            <option value="IN_PROGRESS">IN_PROGRESS</option>
            <option value="PENDING_APPROVAL">PENDING_APPROVAL</option>
            <option value="BLOCKED">BLOCKED</option>
            <option value="RESOLVED">RESOLVED</option>
            <option value="CANCELLED">CANCELLED</option>
          </select>

          {/* Priority Dropdown */}
          <select
            value={selectedPriority}
            onChange={(e) => {
              setSelectedPriority(e.target.value);
              setPage(0);
            }}
            className="px-3 py-2 bg-slate-900/90 border border-slate-700 rounded-xl text-xs text-white focus:outline-none focus:border-brand-500 transition"
          >
            <option value="">All Priorities</option>
            <option value="CRITICAL">CRITICAL</option>
            <option value="HIGH">HIGH</option>
            <option value="MEDIUM">MEDIUM</option>
            <option value="LOW">LOW</option>
          </select>

          {/* Assignee Filter */}
          <select
            value={selectedAssignee}
            onChange={(e) => {
              setSelectedAssignee(e.target.value);
              setPage(0);
            }}
            className="px-3 py-2 bg-slate-900/90 border border-slate-700 rounded-xl text-xs text-white focus:outline-none focus:border-brand-500 transition"
          >
            <option value="">All Assignees</option>
            <option value="unassigned">Unassigned Only</option>
            <option value="me">Assigned to Me</option>
            {users.map((u) => (
              <option key={u.id} value={u.id}>
                {u.full_name}
              </option>
            ))}
          </select>

          {/* Reset Filters */}
          {hasActiveFilters && (
            <button
              onClick={clearAllFilters}
              className="flex items-center gap-1.5 px-3 py-2 text-xs font-semibold text-rose-400 bg-rose-500/10 hover:bg-rose-500/20 border border-rose-500/30 rounded-xl transition"
            >
              <RotateCcw className="w-3.5 h-3.5" />
              Reset
            </button>
          )}
        </div>
      </div>

      {/* Work Items Table */}
      <div className="rounded-2xl glass-panel border border-slate-800 overflow-hidden shadow-xl">
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="border-b border-slate-800 bg-slate-950/40 text-[11px] font-bold text-slate-400 uppercase tracking-wider">
                <th className="py-3.5 px-4">Priority / Status</th>
                <th className="py-3.5 px-4">Work Item Title & Next Action</th>
                <th className="py-3.5 px-4">Owning Team</th>
                <th className="py-3.5 px-4">Assignee</th>
                <th className="py-3.5 px-4">Version</th>
                <th className="py-3.5 px-4 text-right">Updated</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60 text-xs">
              {isLoading ? (
                <tr>
                  <td colSpan={6} className="py-12 text-center text-slate-400">
                    <Clock className="w-5 h-5 animate-spin mx-auto mb-2 text-brand-400" />
                    Querying operational records...
                  </td>
                </tr>
              ) : workItemsData?.items.length === 0 ? (
                <tr>
                  <td colSpan={6} className="py-12 text-center text-slate-400">
                    <AlertCircle className="w-6 h-6 mx-auto mb-2 text-slate-500" />
                    No work items match the selected filter criteria.
                  </td>
                </tr>
              ) : (
                workItemsData?.items.map((item: WorkItemResponse) => {
                  const isSelected = selectedItemId === item.id;
                  return (
                    <tr
                      key={item.id}
                      onClick={() => onSelectItem(item.id)}
                      className={`cursor-pointer transition hover:bg-slate-800/40 ${
                        isSelected ? 'bg-indigo-950/30 border-l-4 border-indigo-500' : ''
                      }`}
                    >
                      {/* Priority / Status Column */}
                      <td className="py-3.5 px-4 whitespace-nowrap">
                        <div className="flex items-center gap-2">
                          <span
                            className={`px-2 py-0.5 rounded text-[10px] font-bold font-mono ${
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
                          <span className="px-2 py-0.5 rounded bg-slate-800 text-slate-300 font-mono text-[10px] font-semibold border border-slate-700">
                            {item.status}
                          </span>
                        </div>
                        <div className="flex items-center gap-1.5 mt-1.5 text-[11px] text-slate-400">
                          {renderCategoryIcon(item.category)}
                          <span className="truncate max-w-[120px]">{item.category.replace(/_/g, ' ')}</span>
                        </div>
                      </td>

                      {/* Title & Next Action Required Snippet */}
                      <td className="py-3.5 px-4 max-w-md">
                        <div className="font-semibold text-white text-sm truncate hover:text-indigo-300 transition">
                          {item.title}
                        </div>
                        <div className="flex items-center gap-1.5 text-xs text-amber-300/90 font-mono mt-1 bg-amber-500/5 px-2 py-0.5 rounded border border-amber-500/20 truncate">
                          <AlertTriangle className="w-3 h-3 flex-shrink-0 text-amber-400" />
                          <span className="truncate">{item.next_action_required || 'Triage needed'}</span>
                        </div>
                      </td>

                      {/* Team */}
                      <td className="py-3.5 px-4 whitespace-nowrap">
                        <span className="font-medium text-slate-300">{item.team?.name || '—'}</span>
                        {item.requires_approval && (
                          <div className="text-[10px] text-indigo-400 font-mono mt-0.5 flex items-center gap-1">
                            <Lock className="w-3 h-3" /> Approval Gate
                          </div>
                        )}
                      </td>

                      {/* Assignee */}
                      <td className="py-3.5 px-4 whitespace-nowrap">
                        {item.assignee ? (
                          <div className="flex items-center gap-2">
                            <div
                              className="w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-bold text-white shadow-sm"
                              style={{ backgroundColor: item.assignee.avatar_color }}
                            >
                              {item.assignee.full_name.slice(0, 2).toUpperCase()}
                            </div>
                            <span className="font-medium text-slate-200 truncate max-w-[110px]">
                              {item.assignee.full_name}
                            </span>
                          </div>
                        ) : (
                          <span className="text-[11px] text-amber-400/90 font-mono bg-amber-500/10 px-2 py-0.5 rounded border border-amber-500/20">
                            Unassigned
                          </span>
                        )}
                      </td>

                      {/* Version Badge */}
                      <td className="py-3.5 px-4 whitespace-nowrap">
                        <span className="px-2 py-0.5 rounded-full bg-slate-900 border border-slate-700 text-slate-300 font-mono font-bold text-[11px]">
                          v{item.version}
                        </span>
                      </td>

                      {/* Updated Timestamp */}
                      <td className="py-3.5 px-4 whitespace-nowrap text-right font-mono text-[11px] text-slate-400">
                        {new Date(item.updated_at).toLocaleTimeString([], {
                          hour: '2-digit',
                          minute: '2-digit',
                        })}
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination Bar */}
        <div className="p-4 bg-slate-950/60 border-t border-slate-800 flex items-center justify-between text-xs text-slate-400">
          <div>
            Showing <span className="font-semibold text-white">{total > 0 ? page * limit + 1 : 0}</span> to{' '}
            <span className="font-semibold text-white">{Math.min((page + 1) * limit, total)}</span> of{' '}
            <span className="font-semibold text-white">{total}</span> items
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={() => setPage((p) => Math.max(0, p - 1))}
              disabled={page === 0 || isLoading}
              className="p-1.5 rounded-lg border border-slate-700 bg-slate-900 hover:bg-slate-800 text-slate-300 disabled:opacity-40 disabled:cursor-not-allowed transition"
            >
              <ChevronLeft className="w-4 h-4" />
            </button>
            <span className="font-mono text-slate-300 px-2">
              Page {page + 1} of {totalPages}
            </span>
            <button
              onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
              disabled={page >= totalPages - 1 || isLoading}
              className="p-1.5 rounded-lg border border-slate-700 bg-slate-900 hover:bg-slate-800 text-slate-300 disabled:opacity-40 disabled:cursor-not-allowed transition"
            >
              <ChevronRight className="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
