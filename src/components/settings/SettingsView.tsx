import React, { useState, useEffect } from 'react';
import {
  Settings,
  Save,
  Download,
  Upload,
  RefreshCw,
  ShieldAlert,
  CheckCircle2,
  Building,
  Database,
  Cloud,
  Sun,
  Moon,
  Check,
  Palette,
} from 'lucide-react';
import { useApp } from '../../context/AppContext';
import { useTheme } from '../../context/ThemeContext';
import { Header } from '../common/Header';

interface SettingsViewProps {
  onNavigate?: (tab: any) => void;
}

export const SettingsView: React.FC<SettingsViewProps> = ({ onNavigate }) => {
  const {
    settings,
    updateSettings,
    exportDatabaseJSON,
    importDatabaseJSON,
    resetToInitialSeed,
    systemDate,
  } = useApp();
  const { theme, setTheme } = useTheme();

  const [form, setForm] = useState({ ...settings });
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [importStatus, setImportStatus] = useState<string | null>(null);
  const [tursoInfo, setTursoInfo] = useState<{ configured: boolean; maskedUrl: string; mode: string } | null>(null);

  useEffect(() => {
    fetch('/api/db/turso-info')
      .then((res) => res.json())
      .then((data) => setTursoInfo(data))
      .catch(() => {});
  }, []);

  const handleSave = (e: React.FormEvent) => {
    e.preventDefault();
    updateSettings(form);
    setSaveSuccess(true);
    setTimeout(() => setSaveSuccess(false), 3000);
  };

  const handleExport = () => {
    const jsonStr = exportDatabaseJSON();
    const blob = new Blob([jsonStr], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `microfinance_backup_${systemDate}.json`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const handleImport = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = (event) => {
      try {
        const text = event.target?.result as string;
        const success = importDatabaseJSON(text);
        if (success) {
          setImportStatus('Database successfully restored from backup!');
        } else {
          setImportStatus('Failed: Invalid backup JSON format.');
        }
      } catch (err) {
        setImportStatus('Error reading backup file.');
      }
    };
    reader.readAsText(file);
  };

  const handleReset = () => {
    if (
      window.confirm(
        'WARNING: This will reset all loans, clients, ledger entries, and payroll records to default demonstration data. Are you sure you want to proceed?'
      )
    ) {
      resetToInitialSeed();
      alert('System successfully reset to default demo dataset.');
    }
  };

  return (
    <div id="settings-view" className="space-y-6">
      <Header
        title="System Configuration & Preferences"
        subtitle="Customize theme appearance, lending rules, institutional profile, and data backups"
        actions={
          <button
            id="btn-save-settings"
            onClick={handleSave}
            className="flex items-center gap-1.5 px-3.5 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-xl text-xs font-semibold shadow-xs transition-colors"
          >
            <Save className="w-4 h-4" />
            Save Configuration
          </button>
        }
      />

      {saveSuccess && (
        <div className="p-3 bg-emerald-50 dark:bg-emerald-950/40 border border-emerald-200 dark:border-emerald-800 rounded-xl text-xs text-emerald-800 dark:text-emerald-300 flex items-center gap-2 shadow-2xs">
          <CheckCircle2 className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
          System lending rules and institutional configuration updated successfully.
        </div>
      )}

      {importStatus && (
        <div className="p-3 bg-blue-50 dark:bg-blue-950/40 border border-blue-200 dark:border-blue-800 rounded-xl text-xs text-blue-800 dark:text-blue-300 flex items-center gap-2 shadow-2xs">
          <CheckCircle2 className="w-4 h-4 text-blue-600 dark:text-blue-400" />
          {importStatus}
        </div>
      )}

      {/* Theme Appearance Selector Section */}
      <div className="p-5 bg-white dark:bg-[#111C38] border border-slate-200/90 dark:border-[#1E2D5A] rounded-2xl space-y-4 shadow-2xs">
        <div className="flex items-center justify-between border-b border-slate-100 dark:border-[#1E2D5A] pb-3">
          <div className="flex items-center gap-2">
            <Palette className="w-4 h-4 text-blue-600 dark:text-blue-400" />
            <div>
              <h3 className="text-sm font-bold text-slate-900 dark:text-white">Theme &amp; Appearance</h3>
              <p className="text-xs text-slate-500 dark:text-slate-400">Choose between crisp Light theme or focused Dark theme</p>
            </div>
          </div>
          <span className="text-xs font-semibold px-2.5 py-1 rounded-full bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 border border-slate-200 dark:border-slate-700">
            Active: <span className="capitalize font-bold text-blue-600 dark:text-blue-400">{theme}</span>
          </span>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 pt-1">
          {/* Light Theme Card */}
          <button
            type="button"
            onClick={() => setTheme('light')}
            className={`p-4 rounded-xl border text-left transition-all relative overflow-hidden group ${
              theme === 'light'
                ? 'border-blue-600 bg-blue-50/40 dark:bg-blue-950/20 ring-2 ring-blue-500/20 shadow-xs'
                : 'border-slate-200 dark:border-slate-800 bg-slate-50/60 dark:bg-[#0E1730] hover:border-slate-300 dark:hover:border-slate-700'
            }`}
          >
            <div className="flex items-start justify-between mb-3">
              <div className="flex items-center gap-2.5">
                <div className="w-9 h-9 rounded-xl bg-amber-100 text-amber-600 flex items-center justify-center shadow-2xs">
                  <Sun className="w-5 h-5 fill-amber-500/20" />
                </div>
                <div>
                  <h4 className="text-sm font-bold text-slate-900 dark:text-white">Light Mode</h4>
                  <p className="text-[11px] text-slate-500 dark:text-slate-400">Clean, crisp high-contrast layout</p>
                </div>
              </div>
              {theme === 'light' && (
                <span className="flex items-center gap-1 text-[11px] font-bold text-blue-600 bg-blue-100/80 px-2 py-0.5 rounded-full">
                  <Check className="w-3 h-3" />
                  Active
                </span>
              )}
            </div>

            {/* Visual preview widget */}
            <div className="p-2.5 rounded-lg bg-white border border-slate-200 shadow-2xs space-y-1.5">
              <div className="flex items-center justify-between">
                <div className="w-16 h-2 rounded bg-slate-300" />
                <div className="w-8 h-2 rounded bg-blue-500" />
              </div>
              <div className="w-28 h-3 rounded bg-slate-800 font-bold" />
              <div className="grid grid-cols-3 gap-1 pt-1">
                <div className="h-4 rounded bg-slate-100 border border-slate-200" />
                <div className="h-4 rounded bg-slate-100 border border-slate-200" />
                <div className="h-4 rounded bg-emerald-50 border border-emerald-200" />
              </div>
            </div>
          </button>

          {/* Dark Theme Card */}
          <button
            type="button"
            onClick={() => setTheme('dark')}
            className={`p-4 rounded-xl border text-left transition-all relative overflow-hidden group ${
              theme === 'dark'
                ? 'border-blue-500 bg-blue-950/30 ring-2 ring-blue-500/20 shadow-xs'
                : 'border-slate-200 dark:border-slate-800 bg-slate-50/60 dark:bg-[#0E1730] hover:border-slate-300 dark:hover:border-slate-700'
            }`}
          >
            <div className="flex items-start justify-between mb-3">
              <div className="flex items-center gap-2.5">
                <div className="w-9 h-9 rounded-xl bg-blue-900/60 text-blue-400 flex items-center justify-center shadow-2xs border border-blue-800">
                  <Moon className="w-5 h-5 fill-blue-400/20" />
                </div>
                <div>
                  <h4 className="text-sm font-bold text-slate-900 dark:text-white">Dark Mode</h4>
                  <p className="text-[11px] text-slate-500 dark:text-slate-400">Deep obsidian navy night layout</p>
                </div>
              </div>
              {theme === 'dark' && (
                <span className="flex items-center gap-1 text-[11px] font-bold text-blue-400 bg-blue-900/60 px-2 py-0.5 rounded-full border border-blue-800">
                  <Check className="w-3 h-3" />
                  Active
                </span>
              )}
            </div>

            {/* Visual preview widget */}
            <div className="p-2.5 rounded-lg bg-[#0B1329] border border-slate-800 shadow-2xs space-y-1.5">
              <div className="flex items-center justify-between">
                <div className="w-16 h-2 rounded bg-slate-700" />
                <div className="w-8 h-2 rounded bg-blue-500" />
              </div>
              <div className="w-28 h-3 rounded bg-white font-bold" />
              <div className="grid grid-cols-3 gap-1 pt-1">
                <div className="h-4 rounded bg-[#111C38] border border-slate-800" />
                <div className="h-4 rounded bg-[#111C38] border border-slate-800" />
                <div className="h-4 rounded bg-emerald-950/60 border border-emerald-800" />
              </div>
            </div>
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left 2 Cols: Form */}
        <div className="lg:col-span-2 space-y-6">
          <form onSubmit={handleSave} className="space-y-6">
            {/* Institution Profile */}
            <div className="p-5 bg-white dark:bg-[#111C38] border border-slate-200/90 dark:border-[#1E2D5A] rounded-2xl space-y-4 shadow-2xs">
              <div className="flex items-center gap-2 border-b border-slate-100 dark:border-[#1E2D5A] pb-3">
                <Building className="w-4 h-4 text-blue-600 dark:text-blue-400" />
                <h3 className="text-sm font-bold text-slate-900 dark:text-white">Institution Profile</h3>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs">
                <div>
                  <label className="block text-slate-700 dark:text-slate-300 font-medium mb-1">Company / Branch Name</label>
                  <input
                    type="text"
                    value={form.companyName}
                    onChange={(e) => setForm({ ...form, companyName: e.target.value })}
                    className="w-full px-3 py-2 bg-slate-50 dark:bg-[#162244] border border-slate-200 dark:border-[#1E2D5A] rounded-xl text-slate-900 dark:text-white focus:outline-hidden focus:border-blue-500 focus:bg-white dark:focus:bg-[#162244] transition-colors"
                  />
                </div>
                <div>
                  <label className="block text-slate-700 dark:text-slate-300 font-medium mb-1">Currency Code / Symbol</label>
                  <input
                    type="text"
                    value={form.currency}
                    onChange={(e) => setForm({ ...form, currency: e.target.value })}
                    className="w-full px-3 py-2 bg-slate-50 dark:bg-[#162244] border border-slate-200 dark:border-[#1E2D5A] rounded-xl text-slate-900 dark:text-white font-mono focus:outline-hidden focus:border-blue-500 focus:bg-white dark:focus:bg-[#162244] transition-colors"
                  />
                </div>
              </div>
            </div>

            {/* Default Loan Product Parameters */}
            <div className="p-5 bg-white dark:bg-[#111C38] border border-slate-200/90 dark:border-[#1E2D5A] rounded-2xl space-y-4 shadow-2xs">
              <div className="flex items-center gap-2 border-b border-slate-100 dark:border-[#1E2D5A] pb-3">
                <Settings className="w-4 h-4 text-indigo-600 dark:text-indigo-400" />
                <h3 className="text-sm font-bold text-slate-900 dark:text-white">Default Lending &amp; Policy Rules</h3>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs">
                <div>
                  <label className="block text-slate-700 dark:text-slate-300 font-medium mb-1">
                    Default Monthly Interest Rate (%)
                  </label>
                  <input
                    type="number"
                    step="0.1"
                    value={form.defaultInterestRate}
                    onChange={(e) =>
                      setForm({ ...form, defaultInterestRate: parseFloat(e.target.value) || 0 })
                    }
                    className="w-full px-3 py-2 bg-slate-50 dark:bg-[#162244] border border-slate-200 dark:border-[#1E2D5A] rounded-xl text-slate-900 dark:text-white font-bold focus:outline-hidden focus:border-blue-500 focus:bg-white dark:focus:bg-[#162244] transition-colors"
                  />
                </div>

                <div>
                  <label className="block text-slate-700 dark:text-slate-300 font-medium mb-1">
                    Default Penalty Rate on Arrears (%)
                  </label>
                  <input
                    type="number"
                    step="0.1"
                    value={form.defaultPenaltyRate}
                    onChange={(e) =>
                      setForm({ ...form, defaultPenaltyRate: parseFloat(e.target.value) || 0 })
                    }
                    className="w-full px-3 py-2 bg-slate-50 dark:bg-[#162244] border border-slate-200 dark:border-[#1E2D5A] rounded-xl text-slate-900 dark:text-white font-bold focus:outline-hidden focus:border-blue-500 focus:bg-white dark:focus:bg-[#162244] transition-colors"
                  />
                </div>

                <div>
                  <label className="block text-slate-700 dark:text-slate-300 font-medium mb-1">
                    Grace Period for Arrears (Days)
                  </label>
                  <input
                    type="number"
                    value={form.gracePeriodDays}
                    onChange={(e) =>
                      setForm({ ...form, gracePeriodDays: parseInt(e.target.value, 10) || 0 })
                    }
                    className="w-full px-3 py-2 bg-slate-50 dark:bg-[#162244] border border-slate-200 dark:border-[#1E2D5A] rounded-xl text-slate-900 dark:text-white font-mono focus:outline-hidden focus:border-blue-500 focus:bg-white dark:focus:bg-[#162244] transition-colors"
                  />
                </div>

                <div>
                  <label className="block text-slate-700 dark:text-slate-300 font-medium mb-1">
                    Standard Upfront Processing Fee (%)
                  </label>
                  <input
                    type="number"
                    step="0.1"
                    value={form.loanProcessingFeeRate}
                    onChange={(e) =>
                      setForm({ ...form, loanProcessingFeeRate: parseFloat(e.target.value) || 0 })
                    }
                    className="w-full px-3 py-2 bg-slate-50 dark:bg-[#162244] border border-slate-200 dark:border-[#1E2D5A] rounded-xl text-slate-900 dark:text-white font-bold focus:outline-hidden focus:border-blue-500 focus:bg-white dark:focus:bg-[#162244] transition-colors"
                  />
                </div>
              </div>
            </div>
          </form>
        </div>

        {/* Right Col: Backup, Restore & Maintenance */}
        <div className="space-y-6">
          {/* Relational Database & Turso Cloud */}
          <div className="p-5 bg-white dark:bg-[#111C38] border border-slate-200/90 dark:border-[#1E2D5A] rounded-2xl space-y-4 shadow-2xs">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-bold text-slate-900 dark:text-white flex items-center gap-2">
                <Database className="w-4 h-4 text-blue-600 dark:text-blue-400" />
                Relational Database
              </h3>
              {tursoInfo?.configured ? (
                <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-emerald-50 dark:bg-emerald-950/60 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800 flex items-center gap-1">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
                  Turso Active
                </span>
              ) : (
                <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-blue-50 dark:bg-blue-950/60 text-blue-700 dark:text-blue-300 border border-blue-200 dark:border-blue-800">
                  SQLite Local
                </span>
              )}
            </div>

            <p className="text-xs text-slate-500 dark:text-slate-400 leading-relaxed">
              {tursoInfo?.configured
                ? `Connected to remote Turso database at ${tursoInfo.maskedUrl}. All team members share live data.`
                : 'Running on local SQLite WebAssembly engine. Ready to connect to free Turso Cloud for multi-user internet access.'}
            </p>

            <button
              type="button"
              onClick={() => onNavigate?.('sqlite')}
              className="w-full flex items-center justify-center gap-2 px-3 py-2.5 bg-indigo-600 hover:bg-indigo-500 text-white rounded-xl text-xs font-semibold transition-colors shadow-xs"
            >
              <Cloud className="w-4 h-4" />
              Open SQLite &amp; Turso Studio
            </button>
          </div>

          {/* Data Backup & Restore */}
          <div className="p-5 bg-white dark:bg-[#111C38] border border-slate-200/90 dark:border-[#1E2D5A] rounded-2xl space-y-4 shadow-2xs">
            <h3 className="text-sm font-bold text-slate-900 dark:text-white">Database Backup &amp; Portability</h3>
            <p className="text-xs text-slate-500 dark:text-slate-400 leading-relaxed">
              Export the entire system database including client KYC, amortization schedules,
              double-entry ledger, and staff payroll to a portable JSON backup file.
            </p>

            <div className="space-y-3 pt-2">
              <button
                type="button"
                id="btn-export-backup"
                onClick={handleExport}
                className="w-full flex items-center justify-center gap-2 px-3 py-2.5 bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-200 border border-slate-200 dark:border-slate-700 rounded-xl text-xs font-semibold transition-colors"
              >
                <Download className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
                Download JSON Backup
              </button>

              <div>
                <label
                  htmlFor="import-file"
                  className="w-full flex items-center justify-center gap-2 px-3 py-2.5 bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-200 border border-slate-200 dark:border-slate-700 rounded-xl text-xs font-semibold cursor-pointer transition-colors"
                >
                  <Upload className="w-4 h-4 text-blue-600 dark:text-blue-400" />
                  Restore from JSON Backup
                </label>
                <input
                  id="import-file"
                  type="file"
                  accept=".json"
                  onChange={handleImport}
                  className="hidden"
                />
              </div>
            </div>
          </div>

          {/* Dangerous Zone / Reset */}
          <div className="p-5 bg-rose-50/50 dark:bg-[#111C38] border border-rose-200/80 dark:border-rose-900/50 rounded-2xl space-y-3 shadow-2xs">
            <div className="flex items-center gap-2 text-rose-600 dark:text-rose-400">
              <ShieldAlert className="w-4 h-4" />
              <h3 className="text-sm font-bold">Reset Demo Dataset</h3>
            </div>
            <p className="text-xs text-slate-600 dark:text-slate-400 leading-relaxed">
              Replaces existing state with the official initial demonstration database containing
              pre-seeded borrowers, loans, journal vouchers, and payroll entries.
            </p>
            <button
              type="button"
              id="btn-reset-demo"
              onClick={handleReset}
              className="w-full flex items-center justify-center gap-2 px-3 py-2 bg-rose-100 hover:bg-rose-200 dark:bg-rose-950/60 dark:hover:bg-rose-900 text-rose-700 dark:text-rose-300 border border-rose-300 dark:border-rose-800 rounded-xl text-xs font-semibold transition-colors"
            >
              <RefreshCw className="w-3.5 h-3.5" />
              Reset to Factory Seed
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

