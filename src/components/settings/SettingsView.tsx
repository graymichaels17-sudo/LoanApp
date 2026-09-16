import React, { useState } from 'react';
import {
  Settings,
  Save,
  Download,
  Upload,
  RefreshCw,
  ShieldAlert,
  CheckCircle2,
  Building,
} from 'lucide-react';
import { useApp } from '../../context/AppContext';
import { Header } from '../common/Header';

export const SettingsView: React.FC = () => {
  const {
    settings,
    updateSettings,
    exportDatabaseJSON,
    importDatabaseJSON,
    resetToInitialSeed,
    systemDate,
  } = useApp();

  const [form, setForm] = useState({ ...settings });
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [importStatus, setImportStatus] = useState<string | null>(null);

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
        title="System Configuration & Data Backup"
        subtitle="Manage institution profile, default lending parameters, penalties, and JSON data exports"
        actions={
          <button
            id="btn-save-settings"
            onClick={handleSave}
            className="flex items-center gap-1.5 px-3 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-xs font-semibold shadow-xs transition-colors"
          >
            <Save className="w-4 h-4" />
            Save Configuration
          </button>
        }
      />

      {saveSuccess && (
        <div className="p-3 bg-emerald-950/40 border border-emerald-800 rounded-xl text-xs text-emerald-300 flex items-center gap-2">
          <CheckCircle2 className="w-4 h-4 text-emerald-400" />
          System lending rules and institutional configuration updated successfully.
        </div>
      )}

      {importStatus && (
        <div className="p-3 bg-blue-950/40 border border-blue-800 rounded-xl text-xs text-blue-300 flex items-center gap-2">
          <CheckCircle2 className="w-4 h-4 text-blue-400" />
          {importStatus}
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left 2 Cols: Form */}
        <div className="lg:col-span-2 space-y-6">
          <form onSubmit={handleSave} className="space-y-6">
            {/* Institution Profile */}
            <div className="p-5 bg-[#111C38] border border-[#1E2D5A] rounded-xl space-y-4">
              <div className="flex items-center gap-2 border-b border-[#1E2D5A] pb-3">
                <Building className="w-4 h-4 text-blue-400" />
                <h3 className="text-sm font-bold text-white">Institution Profile</h3>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs">
                <div>
                  <label className="block text-slate-300 font-medium mb-1">Company / Branch Name</label>
                  <input
                    type="text"
                    value={form.companyName}
                    onChange={(e) => setForm({ ...form, companyName: e.target.value })}
                    className="w-full px-3 py-2 bg-[#162244] border border-[#1E2D5A] rounded-lg text-white focus:outline-hidden focus:border-blue-500"
                  />
                </div>
                <div>
                  <label className="block text-slate-300 font-medium mb-1">Currency Code / Symbol</label>
                  <input
                    type="text"
                    value={form.currency}
                    onChange={(e) => setForm({ ...form, currency: e.target.value })}
                    className="w-full px-3 py-2 bg-[#162244] border border-[#1E2D5A] rounded-lg text-white font-mono focus:outline-hidden focus:border-blue-500"
                  />
                </div>
              </div>
            </div>

            {/* Default Loan Product Parameters */}
            <div className="p-5 bg-[#111C38] border border-[#1E2D5A] rounded-xl space-y-4">
              <div className="flex items-center gap-2 border-b border-[#1E2D5A] pb-3">
                <Settings className="w-4 h-4 text-indigo-400" />
                <h3 className="text-sm font-bold text-white">Default Lending &amp; Policy Rules</h3>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs">
                <div>
                  <label className="block text-slate-300 font-medium mb-1">
                    Default Monthly Interest Rate (%)
                  </label>
                  <input
                    type="number"
                    step="0.1"
                    value={form.defaultInterestRate}
                    onChange={(e) =>
                      setForm({ ...form, defaultInterestRate: parseFloat(e.target.value) || 0 })
                    }
                    className="w-full px-3 py-2 bg-[#162244] border border-[#1E2D5A] rounded-lg text-white font-bold focus:outline-hidden focus:border-blue-500"
                  />
                </div>

                <div>
                  <label className="block text-slate-300 font-medium mb-1">
                    Default Penalty Rate on Arrears (%)
                  </label>
                  <input
                    type="number"
                    step="0.1"
                    value={form.defaultPenaltyRate}
                    onChange={(e) =>
                      setForm({ ...form, defaultPenaltyRate: parseFloat(e.target.value) || 0 })
                    }
                    className="w-full px-3 py-2 bg-[#162244] border border-[#1E2D5A] rounded-lg text-white font-bold focus:outline-hidden focus:border-blue-500"
                  />
                </div>

                <div>
                  <label className="block text-slate-300 font-medium mb-1">
                    Grace Period for Arrears (Days)
                  </label>
                  <input
                    type="number"
                    value={form.gracePeriodDays}
                    onChange={(e) =>
                      setForm({ ...form, gracePeriodDays: parseInt(e.target.value, 10) || 0 })
                    }
                    className="w-full px-3 py-2 bg-[#162244] border border-[#1E2D5A] rounded-lg text-white font-mono focus:outline-hidden focus:border-blue-500"
                  />
                </div>

                <div>
                  <label className="block text-slate-300 font-medium mb-1">
                    Standard Upfront Processing Fee (%)
                  </label>
                  <input
                    type="number"
                    step="0.1"
                    value={form.loanProcessingFeeRate}
                    onChange={(e) =>
                      setForm({ ...form, loanProcessingFeeRate: parseFloat(e.target.value) || 0 })
                    }
                    className="w-full px-3 py-2 bg-[#162244] border border-[#1E2D5A] rounded-lg text-white font-bold focus:outline-hidden focus:border-blue-500"
                  />
                </div>
              </div>
            </div>
          </form>
        </div>

        {/* Right Col: Backup, Restore & Maintenance */}
        <div className="space-y-6">
          {/* Data Backup & Restore */}
          <div className="p-5 bg-[#111C38] border border-[#1E2D5A] rounded-xl space-y-4">
            <h3 className="text-sm font-bold text-white">Database Backup &amp; Portability</h3>
            <p className="text-xs text-slate-400 leading-relaxed">
              Export the entire system database including client KYC, loan amortization schedules,
              double-entry general ledger, and staff payroll to a portable JSON backup file.
            </p>

            <div className="space-y-3 pt-2">
              <button
                type="button"
                id="btn-export-backup"
                onClick={handleExport}
                className="w-full flex items-center justify-center gap-2 px-3 py-2.5 bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 rounded-lg text-xs font-semibold transition-colors"
              >
                <Download className="w-4 h-4 text-emerald-400" />
                Download JSON Backup
              </button>

              <div>
                <label
                  htmlFor="import-file"
                  className="w-full flex items-center justify-center gap-2 px-3 py-2.5 bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 rounded-lg text-xs font-semibold cursor-pointer transition-colors"
                >
                  <Upload className="w-4 h-4 text-blue-400" />
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
          <div className="p-5 bg-[#111C38] border border-rose-900/50 rounded-xl space-y-3">
            <div className="flex items-center gap-2 text-rose-400">
              <ShieldAlert className="w-4 h-4" />
              <h3 className="text-sm font-bold">Reset Demo Dataset</h3>
            </div>
            <p className="text-xs text-slate-400 leading-relaxed">
              Replaces existing state with the official initial demonstration database containing
              pre-seeded borrowers, loans, journal vouchers, and payroll entries.
            </p>
            <button
              type="button"
              id="btn-reset-demo"
              onClick={handleReset}
              className="w-full flex items-center justify-center gap-2 px-3 py-2 bg-rose-950/60 hover:bg-rose-900 text-rose-300 border border-rose-800 rounded-lg text-xs font-semibold transition-colors"
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
