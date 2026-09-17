import initSqlJs, { Database, QueryExecResult } from 'sql.js';
import fs from 'fs';
import path from 'path';

const DATA_DIR = process.env.VERCEL ? path.join('/tmp', 'data') : path.join(process.cwd(), 'data');
const DB_FILE = path.join(DATA_DIR, 'microfinance.sqlite');
const SCHEMA_FILE = path.join(process.cwd(), 'app', 'schema.sql');

let dbInstance: Database | null = null;
let SQL_ENGINE: any = null;

export async function getSqlite(): Promise<Database> {
  if (dbInstance) {
    return dbInstance;
  }

  try {
    if (!fs.existsSync(DATA_DIR)) {
      fs.mkdirSync(DATA_DIR, { recursive: true });
    }
  } catch (err: any) {
    console.warn('[SQLite] Notice on data directory creation (normal in serverless):', err.message);
  }

  const wasmPath = path.join(process.cwd(), 'node_modules', 'sql.js', 'dist');
  SQL_ENGINE = await initSqlJs({
    locateFile: (file: string) => path.join(wasmPath, file),
  });

  if (fs.existsSync(DB_FILE)) {
    try {
      const fileBuffer = fs.readFileSync(DB_FILE);
      dbInstance = new SQL_ENGINE.Database(fileBuffer);
      console.log(`[SQLite] Loaded existing database from ${DB_FILE} (${fileBuffer.byteLength} bytes)`);
      return dbInstance!;
    } catch (err) {
      console.error(`[SQLite] Failed to load existing database, recreating:`, err);
    }
  }

  // Initialize fresh database
  dbInstance = new SQL_ENGINE.Database();
  console.log(`[SQLite] Initialized new SQLite in-memory database, applying schema...`);

  await applySchemaAndSeed(dbInstance!);
  persistDatabase();

  return dbInstance!;
}

export function persistDatabase(): void {
  if (!dbInstance) return;
  try {
    const data = dbInstance.export();
    const buffer = Buffer.from(data);
    fs.writeFileSync(DB_FILE, buffer);
    console.log(`[SQLite] Persisted database to ${DB_FILE} (${buffer.byteLength} bytes)`);
  } catch (err: any) {
    console.warn(`[SQLite] Notice: database file write skipped in serverless environment:`, err.message);
  }
}

export function querySql(sql: string, params: any[] = []): any[] {
  if (!dbInstance) throw new Error('SQLite database not initialized');
  
  try {
    const stmt = dbInstance.prepare(sql);
    if (params && params.length > 0) {
      stmt.bind(params);
    }
    const results: any[] = [];
    while (stmt.step()) {
      results.push(stmt.getAsObject());
    }
    stmt.free();
    return results;
  } catch (e: any) {
    // Fallback using exec if prepare fails for raw queries
    try {
      const res = dbInstance.exec(sql);
      if (!res || res.length === 0) return [];
      const { columns, values } = res[0];
      return values.map((row) => {
        const obj: any = {};
        columns.forEach((col, idx) => {
          obj[col] = row[idx];
        });
        return obj;
      });
    } catch (fallbackErr: any) {
      throw new Error(`SQL Error: ${e.message || fallbackErr.message}`);
    }
  }
}

export function executeSql(sql: string, params: any[] = []): { changes: number; lastInsertRowid?: number } {
  if (!dbInstance) throw new Error('SQLite database not initialized');
  
  if (params && params.length > 0) {
    dbInstance.run(sql, params);
  } else {
    dbInstance.run(sql);
  }

  const rows = querySql('SELECT changes() as ch, last_insert_rowid() as id');
  persistDatabase();
  return {
    changes: rows[0]?.ch ?? 1,
    lastInsertRowid: rows[0]?.id,
  };
}

