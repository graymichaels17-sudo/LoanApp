import { createApp } from '../server/createApp';

let cachedApp: any = null;

export default async function handler(req: any, res: any) {
  // Normalize req.url so Express routes match correctly regardless of Vercel routing
  if (req.url) {
    if (!req.url.startsWith('/api') && req.url !== '/') {
      req.url = `/api${req.url}`;
    }
  }

  // If Vercel passed slug in query
  if (req.query?.slug) {
    const slug = Array.isArray(req.query.slug) ? req.query.slug.join('/') : req.query.slug;
    if (!req.url || req.url === '/api' || req.url === '/') {
      req.url = `/api/${slug}`;
    }
  }

  if (!cachedApp) {
    cachedApp = await createApp();
  }
  return cachedApp(req, res);
}
