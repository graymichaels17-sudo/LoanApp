import { createApp } from '../server/createApp';

let cachedApp: any = null;

export default async function handler(req: any, res: any) {
  // Normalize req.url so Express routes match correctly regardless of Vercel routing
  if (req.url) {
    if (!req.url.startsWith('/api') && req.url !== '/') {
      req.url = `/api${req.url}`;
    }
  }

  // If path or slug was passed in query parameter via rewrite
  if (req.query?.path) {
    const p = Array.isArray(req.query.path) ? req.query.path.join('/') : req.query.path;
    req.url = `/api/${p.replace(/^\//, '')}`;
  } else if (req.query?.slug) {
    const s = Array.isArray(req.query.slug) ? req.query.slug.join('/') : req.query.slug;
    req.url = `/api/${s.replace(/^\//, '')}`;
  } else if (req.headers && req.headers['x-matched-path'] && typeof req.headers['x-matched-path'] === 'string') {
    const matched = req.headers['x-matched-path'];
    if (matched.startsWith('/api')) {
      req.url = matched;
    }
  }

  if (!cachedApp) {
    cachedApp = await createApp();
  }
  return cachedApp(req, res);
}
