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
 * Robustly split SQL into individual executable statements, stripping line comments
 */
export function splitSqlStatements(sql: string): string[] {
  // Strip single-line comments (-- ...)
  const cleaned = sql.replace(/--.*$/gm, '');
  return cleaned
    .split(';')
    .map((s) => s.trim())
    .filter((s) => s.length > 0);
}

/**
 * Initialize remote Turso database schema if tables do not exist yet.
 */
export async function initTursoSchema(client: Client): Promise<{ initialized: boolean; tables: number }> {
  try {
    const res = await client.execute(
      "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name NOT LIKE '_litestream_%'"
    );

    const existingTables = new Set(res.rows.map((r: any) => String(r.name || r[0] || '')));
    const coreTables = [
      'users',
      'locations',
      'clients',
      'loan_products',
      'loans',
      'repayment_schedule',
      'disbursements',
      'rollovers',
      'repayments',
      'fees',
      'bad_debts',
      'bad_debt_recoveries',
      'expense_categories',
      'expenses',
      'accounts',
      'journal_entries',
      'journal_lines',
      'employees',
      'company_details',
    ];

    const missingCoreTables = coreTables.filter((t) => !existingTables.has(t));

    if (missingCoreTables.length === 0) {
      console.log(`[Turso] Remote database fully initialized with ${existingTables.size} tables.`);
      return { initialized: true, tables: existingTables.size };
    }

    console.log(`[Turso] Remote database is missing tables (${missingCoreTables.join(', ')}). Applying microfinance schema...`);
    const schemaPath = path.join(process.cwd(), 'app', 'schema.sql');
    let statements: string[] = [];

    if (fs.existsSync(schemaPath)) {
      const schemaSql = fs.readFileSync(schemaPath, 'utf8');
      statements = splitSqlStatements(schemaSql);
    }

    // Always ensure system_app_state exists too
    statements.push(`
      CREATE TABLE IF NOT EXISTS system_app_state (
        key TEXT PRIMARY KEY,
        data TEXT NOT NULL,
        updated_at TEXT NOT NULL
      )
    `);

    for (const stmt of statements) {
      try {
        await client.execute(stmt);
      } catch (err: any) {
        // Ignore "already exists" errors
        if (!err.message?.includes('already exists') && !err.message?.includes('duplicate column')) {
          console.warn('[Turso] Schema statement warning:', err.message);
        }
      }
    }

    const verify = await client.execute(
      "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    );
    console.log(`[Turso] Schema applied successfully. Verified ${verify.rows.length} tables in remote database.`);
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

  const tableNames = tablesRes.rows.map((row) => String((row as any).name || (row as any)[0]));
  const countStmts = tableNames.map((tableName) => ({
    sql: `SELECT COUNT(*) as c FROM "${tableName}"`,
    args: [],
  }));

  const tableDetails: any[] = [];
  let totalRows = 0;

  try {
    const batchRes = await client.batch(countStmts, 'read');
    tableNames.forEach((tableName, idx) => {
      const rowCount = Number((batchRes[idx]?.rows?.[0] as any)?.c ?? 0);
      totalRows += rowCount;
      tableDetails.push({
        name: tableName,
        rowCount,
      });
    });
  } catch {
    // Fallback if batch read encounters any error
    for (const tableName of tableNames) {
      try {
        const countRes = await client.execute(`SELECT COUNT(*) as c FROM "${tableName}"`);
        const rowCount = Number((countRes.rows[0] as any)?.c ?? 0);
        totalRows += rowCount;
        tableDetails.push({ name: tableName, rowCount });
      } catch {
        tableDetails.push({ name: tableName, rowCount: 0 });
      }
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

  try {
    await client.execute('PRAGMA foreign_keys = OFF;');
  } catch {
    // ignore if LibSQL manages PRAGMA differently
  }

  // Insert parent tables before dependent child tables
  const dependencyOrder = [
    'users',
    'permissions',
    'locations',
    'company_details',
    'accounts',
    'expense_categories',
    'loan_products',
    'interest_rate_presets',
    'clients',
    'loans',
    'repayment_schedule',
    'disbursements',
    'repayments',
    'fees',
    'rollovers',
    'bad_debts',
    'bad_debt_recoveries',
    'expenses',
    'journal_entries',
    'journal_lines',
    'budgets',
    'budget_line_items',
    'budget_monthly_amounts',
    'payroll_settings',
    'payroll_tax_bands',
    'employees',
    'employee_earnings',
    'employee_deductions',
    'payroll_periods',
    'payslips',
    'payslip_lines',
    'one_off_earnings',
    'one_off_deductions',
    'system_app_state',
  ];

  const sortedTables = [...localTables].sort((a, b) => {
    const idxA = dependencyOrder.indexOf(a);
    const idxB = dependencyOrder.indexOf(b);
    return (idxA === -1 ? 999 : idxA) - (idxB === -1 ? 999 : idxB);
  });

  let totalRowsSynced = 0;
  const syncedTables: string[] = [];

  for (const tableName of sortedTables) {
    const rows = getLocalTableRows(tableName);
    if (!rows || rows.length === 0) continue;

    const BATCH_SIZE = 40;
    for (let i = 0; i < rows.length; i += BATCH_SIZE) {
      const slice = rows.slice(i, i + BATCH_SIZE);
      const stmts = slice.map((row) => {
        const keys = Object.keys(row);
        const cols = keys.map((k) => `"${k}"`).join(', ');
        const placeholders = keys.map(() => '?').join(', ');
        const vals = keys.map((k) => row[k]);
        return {
          sql: `INSERT OR REPLACE INTO "${tableName}" (${cols}) VALUES (${placeholders})`,
          args: vals,
        };
      });

      try {
        await client.batch(stmts, 'write');
        totalRowsSynced += slice.length;
      } catch (batchErr: any) {
        // Fallback row-by-row if any individual row has constraint differences
        for (const stmt of stmts) {
          try {
            await client.execute(stmt);
            totalRowsSynced++;
          } catch (err: any) {
            console.warn(`[Turso Sync] Failed inserting row into ${tableName}:`, err.message);
          }
        }
      }
    }
    syncedTables.push(tableName);
  }

  return { success: true, syncedTables, totalRowsSynced };
}

