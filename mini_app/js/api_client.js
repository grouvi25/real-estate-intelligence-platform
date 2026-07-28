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
    createLead: (id, body) =>
      api.request(`/signals/${id}/create-lead`, 'POST', { ...body, ...(window._utm || {}) }),

    // Leads
    leads: (f) => api.request('/leads' + qs(f)),
    lead: (id) => api.request(`/leads/${id}`),
    setLeadStatus: (id, body) => api.request(`/leads/${id}/status`, 'PATCH', body),
    matchFeedback: (leadId, propId, f) =>
      api.request(`/leads/${leadId}/matches/${propId}/feedback` + qs(f), 'POST'),
    processAlternative: (id) => api.request(`/leads/${id}/process-alternative`, 'POST'),
    leadDocumentHtml: (id) => api.requestText(`/leads/${id}/document?format=html`),

    // Deals (Knowledge Moat)
    recordOutcome: (leadId, body) => api.request(`/deals/${leadId}/outcome`, 'POST', body),

    // Properties
    properties: (f) => api.request('/properties' + qs(f)),
    property: (id) => api.request(`/properties/${id}`),
    updateProperty: (id, body) => api.request(`/properties/${id}`, 'PATCH', body),
    propertyReportHtml: (id) => api.requestText(`/properties/${id}/report?format=html`),
    generateListing: (id, body) => api.request(`/properties/${id}/generate-listing`, 'POST', body),

    // Analytics
    overview: () => api.request('/analytics/overview'),
    funnel: () => api.request('/analytics/funnel'),
    managers: () => api.request('/analytics/managers'),
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

    // Monitoring sources (TZ 30 /admin/sources)
    sources: (f) => api.request('/sources' + qs(f)),
    createSource: (body) => api.request('/sources', 'POST', body),
    updateSource: (id, body) => api.request(`/sources/${id}`, 'PATCH', body),
    deleteSource: (id) => api.request(`/sources/${id}`, 'DELETE'),
  };
})();
