import express, { Express } from 'express';
import cors from 'cors';
import {
  getSqlite,
  querySql,
  executeSql,
  getDatabaseStats,
  exportSqliteBinary,
  importSqliteBinary,
  resetSqliteDatabase,
  persistDatabase,
} from './sqlite';
import {
  isTursoConfigured,
  getTursoConfig,
  getTursoClient,
  initTursoSchema,
  queryTurso,
  executeTurso,
  getTursoStats,
  syncLocalToTurso,
} from './turso';

export async function createApp(): Promise<Express> {
  const app = express();

  // Initialize SQLite database engine
  try {
    await getSqlite();
    console.log('[SQLite Engine] Initialized and verified successfully');
  } catch (e) {
    console.error('[SQLite Engine] Initialization error:', e);
  }

  // Initialize Turso Cloud database engine if credentials are provided
  if (isTursoConfigured()) {
    try {
      const client = getTursoClient();
      if (client) {
        const res = await initTursoSchema(client);
        console.log(`[Turso Engine] Remote LibSQL database connected and verified (${res.tables} tables)`);
      }
    } catch (err: any) {
      console.warn('[Turso Engine] Remote database initialization warning:', err.message);
    }
  }

  // Unified Database Query & Execute Runners
  async function runQuery(sql: string, params: any[] = []): Promise<any[]> {
    if (isTursoConfigured()) {
      try {
        return await queryTurso(sql, params);
      } catch (err: any) {
        console.warn('[Turso] Query failed, falling back to local SQLite:', err.message);
        return querySql(sql, params);
      }
    }
    return querySql(sql, params);
  }

  async function runExecute(
    sql: string,
    params: any[] = []
  ): Promise<{ changes: number; lastInsertRowid?: number }> {
    if (isTursoConfigured()) {
      try {
        return await executeTurso(sql, params);
      } catch (err: any) {
        console.warn('[Turso] Execute failed, falling back to local SQLite:', err.message);
        return executeSql(sql, params);
      }
    }
    return executeSql(sql, params);
  }

  // Ensure system_app_state table exists on active database (Turso / SQLite)
  try {
    await runExecute(`
      CREATE TABLE IF NOT EXISTS system_app_state (
        key TEXT PRIMARY KEY,
        data TEXT NOT NULL,
        updated_at TEXT NOT NULL
      )
    `);
  } catch (err: any) {
    console.warn('[Server] Note on system_app_state init:', err.message);
  }

  app.use(cors());
  app.use(express.json({ limit: '50mb' }));
  app.use(express.raw({ type: 'application/x-sqlite3', limit: '50mb' }));

  // Ensure req.url has /api prefix if stripped by Vercel or other proxies
  app.use((req, _res, next) => {
    if (req.url && !req.url.startsWith('/api') && req.url !== '/') {
      req.url = `/api${req.url}`;
    }
    next();
  });

  // ==========================================
  // Database System APIs (SQLite & Turso Cloud)
  // ==========================================

  // Health check
  app.get('/api/health', (req, res) => {
    try {
      const tursoConfig = getTursoConfig();
      res.json({
        status: 'ok',
        engine: tursoConfig.configured ? 'Turso Cloud (LibSQL)' : 'SQLite 3 (WebAssembly)',
        mode: tursoConfig.configured ? 'turso' : 'local_sqlite',
        tursoConnected: tursoConfig.configured,
        tursoUrl: tursoConfig.maskedUrl,
        timestamp: new Date().toISOString(),
      });
    } catch (e: any) {
      res.status(500).json({ status: 'error', message: e.message });
    }
  });

  // Turso connection configuration info
  app.get('/api/db/turso-info', (req, res) => {
    const config = getTursoConfig();
    res.json({
      configured: config.configured,
      maskedUrl: config.maskedUrl,
      mode: config.configured ? 'turso' : 'local_sqlite',
      activeUrl: config.url || null,
      vercelSetupNeeded: !config.configured,
    });
  });

  // Central Synchronized State (Multi-User Cloud Sync)
  app.get('/api/state', async (req, res) => {
    try {
      const rows = await runQuery("SELECT data, updated_at FROM system_app_state WHERE key = 'main_state'");
      if (rows && rows.length > 0) {
        const parsed = JSON.parse(rows[0].data);
        res.json({
          success: true,
          data: parsed,
          updatedAt: rows[0].updated_at,
          source: isTursoConfigured() ? 'turso_cloud' : 'local_sqlite',
          tursoConnected: isTursoConfigured(),
        });
        return;
      }
      res.json({ success: false, message: 'No stored cloud state found yet' });
    } catch (err: any) {
      res.status(500).json({ success: false, error: err.message });
    }
  });

  app.post('/api/state', async (req, res) => {
    try {
      const { state } = req.body;
      if (!state) {
        res.status(400).json({ success: false, error: 'State object is required' });
        return;
      }
      const jsonStr = JSON.stringify(state);
      const now = new Date().toISOString();
      await runExecute(
        `INSERT OR REPLACE INTO system_app_state (key, data, updated_at) VALUES ('main_state', ?, ?)`,
        [jsonStr, now]
      );
      persistDatabase();
      res.json({
        success: true,
        updatedAt: now,
        source: isTursoConfigured() ? 'turso_cloud' : 'local_sqlite',
        tursoConnected: isTursoConfigured(),
      });
    } catch (err: any) {
      res.status(500).json({ success: false, error: err.message });
    }
  });

  // Detailed Stats & Table Schemas
  app.get('/api/db/stats', async (req, res) => {
    try {
      if (isTursoConfigured()) {
        try {
          const stats = await getTursoStats();
          const tursoConfig = getTursoConfig();
          res.json({
            success: true,
            ...stats,
            tursoConnected: true,
            tursoUrl: tursoConfig.maskedUrl,
          });
          return;
        } catch (err: any) {
          console.warn('[Turso Stats] Remote fetch failed, returning local stats:', err.message);
        }
      }
      const stats = getDatabaseStats();
      res.json({
        success: true,
        ...stats,
        mode: 'local_sqlite',
        tursoConnected: false,
      });
    } catch (e: any) {
      res.status(500).json({ success: false, error: e.message });
    }
  });

  // Custom SQL Query Runner (Live SQL Console supporting Turso & SQLite)
  app.post('/api/db/query', async (req, res) => {
    const { sql, params } = req.body;
    if (!sql || typeof sql !== 'string') {
      res.status(400).json({ success: false, error: 'SQL query string is required' });
      return;
    }

    const startTime = performance.now();
    try {
      const trimmed = sql.trim();
      const isSelect = /^(SELECT|PRAGMA|EXPLAIN)/i.test(trimmed);

      if (isSelect) {
        const rows = await runQuery(trimmed, params || []);
        const columns = rows.length > 0 ? Object.keys(rows[0]) : [];
        const durationMs = Math.round((performance.now() - startTime) * 100) / 100;
        res.json({
          success: true,
          columns,
          rows,
          rowCount: rows.length,
          durationMs,
          engine: isTursoConfigured() ? 'Turso Cloud (LibSQL)' : 'SQLite 3 (WebAssembly)',
        });
      } else {
        const result = await runExecute(trimmed, params || []);
        const durationMs = Math.round((performance.now() - startTime) * 100) / 100;
        res.json({
          success: true,
          changes: result.changes,
          lastInsertRowid: result.lastInsertRowid,
          durationMs,
          engine: isTursoConfigured() ? 'Turso Cloud (LibSQL)' : 'SQLite 3 (WebAssembly)',
        });
      }
    } catch (e: any) {
      const durationMs = Math.round((performance.now() - startTime) * 100) / 100;
      res.status(400).json({
        success: false,
        error: e.message,
        durationMs,
      });
    }
  });

  // Synchronize local database schema and data to Turso Cloud
  app.post('/api/db/sync-to-turso', async (req, res) => {
    if (!isTursoConfigured()) {
      res.status(400).json({
        success: false,
        error: 'Turso is not configured. Please add TURSO_DATABASE_URL and TURSO_AUTH_TOKEN in Settings.',
      });
      return;
    }

    try {
      const localTables = querySql(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
      ).map((t: any) => t.name);

      const result = await syncLocalToTurso(localTables, (tableName) => {
        return querySql(`SELECT * FROM "${tableName}"`);
      });

      res.json({
        success: true,
        message: `Successfully synchronized ${result.totalRowsSynced} records across ${result.syncedTables.length} tables to Turso Cloud!`,
        ...result,
      });
    } catch (err: any) {
      res.status(500).json({ success: false, error: err.message });
    }
  });

  // Export SQLite database binary file (.sqlite)
  app.get('/api/db/export', (req, res) => {
    try {
      const binary = exportSqliteBinary();
      const buffer = Buffer.from(binary);
      res.setHeader('Content-Type', 'application/x-sqlite3');
      res.setHeader('Content-Disposition', 'attachment; filename="microfinance.sqlite"');
      res.setHeader('Content-Length', buffer.byteLength);
      res.send(buffer);
    } catch (e: any) {
      res.status(500).json({ error: e.message });
    }
  });

  // Import SQLite database binary file (.sqlite)
  app.post('/api/db/import', (req, res) => {
    try {
      if (!req.body || !Buffer.isBuffer(req.body) || req.body.length === 0) {
        res.status(400).json({ success: false, error: 'Valid SQLite binary file is required' });
        return;
      }
      importSqliteBinary(req.body);
      res.json({ success: true, message: 'SQLite database restored successfully from uploaded file.' });
    } catch (e: any) {
      res.status(500).json({ success: false, error: e.message });
    }
  });

  // Reset database back to default schema and seed data
  app.post('/api/db/reset', async (req, res) => {
    try {
      await resetSqliteDatabase();
      res.json({ success: true, message: 'SQLite database reset to initial schema and seeds.' });
    } catch (e: any) {
      res.status(500).json({ success: false, error: e.message });
    }
  });

  // ==========================================
  // Operational REST APIs powered by SQLite / Turso
  // ==========================================

  // Clients
  app.get('/api/clients', async (req, res) => {
    try {
      const clients = await runQuery('SELECT * FROM clients ORDER BY id DESC');
      res.json(clients);
    } catch (e: any) {
      res.status(500).json({ error: e.message });
    }
  });

  app.post('/api/clients', async (req, res) => {
    const { firstName, lastName, nationalId, gender, location, phone, address, occupation, averageIncome, guarantor, guarantorPhone, notes } = req.body;
    try {
      const last = (await runQuery('SELECT MAX(id) as maxId FROM clients'))[0]?.maxId || 0;
      const nextId = Number(last) + 1;
      const clientNo = `CL-${String(nextId).padStart(5, '0')}`;
      
      await runExecute(
        `INSERT INTO clients (client_no, first_name, last_name, national_id, gender, location, phone, address, occupation, average_income, guarantor, guarantor_phone, status, notes)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Active', ?)`,
        [clientNo, firstName, lastName, nationalId || null, gender || 'Male', location || 'Harare Central', phone || '', address || '', occupation || '', averageIncome || 0, guarantor || '', guarantorPhone || '', notes || '']
      );

      const created = (await runQuery('SELECT * FROM clients WHERE client_no = ?', [clientNo]))[0];
      res.status(201).json(created);
    } catch (e: any) {
      res.status(500).json({ error: e.message });
    }
  });

  // Loans
  app.get('/api/loans', async (req, res) => {
    try {
      const loans = await runQuery(`
        SELECT l.*, c.first_name, c.last_name, c.client_no, c.phone, p.name as product_name
        FROM loans l
        JOIN clients c ON l.client_id = c.id
        LEFT JOIN loan_products p ON l.product_id = p.id
        ORDER BY l.id DESC
      `);
      res.json(loans);
    } catch (e: any) {
      res.status(500).json({ error: e.message });
    }
  });

  // Loan Schedules
  app.get('/api/loans/:id/schedules', async (req, res) => {
    try {
      const schedules = await runQuery(
        'SELECT * FROM repayment_schedule WHERE loan_id = ? ORDER BY installment_no ASC',
        [req.params.id]
      );
      res.json(schedules);
    } catch (e: any) {
      res.status(500).json({ error: e.message });
    }
  });

  // Repayments
  app.get('/api/repayments', async (req, res) => {
    try {
      const repayments = await runQuery(`
        SELECT r.*, l.loan_no, c.first_name || ' ' || c.last_name as client_name
        FROM repayments r
        JOIN loans l ON r.loan_id = l.id
        JOIN clients c ON l.client_id = c.id
        ORDER BY r.id DESC
      `);
      res.json(repayments);
    } catch (e: any) {
      res.status(500).json({ error: e.message });
    }
  });

  // Chart of Accounts
  app.get('/api/accounting/accounts', async (req, res) => {
    try {
      const accounts = await runQuery('SELECT * FROM accounts ORDER BY code ASC');
      res.json(accounts);
    } catch (e: any) {
      res.status(500).json({ error: e.message });
    }
  });

  // General Journal
  app.get('/api/accounting/journal', async (req, res) => {
    try {
      const entries = await runQuery('SELECT * FROM journal_entries ORDER BY id DESC LIMIT 100');
      const lines = await runQuery('SELECT jl.*, a.code as account_code, a.name as account_name FROM journal_lines jl JOIN accounts a ON jl.account_id = a.id');
      
      const combined = entries.map((entry: any) => ({
        ...entry,
        lines: lines.filter((l: any) => l.journal_entry_id === entry.id),
      }));

      res.json(combined);
    } catch (e: any) {
      res.status(500).json({ error: e.message });
    }
  });

  // Employees
  app.get('/api/payroll/employees', async (req, res) => {
    try {
      const employees = await runQuery('SELECT * FROM employees ORDER BY id ASC');
      res.json(employees);
    } catch (e: any) {
      res.status(500).json({ error: e.message });
    }
  });

  // Settings
  app.get('/api/settings', async (req, res) => {
    try {
      const rows = await runQuery('SELECT key, value FROM company_details');
      const obj: any = {};
      rows.forEach((r: any) => {
        obj[r.key] = r.value;
      });
      res.json(obj);
    } catch (e: any) {
      res.status(500).json({ error: e.message });
    }
  });

  return app;
}
