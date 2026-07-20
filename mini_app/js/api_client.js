// Mini App API client helpers. TZ section 30.
// Augments the base `api` (platform_init.js) with token handling (decode the JWT
// to learn agency_id/manager_id) and typed resource calls. Global: `API`.

(function () {
  function decodeJwt(token) {
    try {
      const payload = token.split('.')[1];
      const json = atob(payload.replace(/-/g, '+').replace(/_/g, '/'));
      return JSON.parse(decodeURIComponent(escape(json)));
    } catch (e) {
      return {};
    }
  }

  api.setToken = function (token) {
    this.token = token;
    try { localStorage.setItem('jwt_token', token); } catch (e) { /* ignore */ }
    const claims = decodeJwt(token);
    this.agencyId = claims.agency_id || null;
    this.managerId = claims.sub || null;
  };

  api.loadToken = function () {
    const t = this.token || (function () {
      try { return localStorage.getItem('jwt_token'); } catch (e) { return null; }
    })();
    if (t) this.setToken(t);
    return t;
  };

  const qs = (obj) => {
    const p = Object.entries(obj || {})
      .filter(([, v]) => v !== null && v !== undefined && v !== '')
      .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`);
    return p.length ? '?' + p.join('&') : '';
  };

  window.API = {
    // Signals (agency-scoped query params).
    signals: (f) => api.request('/signals' + qs(Object.assign({ agency_id: api.agencyId }, f))),
    signalQueue: (f) => api.request('/signals/queue' + qs(Object.assign({ agency_id: api.agencyId }, f))),
    setReplyDraft: (id, body) => api.request(`/signals/${id}/reply-draft`, 'PATCH', body),
    sendReply: (id) => api.request(`/signals/${id}/send-reply` + qs({ manager_id: api.managerId }), 'POST'),
    createLead: (id, body) => api.request(`/signals/${id}/create-lead`, 'POST', body),

    // Leads.
    leads: (f) => api.request('/leads' + qs(f)),
    lead: (id) => api.request(`/leads/${id}`),
    setLeadStatus: (id, body) => api.request(`/leads/${id}/status`, 'PATCH', body),
    matchFeedback: (leadId, propId, body) =>
      api.request(`/leads/${leadId}/matches/${propId}`, 'PATCH', body),

    // Properties.
    properties: (f) => api.request('/properties' + qs(f)),
    updateProperty: (id, body) => api.request(`/properties/${id}`, 'PATCH', body),

    // Analytics.
    overview: () => api.request('/analytics/overview'),
    funnel: () => api.request('/analytics/funnel'),
    managers: () => api.request('/analytics/managers'),
    sourceRoi: () => api.request('/analytics/source-roi'),
  };
})();