export function getDatabaseStats() {
  if (!dbInstance) throw new Error('SQLite database not initialized');
  
  const tables = querySql(
    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
  );
  
  let totalRows = 0;
  const tableDetails: any[] = [];

  for (const t of tables) {
    const countRes = querySql(`SELECT COUNT(*) as c FROM "${t.name}"`);
    const count = countRes[0]?.c ?? 0;
    totalRows += count;

    const cols = querySql(`PRAGMA table_info("${t.name}")`);
    tableDetails.push({
      name: t.name,
      rowCount: count,
      columnCount: cols.length,
      columns: cols.map((c: any) => ({ name: c.name, type: c.type, notnull: c.notnull, pk: c.pk })),
    });
  }

  let fileSize = 0;
  if (fs.existsSync(DB_FILE)) {
    fileSize = fs.statSync(DB_FILE).size;
  } else {
    fileSize = dbInstance.export().byteLength;
  }

  return {
    engine: 'SQLite 3 (WebAssembly / sql.js)',
    dbPath: DB_FILE,
    fileSizeBytes: fileSize,
    fileSizeKb: Math.round(fileSize / 1024),
    tablesCount: tables.length,
    totalRows,
    tables: tableDetails,
  };
}

export function exportSqliteBinary(): Uint8Array {
  if (!dbInstance) throw new Error('SQLite database not initialized');
  return dbInstance.export();
}

export function importSqliteBinary(buffer: Buffer): void {
  if (!SQL_ENGINE) throw new Error('SQL engine not initialized');
  dbInstance = new SQL_ENGINE.Database(buffer);
  persistDatabase();
}

export async function resetSqliteDatabase(): Promise<void> {
  if (!SQL_ENGINE) {
    await getSqlite();
  }
  dbInstance = new SQL_ENGINE.Database();
  await applySchemaAndSeed(dbInstance!);
  persistDatabase();
}

