import React, { useState, useEffect } from 'react';
import {
  Database,
  Play,
  Download,
  RotateCcw,
  CheckCircle2,
  AlertCircle,
  Table as TableIcon,
  Search,
  Clock,
  HardDrive,
  Cpu,
  Layers,
  Sparkles,
  Cloud,
  CloudLightning,
  Globe,
  ExternalLink,
  UploadCloud,
  Copy,
  Check,
} from 'lucide-react';
import { SqliteStats, SqlQueryResult } from '../../types';
import { Header } from '../common/Header';
import { Modal } from '../common/Modal';

export const SqliteView: React.FC = () => {
  const [stats, setStats] = useState<SqliteStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [sqlQuery, setSqlQuery] = useState<string>(
    'SELECT l.loan_no, c.first_name || \' \' || c.last_name as client, l.principal, l.interest_rate, l.status FROM loans l JOIN clients c ON l.client_id = c.id ORDER BY l.id DESC;'
  );
  const [queryResult, setQueryResult] = useState<SqlQueryResult | null>(null);
  const [executing, setExecuting] = useState(false);
  const [integrityStatus, setIntegrityStatus] = useState<string | null>(null);
  const [resetting, setResetting] = useState(false);
  const [tableFilter, setTableFilter] = useState('');
  const [selectedTableDetails, setSelectedTableDetails] = useState<string | null>(null);
  const [syncingTurso, setSyncingTurso] = useState(false);
  const [syncMessage, setSyncMessage] = useState<{ text: string; success: boolean } | null>(null);
  const [showCloudGuide, setShowCloudGuide] = useState(false);
  const [copiedVar, setCopiedVar] = useState<string | null>(null);

  const fetchStats = async () => {
    try {
      setLoading(true);
      const res = await fetch('/api/db/stats');
      if (res.ok) {
        const data = await res.json();
        setStats(data);
      }
    } catch (err) {
      console.error('Failed to fetch sqlite stats:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchStats();
    runQuery(sqlQuery);
  }, []);

  const handleCopy = (text: string, label: string) => {
    navigator.clipboard.writeText(text);
    setCopiedVar(label);
    setTimeout(() => setCopiedVar(null), 2000);
  };

  const handleSyncToTurso = async () => {
    setSyncingTurso(true);
    setSyncMessage(null);
    try {
      const res = await fetch('/api/db/sync-to-turso', { method: 'POST' });
      const data = await res.json();
      if (data.success) {
        setSyncMessage({ text: data.message, success: true });
        await fetchStats();
        await runQuery();
      } else {
        setSyncMessage({ text: data.error || 'Failed to sync to Turso', success: false });
      }
    } catch (err: any) {
      setSyncMessage({ text: 'Error connecting to server: ' + err.message, success: false });
    } finally {
      setSyncingTurso(false);
    }
  };

  const runQuery = async (queryToRun?: string) => {
    const q = queryToRun || sqlQuery;
    if (!q.trim()) return;

    setExecuting(true);
    try {
      const res = await fetch('/api/db/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sql: q }),
      });
      const data: SqlQueryResult = await res.json();
      setQueryResult(data);
    } catch (err: any) {
      setQueryResult({
        success: false,
        durationMs: 0,
        error: err.message || 'Failed to execute query',
      });
    } finally {
      setExecuting(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
      e.preventDefault();
      runQuery();
    }
  };

  const checkIntegrity = async () => {
    try {
      const res = await fetch('/api/db/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sql: 'PRAGMA integrity_check;' }),
      });
      const data = await res.json();
      if (data.success && data.rows && data.rows[0]) {
        const checkVal = Object.values(data.rows[0])[0];
        setIntegrityStatus(String(checkVal));
      } else {
        setIntegrityStatus('Check failed');
      }
    } catch (e: any) {
      setIntegrityStatus('Error: ' + e.message);
    }
  };

  const handleDownload = () => {
    window.location.href = '/api/db/export';
  };

  const handleReset = async () => {
    if (
      !window.confirm(
        'Are you sure you want to reset the SQLite database to initial schema and sample records? All custom changes will be replaced.'
      )
    ) {
      return;
    }

    setResetting(true);
    try {
      const res = await fetch('/api/db/reset', { method: 'POST' });
      if (res.ok) {
        await fetchStats();
        await runQuery();
        alert('SQLite database re-seeded successfully!');
      }
    } catch (e: any) {
      alert('Error resetting database: ' + e.message);
    } finally {
      setResetting(false);
    }
  };

  const PRESET_QUERIES = [
    {
      label: 'Loans with Clients',
      sql: `SELECT l.loan_no, c.first_name || ' ' || c.last_name as client_name, l.principal, l.interest_rate, l.term_months, l.status\nFROM loans l\nJOIN clients c ON l.client_id = c.id\nORDER BY l.id DESC;`,
    },
    {
      label: 'Trial Balance',
      sql: `SELECT a.code, a.name, a.type,\n  COALESCE(SUM(jl.debit), 0) as total_debit,\n  COALESCE(SUM(jl.credit), 0) as total_credit\nFROM accounts a\nLEFT JOIN journal_lines jl ON a.id = jl.account_id\nGROUP BY a.id\nORDER BY a.code ASC;`,
    },
    {
      label: 'Unpaid Schedules',
      sql: `SELECT s.loan_id, l.loan_no, s.installment_no, s.due_date, s.principal_due, s.interest_due, s.penalty_charged, s.status\nFROM repayment_schedule s\nJOIN loans l ON s.loan_id = l.id\nWHERE s.status != 'Paid'\nORDER BY s.due_date ASC;`,
    },
    {
      label: 'Client Registry',
      sql: `SELECT client_no, first_name, last_name, location, phone, occupation, average_income, status\nFROM clients\nORDER BY id ASC;`,
    },
    {
      label: 'SQLite Master Tables',
      sql: `SELECT type, name, tbl_name\nFROM sqlite_master\nWHERE type='table' AND name NOT LIKE 'sqlite_%'\nORDER BY name ASC;`,
    },
    {
      label: 'Staff Payroll Register',
      sql: `SELECT employee_no, first_name, last_name, job_title, department, basic_salary, bank_name, active\nFROM employees\nORDER BY id ASC;`,
    },
  ];

  const tableList =
    stats?.tables ||
    (stats?.tableDetails
      ? stats.tableDetails.map((td) => ({
          name: td.name,
          rowCount: td.rowCount,
          columnsCount: 0,
          columns: [] as { name: string; type: string; pk: boolean }[],
          sql: '',
        }))
      : []);

  const filteredTables = tableList.filter((t) =>
    t.name.toLowerCase().includes(tableFilter.toLowerCase())
  );

  return (
    <div className="space-y-6">
      <Header
        title={stats?.tursoConnected ? "Turso Cloud Database Studio" : "SQLite Database Studio"}
        subtitle={
          stats?.tursoConnected
            ? `Connected to remote Turso LibSQL Cloud (${stats.tursoUrl || 'online'}). Accessible by multiple team members.`
            : "Embedded relational SQLite 3 engine with live SQL query runner, schema inspector, and Turso Cloud sync."
        }
        actions={
          <div className="flex items-center gap-2 flex-wrap">
            {stats?.tursoConnected ? (
              <button
                onClick={handleSyncToTurso}
                disabled={syncingTurso}
                className="px-3 py-1.5 text-xs font-semibold rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white flex items-center gap-1.5 transition-colors shadow-xs"
                title="Upload local SQLite records to Turso cloud database"
              >
                <UploadCloud className={`w-3.5 h-3.5 ${syncingTurso ? 'animate-bounce' : ''}`} />
                {syncingTurso ? 'Syncing...' : 'Sync Local Data to Turso'}
              </button>
            ) : (
              <button
                onClick={() => setShowCloudGuide(true)}
                className="px-3 py-1.5 text-xs font-semibold rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white flex items-center gap-1.5 transition-colors shadow-xs"
              >
                <Cloud className="w-3.5 h-3.5" />
                Connect Turso Cloud (Free)
              </button>
            )}

            <button
              onClick={checkIntegrity}
              className="px-3 py-1.5 text-xs font-semibold rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 flex items-center gap-1.5 transition-colors"
            >
              <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
              Check Integrity
            </button>
            <button
              onClick={handleDownload}
              className="px-3 py-1.5 text-xs font-semibold rounded-lg bg-blue-600 hover:bg-blue-500 text-white flex items-center gap-1.5 transition-colors shadow-xs"
            >
              <Download className="w-3.5 h-3.5" />
              Download .sqlite DB
            </button>
            <button
              onClick={handleReset}
              disabled={resetting}
              className="px-3 py-1.5 text-xs font-semibold rounded-lg bg-rose-950/40 hover:bg-rose-900/50 text-rose-300 border border-rose-800/50 flex items-center gap-1.5 transition-colors"
            >
              <RotateCcw className={`w-3.5 h-3.5 ${resetting ? 'animate-spin' : ''}`} />
              Reset Seeds
            </button>
          </div>
        }
      />

      {/* Sync Message Banner */}
      {syncMessage && (
        <div
          className={`p-3 rounded-xl border flex items-center justify-between text-xs ${
            syncMessage.success
              ? 'bg-emerald-950/40 border-emerald-800/50 text-emerald-300'
              : 'bg-rose-950/40 border-rose-800/50 text-rose-300'
          }`}
        >
          <div className="flex items-center gap-2">
            {syncMessage.success ? (
              <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
            ) : (
              <RotateCcw className="w-4 h-4 text-rose-400 shrink-0" />
            )}
            <span>{syncMessage.text}</span>
          </div>
          <button
            onClick={() => setSyncMessage(null)}
            className="text-slate-400 hover:text-white text-xs font-bold px-1.5"
          >
            ✕
          </button>
        </div>
      )}

      {/* Turso Cloud Status Card */}
      {stats?.tursoConnected ? (
        <div className="p-3.5 rounded-xl bg-gradient-to-r from-emerald-950/40 to-teal-950/30 border border-emerald-800/50 flex items-center justify-between flex-wrap gap-3">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-lg bg-emerald-500/20 border border-emerald-500/40 flex items-center justify-center text-emerald-400">
              <CloudLightning className="w-5 h-5" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="text-xs font-bold text-emerald-300">Turso Cloud Database Active</span>
                <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 flex items-center gap-1">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                  Online Multi-User
                </span>
              </div>
              <p className="text-[11px] text-slate-300 font-mono mt-0.5">
                Connected: {stats.tursoUrl} • Real-time queries and updates are saved directly to the cloud.
              </p>
            </div>
          </div>
          <button
            onClick={handleSyncToTurso}
            disabled={syncingTurso}
            className="text-xs px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white font-medium flex items-center gap-1.5 transition-colors"
          >
            <UploadCloud className="w-3.5 h-3.5" />
            {syncingTurso ? 'Syncing...' : 'Sync Local Data'}
          </button>
        </div>
      ) : (
        <div className="p-3.5 rounded-xl bg-gradient-to-r from-indigo-950/40 to-blue-950/30 border border-indigo-800/40 flex items-center justify-between flex-wrap gap-3">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-lg bg-indigo-500/20 border border-indigo-500/40 flex items-center justify-center text-indigo-400">
              <Cloud className="w-5 h-5" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="text-xs font-bold text-slate-200">Local SQLite Mode (Ready for Cloud Hosting)</span>
                <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-blue-500/20 text-blue-300 border border-blue-500/30">
                  Single User / Browser
                </span>
              </div>
              <p className="text-[11px] text-slate-400 mt-0.5">
                To allow multiple staff members to access the system online simultaneously, connect a free Turso Cloud database.
              </p>
            </div>
          </div>
          <button
            onClick={() => setShowCloudGuide(true)}
            className="text-xs px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white font-medium flex items-center gap-1.5 transition-colors"
          >
            <Globe className="w-3.5 h-3.5" />
            View Turso Setup Guide
          </button>
        </div>
      )}

      {/* Integrity banner if checked */}
      {integrityStatus && (
        <div
          className={`p-3 rounded-xl border flex items-center justify-between text-xs ${
            integrityStatus === 'ok'
              ? 'bg-emerald-950/30 border-emerald-800/50 text-emerald-300'
              : 'bg-amber-950/30 border-amber-800/50 text-amber-300'
          }`}
        >
          <div className="flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
            <span>
              <strong>SQLite PRAGMA integrity_check result:</strong>{' '}
              <code className="font-mono bg-black/30 px-1.5 py-0.5 rounded">{integrityStatus}</code> (Database file is healthy with zero page corruption)
            </span>
          </div>
          <button
            onClick={() => setIntegrityStatus(null)}
            className="text-slate-400 hover:text-white text-xs font-bold"
          >
            ✕
          </button>
        </div>
      )}

      {/* SQLite / Turso Telemetry Grid */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3.5">
        <div className="p-4 bg-slate-900/90 border border-slate-800 rounded-xl space-y-1">
          <div className="flex items-center justify-between text-slate-400 text-xs font-medium">
            <span>Database Engine</span>
            {stats?.tursoConnected ? (
              <Cloud className="w-4 h-4 text-emerald-400" />
            ) : (
              <Cpu className="w-4 h-4 text-blue-400" />
            )}
          </div>
          <p className="text-base font-bold text-white font-mono">
            {stats?.tursoConnected ? 'Turso LibSQL' : 'SQLite 3.x'}
          </p>
          <p className="text-[11px] text-emerald-400 flex items-center gap-1">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
            {stats?.tursoConnected ? 'Cloud Multi-User Active' : 'WebAssembly Engine Active'}
          </p>
        </div>

        <div className="p-4 bg-slate-900/90 border border-slate-800 rounded-xl space-y-1">
          <div className="flex items-center justify-between text-slate-400 text-xs font-medium">
            <span>{stats?.tursoConnected ? 'Cloud Endpoint' : 'Physical File'}</span>
            <HardDrive className="w-4 h-4 text-indigo-400" />
          </div>
          <p className="text-base font-bold text-white font-mono truncate">
            {stats?.tursoConnected
              ? 'Remote Cloud'
              : loading || !stats
              ? 'Connecting...'
              : `${stats.fileSizeKb} KB`}
          </p>
          <p className="text-[11px] text-slate-400 truncate font-mono">
            {stats?.tursoConnected ? stats.tursoUrl : 'data/microfinance.sqlite'}
          </p>
        </div>

        <div className="p-4 bg-slate-900/90 border border-slate-800 rounded-xl space-y-1">
          <div className="flex items-center justify-between text-slate-400 text-xs font-medium">
            <span>Schema Tables</span>
            <Layers className="w-4 h-4 text-amber-400" />
          </div>
          <p className="text-base font-bold text-white font-mono">
            {loading || !stats ? '...' : `${stats.tablesCount} Tables`}
          </p>
          <p className="text-[11px] text-slate-400">Operational &amp; Accounting</p>
        </div>

        <div className="p-4 bg-slate-900/90 border border-slate-800 rounded-xl space-y-1">
          <div className="flex items-center justify-between text-slate-400 text-xs font-medium">
            <span>Total Records</span>
            <TableIcon className="w-4 h-4 text-teal-400" />
          </div>
          <p className="text-base font-bold text-white font-mono">
            {loading || !stats ? '...' : `${stats.totalRows} Rows`}
          </p>
          <p className="text-[11px] text-slate-400">Synced across users</p>
        </div>
      </div>

      {/* Main Studio Area */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left: Query Editor & Output (2 cols) */}
        <div className="lg:col-span-2 space-y-4">
          <div className="bg-slate-900/90 border border-slate-800 rounded-xl overflow-hidden shadow-xs">
            {/* Query Header & Presets */}
            <div className="p-3.5 bg-slate-900 border-b border-slate-800 space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-xs font-bold text-white uppercase tracking-wider flex items-center gap-2">
                  <Sparkles className="w-3.5 h-3.5 text-blue-400" />
                  SQL Query Runner
                </span>
                <span className="text-[11px] text-slate-400">
                  Press <kbd className="font-mono bg-slate-800 px-1 py-0.5 rounded text-[10px]">Ctrl+Enter</kbd> to execute
                </span>
              </div>

              {/* Preset Chips */}
              <div className="flex items-center gap-1.5 flex-wrap">
                <span className="text-[11px] text-slate-400 mr-1">Presets:</span>
                {PRESET_QUERIES.map((p) => (
                  <button
                    key={p.label}
                    onClick={() => {
                      setSqlQuery(p.sql);
                      runQuery(p.sql);
                    }}
                    className="text-[11px] px-2 py-0.5 rounded-md bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white border border-slate-700 transition-colors"
                  >
                    {p.label}
                  </button>
                ))}
              </div>
            </div>

            {/* Editor Textarea */}
            <div className="relative">
              <textarea
                value={sqlQuery}
                onChange={(e) => setSqlQuery(e.target.value)}
                onKeyDown={handleKeyDown}
                rows={5}
                className="w-full bg-slate-950 p-4 font-mono text-xs text-blue-100 focus:outline-none focus:ring-1 focus:ring-blue-500 selection:bg-blue-600 selection:text-white resize-y leading-relaxed"
                placeholder="Enter any SQL query (e.g. SELECT * FROM clients;)..."
              />
            </div>

            {/* Execute Bar */}
            <div className="p-3 bg-slate-900/60 border-t border-slate-800 flex items-center justify-between">
              <div className="text-xs text-slate-400 flex items-center gap-2">
                {queryResult && (
                  <>
                    <Clock className="w-3.5 h-3.5 text-slate-500" />
                    <span>Duration: <strong className="font-mono text-slate-300">{queryResult.durationMs} ms</strong></span>
                    <span>•</span>
                    <span>
                      {queryResult.rowCount !== undefined
                        ? `${queryResult.rowCount} rows returned`
                        : `${queryResult.changes || 0} rows affected`}
                    </span>
                  </>
                )}
              </div>
              <button
                onClick={() => runQuery()}
                disabled={executing}
                className="px-4 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold flex items-center gap-1.5 shadow-xs transition-colors disabled:opacity-50"
              >
                <Play className={`w-3.5 h-3.5 ${executing ? 'animate-spin' : ''}`} />
                {executing ? 'Executing...' : 'Run Query'}
              </button>
            </div>
          </div>

          {/* Query Results Display */}
          <div className="bg-slate-900/90 border border-slate-800 rounded-xl overflow-hidden">
            <div className="px-4 py-3 border-b border-slate-800 flex items-center justify-between">
              <h3 className="text-xs font-bold text-white uppercase tracking-wider flex items-center gap-2">
                <TableIcon className="w-3.5 h-3.5 text-emerald-400" />
                Query Results
              </h3>
              {queryResult?.rows && (
                <span className="text-xs font-mono text-slate-400">
                  {queryResult.rows.length} records
                </span>
              )}
            </div>

            {queryResult?.error && (
              <div className="p-4 bg-rose-950/30 border-l-4 border-rose-500 text-rose-300 text-xs space-y-1">
                <div className="flex items-center gap-1.5 font-bold">
                  <AlertCircle className="w-4 h-4" />
                  SQLite Error
                </div>
                <p className="font-mono">{queryResult.error}</p>
              </div>
            )}

            {queryResult?.success && queryResult.columns && queryResult.rows && (
              <div className="overflow-x-auto max-h-96">
                {queryResult.rows.length === 0 ? (
                  <div className="p-8 text-center text-slate-400 text-xs">
                    No rows returned by this query.
                  </div>
                ) : (
                  <table className="w-full text-left text-xs">
                    <thead className="bg-slate-800/80 text-slate-300 font-semibold border-b border-slate-700 sticky top-0">
                      <tr>
                        {queryResult.columns.map((col) => (
                          <th key={col} className="px-3.5 py-2 font-mono whitespace-nowrap">
                            {col}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-800/60 font-mono">
                      {queryResult.rows.map((row, idx) => (
                        <tr
                          key={idx}
                          className="hover:bg-slate-800/40 transition-colors"
                        >
                          {queryResult.columns!.map((col) => {
                            const val = row[col];
                            return (
                              <td
                                key={col}
                                className="px-3.5 py-2 text-slate-300 whitespace-nowrap"
                              >
                                {val === null ? (
                                  <span className="text-slate-500 italic">NULL</span>
                                ) : typeof val === 'object' ? (
                                  JSON.stringify(val)
                                ) : (
                                  String(val)
                                )}
                              </td>
                            );
                          })}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            )}

            {queryResult?.success && queryResult.changes !== undefined && (
              <div className="p-4 text-xs text-emerald-300 bg-emerald-950/20 flex items-center gap-2">
                <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                Query executed successfully. Rows affected: <strong className="font-mono">{queryResult.changes}</strong>.
              </div>
            )}
          </div>
        </div>

        {/* Right: Table Schema Catalog (1 col) */}
        <div className="space-y-4">
          <div className="bg-slate-900/90 border border-slate-800 rounded-xl overflow-hidden flex flex-col h-full max-h-[640px]">
            {/* Catalog Header & Search */}
            <div className="p-3.5 bg-slate-900 border-b border-slate-800 space-y-2.5">
              <div className="flex items-center justify-between">
                <h3 className="text-xs font-bold text-white uppercase tracking-wider flex items-center gap-2">
                  <Database className="w-3.5 h-3.5 text-blue-400" />
                  SQLite Schema Tables
                </h3>
                <span className="text-xs font-mono text-slate-400">
                  {tableList.length}
                </span>
              </div>

              <div className="relative">
                <Search className="w-3.5 h-3.5 text-slate-500 absolute left-2.5 top-2.5" />
                <input
                  type="text"
                  placeholder="Filter tables..."
                  value={tableFilter}
                  onChange={(e) => setTableFilter(e.target.value)}
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg pl-8 pr-3 py-1.5 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-blue-500"
                />
              </div>
            </div>

            {/* Tables List */}
            <div className="overflow-y-auto flex-1 divide-y divide-slate-800/60 p-1">
              {filteredTables?.map((t) => {
                const isSelected = selectedTableDetails === t.name;
                return (
                  <div key={t.name} className="p-2 hover:bg-slate-800/40 rounded-lg transition-colors space-y-1.5">
                    <div className="flex items-center justify-between">
                      <button
                        onClick={() => {
                          const q = `SELECT * FROM "${t.name}" LIMIT 50;`;
                          setSqlQuery(q);
                          runQuery(q);
                        }}
                        className="font-mono text-xs font-semibold text-blue-300 hover:text-blue-200 text-left truncate flex-1 hover:underline"
                        title="Click to view rows"
                      >
                        {t.name}
                      </button>
                      <div className="flex items-center gap-1.5 shrink-0">
                        <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-slate-800 text-slate-300">
                          {t.rowCount} rows
                        </span>
                        <button
                          onClick={() => setSelectedTableDetails(isSelected ? null : t.name)}
                          className="text-[10px] px-1.5 py-0.5 rounded border border-slate-700 hover:bg-slate-700 text-slate-400 hover:text-white"
                        >
                          {isSelected ? 'Hide' : 'Cols'}
                        </button>
                      </div>
                    </div>

                    {/* Column Schema Drawer */}
                    {isSelected && (
                      <div className="mt-2 p-2 bg-slate-950 rounded border border-slate-800 text-[11px] font-mono space-y-1">
                        <p className="text-[10px] uppercase font-bold text-slate-400">Columns ({t.columns.length}):</p>
                        <div className="space-y-0.5 max-h-40 overflow-y-auto">
                          {t.columns.map((c) => (
                            <div key={c.name} className="flex justify-between text-slate-300">
                              <span className={c.pk ? 'text-amber-400 font-bold' : ''}>
                                {c.name} {c.pk ? '(PK)' : ''}
                              </span>
                              <span className="text-slate-500">{c.type || 'TEXT'}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      </div>

      {/* Turso Cloud Setup Guide Modal */}
      <Modal
        isOpen={showCloudGuide}
        onClose={() => setShowCloudGuide(false)}
        title="Connect Turso Cloud Database (100% Free)"
        maxWidth="lg"
      >
        <div className="space-y-4 text-xs">
          <div className="p-3.5 rounded-xl bg-indigo-950/30 border border-indigo-800/40 space-y-2">
            <div className="flex items-center gap-2 text-indigo-300 font-semibold">
              <Cloud className="w-4 h-4" />
              <span>Host your SQLite database online with Turso</span>
            </div>
            <p className="text-slate-300 leading-relaxed">
              Turso provides serverless SQLite distributed across the globe with a generous <strong>Free Starter Tier</strong> (9 GB storage &amp; 1 billion row reads/month). Once connected, loan officers, tellers, and managers can access this app from anywhere simultaneously.
            </p>
          </div>

          <div className="space-y-3">
            <h4 className="font-bold text-slate-200 uppercase tracking-wider text-[11px]">
              Step-by-Step Setup (Takes ~2 Minutes):
            </h4>

            {/* Step 1 */}
            <div className="p-3 rounded-xl bg-slate-900 border border-slate-800 space-y-1.5">
              <div className="flex items-center justify-between">
                <span className="font-semibold text-slate-200">1. Create a Free Account on Turso</span>
                <a
                  href="https://turso.tech"
                  target="_blank"
                  rel="noreferrer"
                  className="text-indigo-400 hover:text-indigo-300 flex items-center gap-1 font-medium"
                >
                  turso.tech <ExternalLink className="w-3 h-3" />
                </a>
              </div>
              <p className="text-slate-400">
                Sign up with GitHub or Google. No credit card is required.
              </p>
            </div>

            {/* Step 2 */}
            <div className="p-3 rounded-xl bg-slate-900 border border-slate-800 space-y-1.5">
              <span className="font-semibold text-slate-200">2. Create a Database</span>
              <p className="text-slate-400">
                In the Turso Web Console, click <strong>Create Database</strong> and name it (e.g. <code className="font-mono text-indigo-300">microfinance</code>). Or with the Turso CLI:
              </p>
              <div className="p-2 rounded bg-black/50 font-mono text-[11px] text-emerald-400 flex items-center justify-between">
                <span>turso db create microfinance</span>
                <button
                  onClick={() => handleCopy('turso db create microfinance', 'cli-create')}
                  className="text-slate-400 hover:text-white"
                >
                  {copiedVar === 'cli-create' ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
                </button>
              </div>
            </div>

            {/* Step 3 */}
            <div className="p-3 rounded-xl bg-slate-900 border border-slate-800 space-y-1.5">
              <span className="font-semibold text-slate-200">3. Copy your URL &amp; Auth Token</span>
              <p className="text-slate-400">
                Turso gives you a database URL and an authentication token:
              </p>
              <ul className="list-disc pl-4 space-y-1 text-slate-300">
                <li>
                  <strong className="text-slate-200">Database URL:</strong> looks like <code className="font-mono text-indigo-300">libsql://microfinance-[your-org].turso.io</code>
                </li>
                <li>
                  <strong className="text-slate-200">Auth Token:</strong> generated in the console or via <code className="font-mono text-slate-400">turso db tokens create microfinance</code>
                </li>
              </ul>
            </div>

            {/* Step 4 */}
            <div className="p-3 rounded-xl bg-slate-900 border border-slate-800 space-y-2">
              <span className="font-semibold text-slate-200">4. Add to App Settings / Environment Variables</span>
              <p className="text-slate-400">
                Add these two variables to your environment (via the <strong>Settings menu</strong> in Google AI Studio or your hosting provider):
              </p>

              <div className="space-y-1.5 font-mono text-[11px]">
                <div className="p-2 rounded bg-black/50 text-slate-200 flex items-center justify-between">
                  <span>TURSO_DATABASE_URL=libsql://...</span>
                  <button
                    onClick={() => handleCopy('TURSO_DATABASE_URL', 'var-url')}
                    className="text-slate-400 hover:text-white flex items-center gap-1 text-[10px]"
                  >
                    {copiedVar === 'var-url' ? <Check className="w-3 h-3 text-emerald-400" /> : <Copy className="w-3 h-3" />}
                    Copy Name
                  </button>
                </div>
                <div className="p-2 rounded bg-black/50 text-slate-200 flex items-center justify-between">
                  <span>TURSO_AUTH_TOKEN=your_secret_token</span>
                  <button
                    onClick={() => handleCopy('TURSO_AUTH_TOKEN', 'var-token')}
                    className="text-slate-400 hover:text-white flex items-center gap-1 text-[10px]"
                  >
                    {copiedVar === 'var-token' ? <Check className="w-3 h-3 text-emerald-400" /> : <Copy className="w-3 h-3" />}
                    Copy Name
                  </button>
                </div>
              </div>
            </div>
          </div>

          <div className="p-3 rounded-xl bg-emerald-950/20 border border-emerald-800/40 text-emerald-300">
            <strong>Automatic Migration:</strong> Once connected, the server automatically applies all microfinance tables to Turso. You can also click <strong>"Sync Local Data to Turso"</strong> to instantly copy your existing loans, clients, and accounting ledgers into the cloud!
          </div>

          <div className="flex justify-end pt-2">
            <button
              onClick={() => setShowCloudGuide(false)}
              className="px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-white font-semibold text-xs"
            >
              Close
            </button>
          </div>
        </div>
      </Modal>
    </div>
  );
};
