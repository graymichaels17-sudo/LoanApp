import { createClient, Client } from '@libsql/client';
import fs from 'fs';
import path from 'path';

let clientInstance: Client | null = null;

export function isTursoConfigured(): boolean {
  return Boolean(process.env.TURSO_DATABASE_URL && process.env.TURSO_DATABASE_URL.trim() !== '');
}

export function getTursoConfig(): {
  configured: boolean;
  url?: string;
  maskedUrl?: string;
} {
  const url = process.env.TURSO_DATABASE_URL?.trim();
  if (!url) {
    return { configured: false };
  }

  // Mask sensitive parts of the URL if needed
  let maskedUrl = url;
  try {
    const parsed = new URL(url.replace('libsql://', 'https://'));
    maskedUrl = `libsql://${parsed.hostname}`;
  } catch {
    maskedUrl = url.substring(0, 15) + '...';
  }

  return {
    configured: true,
    url,
    maskedUrl,
  };
}

export function getTursoClient(): Client | null {
  if (!isTursoConfigured()) {
    return null;
  }

  if (!clientInstance) {
    const url = process.env.TURSO_DATABASE_URL!.trim();
    const authToken = process.env.TURSO_AUTH_TOKEN?.trim() || undefined;

    clientInstance = createClient({
      url,
      authToken,
    });
    console.log(`[Turso] Connected to remote LibSQL database: ${url}`);
  }

  return clientInstance;
}

/**
 * Initialize remote Turso database schema if tables do not exist yet.
 */
export async function initTursoSchema(client: Client): Promise<{ initialized: boolean; tables: number }> {
  try {
    const res = await client.execute(
      "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name NOT LIKE '_litestream_%'"
    );

    if (res.rows.length > 0) {
      console.log(`[Turso] Remote database already initialized with ${res.rows.length} tables.`);
      return { initialized: true, tables: res.rows.length };
    }

    console.log('[Turso] Database is empty. Applying initial microfinance schema...');
    const schemaPath = path.join(process.cwd(), 'app', 'schema.sql');
    if (!fs.existsSync(schemaPath)) {
      throw new Error(`Schema file not found at ${schemaPath}`);
    }

    const schemaSql = fs.readFileSync(schemaPath, 'utf8');
    
    // Split SQL into individual executable statements
    const statements = schemaSql
      .split(';')
      .map((s) => s.trim())
      .filter((s) => s.length > 0 && !s.startsWith('--'));

    for (const stmt of statements) {
      try {
        await client.execute(stmt);
      } catch (err: any) {
        // Ignore "already exists" errors
        if (!err.message?.includes('already exists')) {
          console.warn('[Turso] Schema statement warning:', err.message);
        }
      }
    }

    const verify = await client.execute(
      "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    );
    console.log(`[Turso] Schema applied successfully. Created ${verify.rows.length} tables.`);
    return { initialized: true, tables: verify.rows.length };
  } catch (err: any) {
    console.error('[Turso] Error initializing schema:', err);
    throw err;
  }
}

/**
 * Run a SELECT query against Turso
 */
export async function queryTurso(sql: string, params: any[] = []): Promise<any[]> {
  const client = getTursoClient();
  if (!client) throw new Error('Turso client is not configured');

  const result = await client.execute({ sql, args: params });
  return result.rows.map((row) => {
    const obj: any = {};
    result.columns.forEach((col, idx) => {
      obj[col] = (row as any)[idx] !== undefined ? (row as any)[idx] : (row as any)[col];
    });
    return obj;
  });
}

/**
 * Run an INSERT/UPDATE/DELETE query against Turso
 */
export async function executeTurso(
  sql: string,
  params: any[] = []
): Promise<{ changes: number; lastInsertRowid?: number }> {
  const client = getTursoClient();
  if (!client) throw new Error('Turso client is not configured');

  const result = await client.execute({ sql, args: params });
  return {
    changes: result.rowsAffected,
    lastInsertRowid: result.lastInsertRowid !== undefined ? Number(result.lastInsertRowid) : undefined,
  };
}

/**
 * Get stats from Turso database
 */
export async function getTursoStats() {
  const client = getTursoClient();
  if (!client) throw new Error('Turso client is not configured');

  const tablesRes = await client.execute(
    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
  );

  const tableDetails: any[] = [];
  let totalRows = 0;

  for (const row of tablesRes.rows) {
    const tableName = String((row as any).name || (row as any)[0]);
    try {
      const countRes = await client.execute(`SELECT COUNT(*) as c FROM "${tableName}"`);
      const rowCount = Number((countRes.rows[0] as any)?.c ?? 0);
      totalRows += rowCount;
      tableDetails.push({
        name: tableName,
        rowCount,
      });
    } catch {
      tableDetails.push({ name: tableName, rowCount: 0 });
    }
  }

  return {
    engine: 'Turso Cloud (LibSQL)',
    mode: 'turso',
    tablesCount: tablesRes.rows.length,
    totalRows,
    tableDetails,
    connected: true,
  };
}

/**
 * Synchronize local SQLite data into remote Turso database
 */
export async function syncLocalToTurso(
  localTables: string[],
  getLocalTableRows: (tableName: string) => any[]
): Promise<{ success: boolean; syncedTables: string[]; totalRowsSynced: number }> {
  const client = getTursoClient();
  if (!client) throw new Error('Turso client is not configured');

  // Make sure schema exists
  await initTursoSchema(client);

  let totalRowsSynced = 0;
  const syncedTables: string[] = [];

  for (const tableName of localTables) {
    const rows = getLocalTableRows(tableName);
    if (!rows || rows.length === 0) continue;

    for (const row of rows) {
      const keys = Object.keys(row);
      const cols = keys.map((k) => `"${k}"`).join(', ');
      const placeholders = keys.map(() => '?').join(', ');
      const vals = keys.map((k) => row[k]);

      try {
        await client.execute({
          sql: `INSERT OR REPLACE INTO "${tableName}" (${cols}) VALUES (${placeholders})`,
          args: vals,
        });
        totalRowsSynced++;
      } catch (err: any) {
        console.warn(`[Turso Sync] Failed inserting row into ${tableName}:`, err.message);
      }
    }
    syncedTables.push(tableName);
  }

  return { success: true, syncedTables, totalRowsSynced };
}

