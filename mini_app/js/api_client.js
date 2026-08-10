// Mini App API client. Augments base `api` (platform_init.js). Global `API`.
(function () {
  function decodeJwt(token) {
    try {
      const payload = token.split('.')[1];
      const json = atob(payload.replace(/-/g, '+').replace(/_/g, '/'));
      return JSON.parse(decodeURIComponent(escape(json)));
    } catch (e) { return {}; }
  }

  // Claims are decoded synchronously; persisting is async (CloudStorage) and
  // deliberately not awaited here — callers never need the write to land first.
  api.setToken = function (token) {
    this.token = token;
    const c = decodeJwt(token);
    this.agencyId = c.agency_id || null;
    this.managerId = c.sub || null;
    StorageAdapter.set('jwt_token', token);
  };
  api.loadToken = async function () {
    const t = this.token || (await StorageAdapter.get('jwt_token'));
    if (t) this.setToken(t);
    return t;
  };

  // Multipart upload. The browser must set Content-Type itself so the
  // multipart boundary is correct, hence a separate path from api.request.
  api.upload = async function (endpoint, formData) {
    const build = () => {
      const headers = {};
      if (this.token) headers['Authorization'] = `Bearer ${this.token}`;
      return fetch(`${API_BASE}/api${endpoint}`, { method: 'POST', headers, body: formData });
    };
    let res = await build();
    if (res.status === 401 && typeof authenticate === 'function') {
      await StorageAdapter.remove('jwt_token');
      this.token = null;
      try { await authenticate(); res = await build(); } catch (e) { /* fall through */ }
    }
    if (!res.ok) {
      // The import reports per-row problems in the body; surface them instead
      // of a bare status code.
      let detail = `API ${res.status}`;
      try { const body = await res.json(); detail = body.detail || body.message || detail; }
      catch (e) { /* keep the status */ }
      throw new Error(detail);
    }
    return res.json();
  };

  // Binary fetch for stored documents. The download endpoint requires the JWT,
  // so a plain <a href> opens a 401 instead of the file -- the header only
  // travels on a fetch. The blob URL it returns can then be opened or saved.
  api.requestBlob = async function (endpoint) {
    const build = () => {
      const headers = {};
      if (this.token) headers['Authorization'] = `Bearer ${this.token}`;
      return fetch(`${API_BASE}/api${endpoint}`, { headers });
    };
    let res = await build();
    if (res.status === 401 && typeof authenticate === 'function') {
      await StorageAdapter.remove('jwt_token');
      this.token = null;
      try { await authenticate(); res = await build(); } catch (e) { /* fall through */ }
    }
    if (!res.ok) throw new Error(`API ${res.status}`);
    return URL.createObjectURL(await res.blob());
  };

  // Raw text (documents return HTML, not JSON).
  api.requestText = async function (endpoint) {
    const build = () => {
      const headers = {};
      if (this.token) headers['Authorization'] = `Bearer ${this.token}`;
      return fetch(`${API_BASE}/api${endpoint}`, { headers });
    };
    let res = await build();
    if (res.status === 401 && typeof authenticate === 'function' && !endpoint.startsWith('/auth/')) {
      await StorageAdapter.remove('jwt_token');
      this.token = null;
      try { await authenticate(); res = await build(); } catch (e) { /* fall through */ }
    }
    if (!res.ok) throw new Error(`API ${res.status}`);
    return res.text();
  };

  const qs = (obj) => {
    const p = Object.entries(obj || {})
      .filter(([, v]) => v !== null && v !== undefined && v !== '')
      .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`);
    return p.length ? '?' + p.join('&') : '';
  };

  window.API = {
    // Signals
    signals: (f) => api.request('/signals' + qs(f)),
    signal: (id) => api.request(`/signals/${id}`),
    signalQueue: (f) => api.request('/signals/queue' + qs(f)),
    generateReply: (id) => api.request(`/signals/${id}/generate-reply`, 'POST'),
    setReplyDraft: (id, body) => api.request(`/signals/${id}/reply-draft`, 'PATCH', body),
    sendReply: (id) => api.request(`/signals/${id}/send-reply`, 'POST'),
    // Triage: the two ways a signal leaves the queue unanswered (дополнение §5.2)
    escalateSignal: (id, reason) => api.request(`/signals/${id}/escalate`, 'POST', { reason }),
    dismissSignal: (id, reason) => api.request(`/signals/${id}/dismiss`, 'POST', { reason }),
    createLead: (id, body) =>
      api.request(`/signals/${id}/create-lead`, 'POST', { ...body, ...(window._utm || {}) }),

    // Leads
    leads: (f) => api.request('/leads' + qs(f)),
    createLeadManual: (body) => api.request('/leads', 'POST', body),
    lead: (id) => api.request(`/leads/${id}`),
    setLeadStatus: (id, body) => api.request(`/leads/${id}/status`, 'PATCH', body),
    matchFeedback: (leadId, propId, f) =>
      api.request(`/leads/${leadId}/matches/${propId}/feedback` + qs(f), 'POST'),
    processAlternative: (id) => api.request(`/leads/${id}/process-alternative`, 'POST'),
    leadDocumentHtml: (id) => api.requestText(`/leads/${id}/document?format=html`),
    createContract: (body) => api.request('/documents/preliminary-contract', 'POST', body),
    createChecklist: (propId) => api.request(`/documents/checklist/${propId}`, 'POST'),
    // `key` already carries the agency prefix the endpoint checks.
    documentBlob: (key) => api.requestBlob(`/documents/${key}`),
    readiness: () => api.request('/health/readiness'),

    // 152-ФЗ: what we hold about a person, and erasing it on their request
    personalData: (id) => api.request(`/leads/${id}/personal-data`),
    erasePersonalData: (id, reason) =>
      api.request(`/leads/${id}/erase-personal-data`, 'POST', { reason }),

    // Deals (Knowledge Moat)
    recordOutcome: (leadId, body) => api.request(`/deals/${leadId}/outcome`, 'POST', body),

    // Properties
    properties: (f) => api.request('/properties' + qs(f)),
    property: (id) => api.request(`/properties/${id}`),
    importProperties: (file, dryRun, geoId) => {
      const fd = new FormData();
      fd.append('file', file);
      fd.append('dry_run', dryRun ? 'true' : 'false');
      if (geoId) fd.append('geo_location_id', geoId);
      return api.upload('/properties/import', fd);
    },
    updateProperty: (id, body) => api.request(`/properties/${id}`, 'PATCH', body),
    propertyReportHtml: (id) => api.requestText(`/properties/${id}/report?format=html`),
    generateListing: (id, body) => api.request(`/properties/${id}/generate-listing`, 'POST', body),

    // Analytics
    overview: () => api.request('/analytics/overview'),
    funnel: () => api.request('/analytics/funnel'),
    managers: () => api.request('/analytics/managers'),
    timeline: () => api.request('/analytics/timeline'),
    sourceRoi: () => api.request('/analytics/source-roi'),
    marketEvent: (body) => api.request('/analytics/market-event', 'POST', body),

    // Partners & referrals
    partners: (f) => api.request('/partners' + qs(f)),
    acceptPartnerGeo: (body) => api.request('/partners/accept', 'POST', body),
    partner: (id) => api.request(`/partners/${id}`),
    createPartner: (body) => api.request('/partners', 'POST', body),
    updatePartner: (id, body) => api.request(`/partners/${id}`, 'PATCH', body),
    deletePartner: (id) => api.request(`/partners/${id}`, 'DELETE'),
    referralsList: (f) => api.request('/referrals' + qs(f)),
    createReferral: (body) => api.request('/referrals', 'POST', body),
    recordReferralDeal: (id, body) => api.request(`/referrals/${id}/deal`, 'POST', body),

    // Geo
    geoList: () => api.request('/geo'),
    createGeo: (body) => api.request('/geo', 'POST', body),

    // Manager tasks (TZ 30 /tasks)
    tasks: (f) => api.request('/tasks' + qs(f)),
    tasksSummary: () => api.request('/tasks/summary'),
    updateTask: (id, body) => api.request(`/tasks/${id}`, 'PATCH', body),

    // Manager onboarding: the invite link is what admits someone to the agency
    invite: () => api.request('/auth/invite'),
    rotateInvite: () => api.request('/auth/invite/rotate', 'POST'),

    // The agency's own record: name, city, and where leads are exported
    appConfig: () => api.request('/auth/config'),
    agency: () => api.request('/auth/agency'),
    updateAgency: (body) => api.request('/auth/agency', 'PATCH', body),

    // Which AI answers, and whether the data leaves Russia (152-ФЗ)
    aiProvider: () => api.request('/auth/ai-provider'),
    setAiProvider: (provider) => api.request('/auth/ai-provider', 'PUT', { provider }),

    // Monitoring sources (TZ 30 /admin/sources)
    sources: (f) => api.request('/sources' + qs(f)),
    createSource: (body) => api.request('/sources', 'POST', body),
    updateSource: (id, body) => api.request(`/sources/${id}`, 'PATCH', body),
    deleteSource: (id) => api.request(`/sources/${id}`, 'DELETE'),
  };
})();
