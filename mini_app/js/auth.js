// Mini App auth flow: platform initData -> JWT. TZ section 18.2.

async function initAuth() {
  const platform = PlatformSDK.platform;
  const initData = PlatformSDK.initData;
  try {
    const res = await api.request('/auth/platform', 'POST', {
      platform: platform,
      init_data: initData
    });
    localStorage.setItem('jwt_token', res.token);
    api.token = res.token;
    window.location.href = '/mini-app/manager/signals';
  } catch (e) {
    const el = document.getElementById('error-screen');
    if (el) el.classList.remove('hidden');
    // eslint-disable-next-line no-console
    console.error('Auth failed:', e);
  }
}

document.addEventListener('DOMContentLoaded', initAuth);
