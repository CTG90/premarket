// Private Yahoo proxy for Premarket Live (Cloudflare Worker, free plan).
// Public CORS proxies keep dying or going paid; this one is yours.
//
// Setup (about 5 minutes):
// 1. Sign in at dash.cloudflare.com > Workers & Pages > Create > Create Worker.
// 2. Name it yahoo-proxy, Deploy, then Edit code. Replace everything with this file. Deploy.
// 3. Copy the worker URL (https://yahoo-proxy.<you>.workers.dev) and in Premarket Live
//    Settings > Yahoo proxy paste:  https://yahoo-proxy.<you>.workers.dev/?url=
//
// It only forwards to Yahoo Finance hosts and only answers pages on ALLOWED_ORIGINS,
// so nobody else can use it as an open proxy.

const ALLOWED_HOSTS = ['query1.finance.yahoo.com', 'query2.finance.yahoo.com', 'feeds.finance.yahoo.com'];
const ALLOWED_ORIGINS = ['https://ctg90.github.io'];

export default {
  async fetch(request) {
    const origin = request.headers.get('Origin') || '';
    const allow = ALLOWED_ORIGINS.includes(origin) ? origin : ALLOWED_ORIGINS[0];
    const cors = { 'Access-Control-Allow-Origin': allow, 'Vary': 'Origin' };
    if (request.method === 'OPTIONS') return new Response(null, { headers: { ...cors, 'Access-Control-Allow-Methods': 'GET' } });

    const target = new URL(request.url).searchParams.get('url');
    let u;
    try { u = new URL(target); } catch { return new Response('Missing or bad ?url=', { status: 400, headers: cors }); }
    if (u.protocol !== 'https:' || !ALLOWED_HOSTS.includes(u.hostname)) {
      return new Response('Host not allowed', { status: 403, headers: cors });
    }
    const r = await fetch(u.toString(), {
      headers: { 'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15', 'Accept': '*/*' },
      cf: { cacheTtl: 2, cacheEverything: false },
    });
    const h = new Headers(cors);
    h.set('Content-Type', r.headers.get('Content-Type') || 'application/json');
    h.set('Cache-Control', 'no-store');
    return new Response(r.body, { status: r.status, headers: h });
  },
};