async function applySchemaAndSeed(db: Database) {
  // Read schema.sql if exists or use embedded comprehensive schema
  if (fs.existsSync(SCHEMA_FILE)) {
    const rawSchema = fs.readFileSync(SCHEMA_FILE, 'utf-8');
    db.run(rawSchema);
  } else {
    // Embedded standard schema
    db.run(`
      PRAGMA foreign_keys = ON;
      CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        salt TEXT NOT NULL,
        full_name TEXT NOT NULL,
        role TEXT NOT NULL,
        active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        last_login TEXT
      );
      CREATE TABLE IF NOT EXISTS locations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        active INTEGER NOT NULL DEFAULT 1
      );
      CREATE TABLE IF NOT EXISTS clients (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        client_no TEXT UNIQUE NOT NULL,
        first_name TEXT NOT NULL,
        last_name TEXT NOT NULL,
        national_id TEXT UNIQUE,
        gender TEXT,
        location TEXT,
        phone TEXT,
        address TEXT,
        occupation TEXT,
        average_income INTEGER,
        guarantor TEXT,
        guarantor_phone TEXT,
        date_registered TEXT NOT NULL DEFAULT (date('now')),
        status TEXT NOT NULL DEFAULT 'Active',
        notes TEXT,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
      );
      CREATE TABLE IF NOT EXISTS loan_products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        interest_method TEXT NOT NULL DEFAULT 'flat',
        interest_rate REAL NOT NULL,
        rate_period TEXT NOT NULL DEFAULT 'month',
        admin_fee_pct REAL NOT NULL DEFAULT 0,
        penalty_pct REAL NOT NULL DEFAULT 0,
        grace_period_days INTEGER NOT NULL DEFAULT 0,
        repayment_frequency TEXT NOT NULL DEFAULT 'monthly',
        term_unit_label TEXT NOT NULL DEFAULT 'months',
        active INTEGER NOT NULL DEFAULT 1
      );
      CREATE TABLE IF NOT EXISTS loans (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        loan_no TEXT UNIQUE NOT NULL,
        client_id INTEGER NOT NULL REFERENCES clients(id),
        product_id INTEGER REFERENCES loan_products(id),
        principal INTEGER NOT NULL,
        interest_rate REAL NOT NULL,
        interest_method TEXT NOT NULL,
        rate_period TEXT NOT NULL DEFAULT 'month',
        term_months INTEGER NOT NULL,
        repayment_frequency TEXT NOT NULL DEFAULT 'monthly',
        application_date TEXT NOT NULL DEFAULT (date('now')),
        disbursement_date TEXT,
        first_due_date TEXT,
        maturity_date TEXT,
        admin_fee INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'Pending',
        approval_status TEXT NOT NULL DEFAULT 'Pending',
        purpose TEXT,
        collateral TEXT,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
      );
      CREATE TABLE IF NOT EXISTS repayment_schedule (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        loan_id INTEGER NOT NULL REFERENCES loans(id) ON DELETE CASCADE,
        installment_no INTEGER NOT NULL,
        due_date TEXT NOT NULL,
        principal_due INTEGER NOT NULL,
        interest_due INTEGER NOT NULL,
        total_due INTEGER NOT NULL,
        principal_paid INTEGER NOT NULL DEFAULT 0,
        interest_paid INTEGER NOT NULL DEFAULT 0,
        penalty_charged INTEGER NOT NULL DEFAULT 0,
        penalty_paid INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'Pending',
        UNIQUE(loan_id, installment_no)
      );
      CREATE TABLE IF NOT EXISTS repayments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        loan_id INTEGER NOT NULL REFERENCES loans(id),
        payment_date TEXT NOT NULL DEFAULT (date('now')),
        amount INTEGER NOT NULL,
        principal_paid INTEGER NOT NULL DEFAULT 0,
        interest_paid INTEGER NOT NULL DEFAULT 0,
        penalty_paid INTEGER NOT NULL DEFAULT 0,
        admin_fee_paid INTEGER NOT NULL DEFAULT 0,
        method TEXT NOT NULL DEFAULT 'Cash',
        reference TEXT,
        notes TEXT,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
      );
      CREATE TABLE IF NOT EXISTS accounts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT UNIQUE NOT NULL,
        name TEXT NOT NULL,
        type TEXT NOT NULL,
        is_control INTEGER NOT NULL DEFAULT 0
      );
      CREATE TABLE IF NOT EXISTS journal_entries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        entry_date TEXT NOT NULL DEFAULT (date('now')),
        reference TEXT,
        source_type TEXT,
        source_id INTEGER,
        description TEXT,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
      );
      CREATE TABLE IF NOT EXISTS journal_lines (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        journal_entry_id INTEGER NOT NULL REFERENCES journal_entries(id) ON DELETE CASCADE,
        account_id INTEGER NOT NULL REFERENCES accounts(id),
        debit INTEGER NOT NULL DEFAULT 0,
        credit INTEGER NOT NULL DEFAULT 0,
        memo TEXT
      );
      CREATE TABLE IF NOT EXISTS employees (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        employee_no TEXT UNIQUE NOT NULL,
        first_name TEXT NOT NULL,
        last_name TEXT NOT NULL,
        national_id TEXT,
        job_title TEXT,
        department TEXT,
        hire_date TEXT,
        basic_salary INTEGER NOT NULL DEFAULT 0,
        bank_name TEXT,
        bank_account_no TEXT,
        nssa_number TEXT,
        tax_number TEXT,
        active INTEGER DEFAULT 1
      );
      CREATE TABLE IF NOT EXISTS company_details (
        key TEXT PRIMARY KEY,
        value TEXT
      );
    `);
  }

  // Seed default Users
  db.run(`
    INSERT OR IGNORE INTO users (id, username, password_hash, salt, full_name, role, active) VALUES
      (1, 'admin', 'pbkdf2_sha256_mock_hash', 'salt1', 'System Administrator', 'admin', 1),
      (2, 'manager', 'pbkdf2_sha256_mock_hash', 'salt2', 'Sarah Moyo', 'manager', 1),
      (3, 'officer', 'pbkdf2_sha256_mock_hash', 'salt3', 'Tendai Ncube', 'loan_officer', 1),
      (4, 'teller', 'pbkdf2_sha256_mock_hash', 'salt4', 'Blessing Sibanda', 'teller', 1);
  `);

  // Seed Chart of Accounts
  db.run(`
    INSERT OR IGNORE INTO accounts (id, code, name, type, is_control) VALUES
      (1, '1000', 'Cash and Bank', 'Asset', 1),
      (2, '1100', 'Loans Receivable - Principal', 'Asset', 1),
      (3, '1150', 'Interest Receivable', 'Asset', 1),
      (4, '2000', 'Accounts Payable', 'Liability', 0),
      (5, '2050', 'Client Credit Balances', 'Liability', 1),
      (6, '2100', 'PAYE Payable', 'Liability', 1),
      (7, '2150', 'NSSA Payable', 'Liability', 1),
      (8, '2160', 'AIDS Levy Payable', 'Liability', 1),
      (9, '2170', 'ZIMDEF Payable', 'Liability', 1),
      (10, '2180', 'Net Salaries Payable', 'Liability', 1),
      (11, '3000', "Owner's Capital", 'Equity', 0),
      (12, '3100', 'Retained Earnings', 'Equity', 0),
      (13, '3200', 'Profit and Loss Account', 'Equity', 0),
      (14, '4000', 'Interest Income', 'Income', 1),
      (15, '4100', 'Admin Fee Income', 'Income', 1),
      (16, '4200', 'Penalty Fee Income', 'Income', 1),
      (17, '4300', 'Bad Debt Recovery Income', 'Income', 1),
      (18, '4400', 'Application Fee Income', 'Income', 1),
      (19, '4500', 'Rollover Fee Income', 'Income', 1),
      (20, '5000', 'Bad Debts Written Off', 'Expense', 1),
      (21, '5100', 'Salaries and Wages Expense', 'Expense', 1),
      (22, '5110', 'Employer NSSA Contributions', 'Expense', 1),
      (23, '5120', 'ZIMDEF Training Levy Expense', 'Expense', 1),
      (24, '5900', 'General Operating Expenses', 'Expense', 0);
  `);

  // Seed Locations
  db.run(`
    INSERT OR IGNORE INTO locations (id, name, active) VALUES
      (1, 'Harare Central', 1),
      (2, 'Bulawayo CBD', 1),
      (3, 'Mutare Main', 1),
      (4, 'Gweru Town', 1),
      (5, 'Chitungwiza Unit L', 1);
  `);

  // Seed Loan Products
  db.run(`
    INSERT OR IGNORE INTO loan_products (id, name, interest_method, interest_rate, rate_period, admin_fee_pct, penalty_pct, grace_period_days, repayment_frequency, term_unit_label, active) VALUES
      (1, 'Standard Microloan', 'flat', 15.0, 'month', 3.0, 5.0, 5, 'monthly', 'months', 1),
      (2, 'SME Working Capital', 'reducing_balance', 12.0, 'month', 2.5, 5.0, 7, 'monthly', 'months', 1),
      (3, 'Agro-Harvest Seasonal', 'interest_only_balloon', 10.0, 'month', 4.0, 5.0, 10, 'monthly', 'months', 1),
      (4, 'Emergency Fast Cash', 'flat', 20.0, 'month', 5.0, 10.0, 3, 'weekly', 'weeks', 1);
  `);

  // Seed Company Details
  db.run(`
    INSERT OR REPLACE INTO company_details (key, value) VALUES
      ('company_name', 'Microfinance Manager (Pvt) Ltd'),
      ('currency', 'USD ($)'),
      ('default_interest_rate', '15'),
      ('default_penalty_rate', '5'),
      ('grace_period_days', '5'),
      ('loan_processing_fee_rate', '3'),
      ('license_number', 'RBZ-MF-2026-088'),
      ('system_date', '2026-09-16');
  `);

  console.log(`[SQLite] Schema successfully initialized with clean slate`);
}
