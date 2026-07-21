// Mini App API client. Augments base `api` (platform_init.js). Global `API`.
(function () {
  function decodeJwt(token) {
    try {
      const payload = token.split('.')[1];
      const json = atob(payload.replace(/-/g, '+').replace(/_/g, '/'));
      return JSON.parse(decodeURIComponent(escape(json)));
    } catch (e) { return {}; }
  }

  api.setToken = function (token) {
    this.token = token;
    try { localStorage.setItem('jwt_token', token); } catch (e) { /* ignore */ }
    const c = decodeJwt(token);
    this.agencyId = c.agency_id || null;
    this.managerId = c.sub || null;
  };
  api.loadToken = function () {
    const t = this.token || (function () {
      try { return localStorage.getItem('jwt_token'); } catch (e) { return null; }
    })();
    if (t) this.setToken(t);
    return t;
  };

  // Raw text (documents return HTML, not JSON).
  api.requestText = async function (endpoint) {
    const headers = {};
    if (this.token) headers['Authorization'] = `Bearer ${this.token}`;
    const res = await fetch(`${API_BASE}/api${endpoint}`, { headers });
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
    signals: (f) => api.request('/signals' + qs(Object.assign({ agency_id: api.agencyId }, f))),
    signalQueue: (f) => api.request('/signals/queue' + qs(Object.assign({ agency_id: api.agencyId }, f))),
    generateReply: (id) => api.request(`/signals/${id}/generate-reply`, 'POST'),
    setReplyDraft: (id, body) => api.request(`/signals/${id}/reply-draft`, 'PATCH', body),
    sendReply: (id) => api.request(`/signals/${id}/send-reply` + qs({ manager_id: api.managerId }), 'POST'),
    createLead: (id, body) => api.request(`/signals/${id}/create-lead`, 'POST', body),

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
    createPartner: (body) => api.request('/partners', 'POST', body),
    createReferral: (body) => api.request('/referrals', 'POST', body),

    // Geo
    geoList: () => api.request('/geo'),
    createGeo: (body) => api.request('/geo', 'POST', body),
  };
})();
