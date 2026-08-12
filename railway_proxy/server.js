const express = require('express');
const { createProxyMiddleware } = require('http-proxy-middleware');

const app = express();
const PROXY_SECRET = process.env.PROXY_SECRET || '';
const PORT = Number(process.env.PORT || 3000);

// Health stays public so Railway and operators can probe the service.
app.get('/health', (_req, res) => res.json({ status: 'ok' }));

function authMiddleware(req, res, next) {
  const supplied = req.headers['x-proxy-secret'];
  if (!PROXY_SECRET) {
    console.error('PROXY_SECRET is not set: rejecting all provider requests');
    return res.status(403).json({ error: 'Proxy not configured' });
  }
  if (supplied !== PROXY_SECRET) {
    return res.status(403).json({ error: 'Invalid proxy secret' });
  }
  return next();
}

app.use(authMiddleware);

app.use('/v1', createProxyMiddleware({
  target: 'https://api.openai.com',
  changeOrigin: true,
  on: {
    proxyReq: (proxyReq, req) => {
      const bearer = req.headers.authorization || '';
      const rawKey = req.headers['x-api-key'] || bearer.replace(/^Bearer\s+/i, '');
      proxyReq.setHeader('Authorization', `Bearer ${rawKey}`);
      proxyReq.removeHeader('x-proxy-secret');
      proxyReq.removeHeader('x-api-key');
    },
  },
}));

app.use('/anthropic', createProxyMiddleware({
  target: 'https://api.anthropic.com',
  pathRewrite: { '^/anthropic': '' },
  changeOrigin: true,
  on: {
    proxyReq: (proxyReq, req) => {
      const rawKey = req.headers['x-api-key'] || '';
      proxyReq.setHeader('x-api-key', rawKey);
      proxyReq.removeHeader('x-proxy-secret');
      proxyReq.removeHeader('authorization');
    },
  },
}));

app.listen(PORT, () => {
  console.log(`REIP Railway proxy listening on ${PORT}`);
  if (!PROXY_SECRET) console.warn('WARNING: PROXY_SECRET is not set');
});
