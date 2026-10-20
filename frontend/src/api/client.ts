import {
  ConflictErrorDetail,
  DashboardStatsResponse,
  OutboxBatchResultResponse,
  OutboxEventResponse,
  OutboxQueueSummaryResponse,
  WorkItemApproveRequest,
  WorkItemClaimRequest,
  WorkItemCommentRequest,
  WorkItemCreateRequest,
  WorkItemDetailResponse,
  WorkItemListResponse,
  WorkItemReassignRequest,
  WorkItemResponse,
  WorkItemTransitionRequest,
  WorkItemUpdateRequest,
} from '../types/contracts';

// Custom Typed API Error
export class ApiError extends Error {
  status: number;
  conflictDetail?: ConflictErrorDetail;
  cachedReplay?: boolean;

  constructor(message: string, status: number, conflictDetail?: ConflictErrorDetail, cachedReplay?: boolean) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.conflictDetail = conflictDetail;
    this.cachedReplay = cachedReplay;
  }
}

// Generate RFC-compliant UUID for idempotency keys
export function generateUUID(): string {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) {
    return crypto.randomUUID();
  }
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function (c) {
    const r = (Math.random() * 16) | 0;
    const v = c === 'x' ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

// API Base URL - Configurable via Vite environment variable
export const API_BASE_URL: string = (
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ||
  'http://localhost:8000/api'
).replace(/\/+$/, '');

export function buildApiUrl(path: string): string {
  if (path.startsWith('http://') || path.startsWith('https://')) {
    return path;
  }
  const cleanPath = path.startsWith('/') ? path : `/${path}`;
  if (API_BASE_URL.endsWith('/api') && (cleanPath === '/api' || cleanPath.startsWith('/api/'))) {
    return `${API_BASE_URL}${cleanPath.substring(4)}`;
  }
  return `${API_BASE_URL}${cleanPath}`;
}

interface RequestOptions extends RequestInit {
  userId?: string;
  idempotencyKey?: string;
}

export async function apiRequest<T>(url: string, options: RequestOptions = {}): Promise<T> {
  const headers = new Headers(options.headers || {});

  if (!headers.has('Content-Type') && options.body) {
    headers.set('Content-Type', 'application/json');
  }

  // Attach simulated active user identity
  if (options.userId) {
    headers.set('X-User-Id', options.userId);
  }

  // Attach Idempotency-Key on mutating operations
  const method = (options.method || 'GET').toUpperCase();
  if (['POST', 'PATCH', 'PUT', 'DELETE'].includes(method)) {
    const key = options.idempotencyKey || generateUUID();
    headers.set('Idempotency-Key', key);
  }

  const fullUrl = buildApiUrl(url);
  const response = await fetch(fullUrl, {
    ...options,
    headers,
  });

  const isReplay = response.headers.get('x-cache-lookup') === 'HIT';

  if (!response.ok) {
    let errorJson: any = null;
    try {
      errorJson = await response.json();
    } catch {
      // Non-JSON error
    }

    if (response.status === 409 && errorJson?.detail) {
      const conflictDetail = errorJson.detail as ConflictErrorDetail;
      throw new ApiError(
        conflictDetail.message || 'Concurrency conflict detected.',
        409,
        conflictDetail
      );
    }

    const message =
      errorJson?.detail ||
      errorJson?.message ||
      `Request failed with status ${response.status}: ${response.statusText}`;

    throw new ApiError(message, response.status);
  }

  const data = await response.json();
  if (isReplay && typeof data === 'object' && data !== null) {
    (data as any)._isIdempotentReplay = true;
  }
  return data as T;
}

// =====================================================================
// TYPED DOMAIN API METHODS
// =====================================================================

export const api = {
  // Work Items Queries
  getWorkItems: (params: {
    teamId?: string;
    status?: string;
    priority?: string;
    category?: string;
    assignee?: string;
    needsAttention?: boolean;
    q?: string;
    limit?: number;
    offset?: number;
    userId?: string;
  }): Promise<WorkItemListResponse> => {
    const query = new URLSearchParams();
    if (params.teamId) query.set('team_id', params.teamId);
    if (params.status) query.set('status', params.status);
    if (params.priority) query.set('priority', params.priority);
    if (params.category) query.set('category', params.category);
    if (params.assignee) query.set('assignee', params.assignee);
    if (params.needsAttention) query.set('needs_attention', 'true');
    if (params.q) query.set('q', params.q);
    if (params.limit !== undefined) query.set('limit', params.limit.toString());
    if (params.offset !== undefined) query.set('offset', params.offset.toString());

    return apiRequest<WorkItemListResponse>(`/api/work-items?${query.toString()}`, {
      userId: params.userId,
    });
  },

  getWorkItemDetail: (id: string, userId?: string): Promise<WorkItemDetailResponse> => {
    return apiRequest<WorkItemDetailResponse>(`/api/work-items/${id}`, { userId });
  },

  getDashboardStats: (userId?: string): Promise<DashboardStatsResponse> => {
    return apiRequest<DashboardStatsResponse>('/api/work-items/stats', { userId });
  },

  // Work Items Mutations (OCC Protected)
  createWorkItem: (
    data: WorkItemCreateRequest,
    userId?: string,
    idempotencyKey?: string
  ): Promise<WorkItemResponse> => {
    return apiRequest<WorkItemResponse>('/api/work-items', {
      method: 'POST',
      body: JSON.stringify(data),
      userId,
      idempotencyKey,
    });
  },

  updateWorkItem: (
    id: string,
    data: WorkItemUpdateRequest,
    userId?: string,
    idempotencyKey?: string
  ): Promise<WorkItemResponse> => {
    return apiRequest<WorkItemResponse>(`/api/work-items/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
      userId,
      idempotencyKey,
    });
  },

  claimWorkItem: (
    id: string,
    data: WorkItemClaimRequest,
    userId?: string,
    idempotencyKey?: string
  ): Promise<WorkItemResponse> => {
    return apiRequest<WorkItemResponse>(`/api/work-items/${id}/claim`, {
      method: 'POST',
      body: JSON.stringify(data),
      userId,
      idempotencyKey,
    });
  },

  transitionStatus: (
    id: string,
    data: WorkItemTransitionRequest,
    userId?: string,
    idempotencyKey?: string
  ): Promise<WorkItemResponse> => {
    return apiRequest<WorkItemResponse>(`/api/work-items/${id}/transition`, {
      method: 'POST',
      body: JSON.stringify(data),
      userId,
      idempotencyKey,
    });
  },

  approveWorkItem: (
    id: string,
    data: WorkItemApproveRequest,
    userId?: string,
    idempotencyKey?: string
  ): Promise<WorkItemResponse> => {
    return apiRequest<WorkItemResponse>(`/api/work-items/${id}/approve`, {
      method: 'POST',
      body: JSON.stringify(data),
      userId,
      idempotencyKey,
    });
  },

  reassignWorkItem: (
    id: string,
    data: WorkItemReassignRequest,
    userId?: string,
    idempotencyKey?: string
  ): Promise<WorkItemResponse> => {
    return apiRequest<WorkItemResponse>(`/api/work-items/${id}/reassign`, {
      method: 'POST',
      body: JSON.stringify(data),
      userId,
      idempotencyKey,
    });
  },

  addComment: (
    id: string,
    data: WorkItemCommentRequest,
    userId?: string
  ): Promise<WorkItemDetailResponse> => {
    return apiRequest<WorkItemDetailResponse>(`/api/work-items/${id}/comments`, {
      method: 'POST',
      body: JSON.stringify(data),
      userId,
    });
  },

  // Test Hook: Simulates a background colleague mutation causing 409 Conflict
  simulateColleagueEdit: (id: string, userId?: string): Promise<WorkItemResponse> => {
    return apiRequest<WorkItemResponse>(`/api/work-items/${id}/simulate-concurrent-edit`, {
      method: 'POST',
      userId,
    });
  },

  // Transactional Outbox Management
  getOutboxQueue: (status?: string): Promise<OutboxQueueSummaryResponse> => {
    const q = status ? `?status=${status}` : '';
    return apiRequest<OutboxQueueSummaryResponse>(`/api/outbox${q}`);
  },

  triggerOutboxProcess: (): Promise<OutboxBatchResultResponse> => {
    return apiRequest<OutboxBatchResultResponse>('/api/outbox/process', {
      method: 'POST',
    });
  },

  retryOutboxEvent: (id: string): Promise<OutboxEventResponse> => {
    return apiRequest<OutboxEventResponse>(`/api/outbox/${id}/retry`, {
      method: 'POST',
    });
  },

  simulateOutboxFailure: (workItemId?: string): Promise<OutboxEventResponse> => {
    const q = workItemId ? `?work_item_id=${workItemId}` : '';
    return apiRequest<OutboxEventResponse>(`/api/outbox/simulate-failure${q}`, {
      method: 'POST',
    });
  },

  // Health and Keep-Alive Probe
  checkHealth: (): Promise<{ status: string; database: string; timestamp: string }> => {
    return apiRequest<{ status: string; database: string; timestamp: string }>('/api/health');
  },
};
