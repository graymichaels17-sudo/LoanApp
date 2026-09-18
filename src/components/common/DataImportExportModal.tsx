import React, { useState } from 'react';
import {
  FileSpreadsheet,
  FileText,
  Upload,
  Download,
  CheckCircle2,
  FileDown,
  Users,
  Coins,
  ArrowDownLeft,
  Banknote,
  Database,
  ArrowRight,
} from 'lucide-react';
import { useApp } from '../../context/AppContext';
import { Modal } from './Modal';
import {
  exportClientsToExcel,
  exportClientsToPDF,
  exportLoansToExcel,
  exportLoansToPDF,
  exportFullDatabaseToExcel,
  readExcelFile,
  parseClientsFromExcel,
  parseLoansFromExcel,
  downloadClientsExcelTemplate,
  downloadLoansExcelTemplate,
  downloadExcelWorkbook,
  downloadPDFReport,
  ParsedClientsResult,
  ParsedLoansResult,
} from '../../utils/exportImport';
import { formatMoney } from '../../utils/money';

interface DataImportExportModalProps {
  isOpen: boolean;
  onClose: () => void;
  initialTab?: 'export' | 'import';
  initialSection?: 'clients' | 'loans' | 'reports' | 'all';
}

export const DataImportExportModal: React.FC<DataImportExportModalProps> = ({
  isOpen,
  onClose,
  initialTab = 'export',
  initialSection = 'clients',
}) => {
  const {
    clients,
    loans,
    disbursements,
    repayments,
    accounts,
    journalEntries,
    settings,
    systemDate,
    bulkImportClients,
    bulkImportLoans,
  } = useApp();

  const [activeTab, setActiveTab] = useState<'export' | 'import'>(initialTab);
  const [selectedDataset, setSelectedDataset] = useState<'clients' | 'loans' | 'disbursements' | 'repayments' | 'all'>(
    initialSection === 'loans' ? 'loans' : initialSection === 'all' ? 'all' : 'clients'
  );
  const [exportFormat, setExportFormat] = useState<'excel' | 'pdf'>('excel');

  // Import State
  const [importTarget, setImportTarget] = useState<'clients' | 'loans'>('clients');
  const [importedFile, setImportedFile] = useState<File | null>(null);
  const [isParsing, setIsParsing] = useState(false);
  const [clientParseResult, setClientParseResult] = useState<ParsedClientsResult | null>(null);
  const [loanParseResult, setLoanParseResult] = useState<ParsedLoansResult | null>(null);
  const [importSuccessMessage, setImportSuccessMessage] = useState<string | null>(null);

  // -------------------------------------------------------------------------
  // EXPORT HANDLER
  // -------------------------------------------------------------------------
  const handleExecuteExport = () => {
    if (exportFormat === 'excel') {
      if (selectedDataset === 'all') {
        exportFullDatabaseToExcel({
          clients,
          loans,
          disbursements,
          repayments,
          accounts,
          journalEntries,
        });
      } else if (selectedDataset === 'clients') {
        exportClientsToExcel(clients, loans);
      } else if (selectedDataset === 'loans') {
        exportLoansToExcel(loans, clients);
      } else if (selectedDataset === 'disbursements') {
        const data = disbursements.map((d) => {
          const l = loans.find((item) => item.id === d.loanId);
          const c = l ? clients.find((client) => client.id === l.clientId) : null;
          return {
            'Disbursement Date': d.disbursementDate,
            'Loan #': l?.loanNo || d.loanId,
            'Borrower': c ? `${c.firstName} ${c.lastName}` : '-',
            'Amount': d.amount,
            'Method': d.method,
            'Reference': d.reference || '-',
            'Notes': d.notes || '-',
          };
        });
        downloadExcelWorkbook(`disbursements_${systemDate}`, [{ name: 'Disbursements Register', data }]);
      } else if (selectedDataset === 'repayments') {
        const data = repayments.map((r) => {
          const l = loans.find((item) => item.id === r.loanId);
          const c = l ? clients.find((client) => client.id === l.clientId) : null;
          return {
            'Payment Date': r.paymentDate,
            'Loan #': l?.loanNo || r.loanId,
            'Borrower': c ? `${c.firstName} ${c.lastName}` : '-',
            'Total Received': r.amount,
            'Principal Component': r.principalPaid,
            'Interest Component': r.interestPaid,
            'Penalty Component': r.penaltyPaid,
            'Method': r.method,
            'Reference': r.reference || '-',
          };
        });
        downloadExcelWorkbook(`repayments_${systemDate}`, [{ name: 'Repayments Register', data }]);
      }
    } else {
      // PDF Export
      if (selectedDataset === 'all') {
        // Institutional Executive Summary
        const columns = ['Metric / Component', 'Portfolio Figures', 'Operational Detail'];
        const totalPrincipal = loans.reduce((s, l) => s + l.principal, 0);
        const totalRepaid = repayments.reduce((s, r) => s + r.amount, 0);
        const rows = [
          ['Total Registered Clients', clients.length.toString(), `${clients.filter((c) => c.status === 'Active').length} Active`],
          ['Cumulative Loan Portfolio', formatMoney(totalPrincipal), `${loans.length} Total Loans Originated`],
          ['Active Portfolio at Risk', loans.filter((l) => l.status === 'Active').length.toString(), 'Current Performing & Monitored'],
          ['Total Repayments Collected', formatMoney(totalRepaid), `${repayments.length} Transaction Receipts`],
          ['Total Disbursements Volume', formatMoney(disbursements.reduce((s, d) => s + d.amount, 0)), `${disbursements.length} Disbursed Accounts`],
        ];
        downloadPDFReport({
          title: 'Executive Institutional Portfolio Report',
          subtitle: `Comprehensive institutional overview of ${settings.companyName}`,
          companyName: settings.companyName,
          systemDate,
          filename: `executive_portfolio_summary_${systemDate}.pdf`,
          columns,
          rows,
          summaryCards: [
            { label: 'Total Borrowers', value: clients.length.toString() },
            { label: 'Portfolio Volume', value: formatMoney(totalPrincipal) },
            { label: 'Total Collections', value: formatMoney(totalRepaid) },
          ],
        });
      } else if (selectedDataset === 'clients') {
        exportClientsToPDF(clients, settings, systemDate);
      } else if (selectedDataset === 'loans') {
        exportLoansToPDF(loans, clients, settings, systemDate);
      } else if (selectedDataset === 'disbursements') {
        const columns = ['Date', 'Loan #', 'Borrower', 'Disbursed Amount', 'Method', 'Reference'];
        const rows = disbursements.map((d) => {
          const l = loans.find((item) => item.id === d.loanId);
          const c = l ? clients.find((client) => client.id === l.clientId) : null;
          return [
            d.disbursementDate,
            l?.loanNo || d.loanId.toString(),
            c ? `${c.firstName} ${c.lastName}` : '-',
            formatMoney(d.amount),
            d.method,
            d.reference || '-',
          ];
        });
        downloadPDFReport({
          title: 'Loan Disbursements Register',
          subtitle: `Audited listing of ${disbursements.length} institutional disbursements`,
          companyName: settings.companyName,
          systemDate,
          filename: `disbursements_register_${systemDate}.pdf`,
          columns,
          rows,
        });
      } else if (selectedDataset === 'repayments') {
        const columns = ['Date', 'Loan #', 'Borrower', 'Total Paid', 'Principal', 'Interest', 'Method'];
        const rows = repayments.map((r) => {
          const l = loans.find((item) => item.id === r.loanId);
          const c = l ? clients.find((client) => client.id === l.clientId) : null;
          return [
            r.paymentDate,
            l?.loanNo || r.loanId.toString(),
            c ? `${c.firstName} ${c.lastName}` : '-',
            formatMoney(r.amount),
            formatMoney(r.principalPaid),
            formatMoney(r.interestPaid),
            r.method,
          ];
        });
        downloadPDFReport({
          title: 'Loan Collections & Repayments Register',
          subtitle: `Verified listing of ${repayments.length} repayment transactions`,
          companyName: settings.companyName,
          systemDate,
          filename: `repayments_register_${systemDate}.pdf`,
          columns,
          rows,
        });
      }
    }
  };

  // -------------------------------------------------------------------------
  // IMPORT FILE PARSING
  // -------------------------------------------------------------------------
  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setImportedFile(file);
    setIsParsing(true);
    setImportSuccessMessage(null);
    setClientParseResult(null);
    setLoanParseResult(null);

    try {
      const sheetsData = await readExcelFile(file);
      const firstSheetName = Object.keys(sheetsData)[0];
      const rows = sheetsData[firstSheetName] || [];

      if (importTarget === 'clients') {
        const result = parseClientsFromExcel(rows);
        setClientParseResult(result);
      } else {
        const result = parseLoansFromExcel(rows, clients);
        setLoanParseResult(result);
      }
    } catch (err: any) {
      alert(`Error reading file: ${err.message || 'Invalid format'}`);
    } finally {
      setIsParsing(false);
    }
  };

  const handleExecuteImport = () => {
    if (importTarget === 'clients' && clientParseResult && clientParseResult.valid.length > 0) {
      const count = bulkImportClients(clientParseResult.valid);
      setImportSuccessMessage(`Successfully imported ${count} new clients into the database.`);
      setClientParseResult(null);
      setImportedFile(null);
    } else if (importTarget === 'loans' && loanParseResult && loanParseResult.valid.length > 0) {
      const count = bulkImportLoans(loanParseResult.valid);
      setImportSuccessMessage(`Successfully imported ${count} new loan applications into the portfolio.`);
      setLoanParseResult(null);
      setImportedFile(null);
    }
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title="Data Center: Import & Export"
      maxWidth="4xl"
    >
      <div className="space-y-6 text-xs text-slate-700 dark:text-slate-300">
        {/* Navigation Tabs */}
        <div className="flex items-center gap-2 border-b border-slate-200 dark:border-slate-800 pb-3">
          <button
            onClick={() => setActiveTab('export')}
            className={`flex items-center gap-2 px-4 py-2 rounded-xl font-bold transition-all text-xs ${
              activeTab === 'export'
                ? 'bg-blue-600 text-white shadow-xs'
                : 'bg-slate-100 dark:bg-slate-800/80 text-slate-600 dark:text-slate-300 hover:bg-slate-200'
            }`}
          >
            <Download className="w-4 h-4" />
            <span>Export Data (Excel & PDF)</span>
          </button>

          <button
            onClick={() => setActiveTab('import')}
            className={`flex items-center gap-2 px-4 py-2 rounded-xl font-bold transition-all text-xs ${
              activeTab === 'import'
                ? 'bg-blue-600 text-white shadow-xs'
                : 'bg-slate-100 dark:bg-slate-800/80 text-slate-600 dark:text-slate-300 hover:bg-slate-200'
            }`}
          >
            <Upload className="w-4 h-4" />
            <span>Import from Excel (.xlsx / .csv)</span>
          </button>
        </div>

        {/* ----------------------------------------------------------------- */}
        {/* TAB 1: EXPORT VIEW */}
        {/* ----------------------------------------------------------------- */}
        {activeTab === 'export' && (
          <div className="space-y-5">
            {/* Step 1: Choose Dataset */}
            <div className="space-y-2">
              <label className="font-bold text-slate-900 dark:text-white uppercase tracking-wider text-[11px]">
                1. Select Dataset to Export
              </label>

              <div className="grid grid-cols-2 sm:grid-cols-3 gap-2.5">
                {[
                  { id: 'clients', label: 'Clients Registry', count: `${clients.length} borrowers`, icon: Users },
                  { id: 'loans', label: 'Loans & Portfolio', count: `${loans.length} loans`, icon: Coins },
                  { id: 'disbursements', label: 'Disbursements', count: `${disbursements.length} records`, icon: Banknote },
                  { id: 'repayments', label: 'Repayments Register', count: `${repayments.length} receipts`, icon: ArrowDownLeft },
                  { id: 'all', label: 'Full System Backup', count: 'Multi-sheet complete', icon: Database },
                ].map((item) => {
                  const Icon = item.icon;
                  const isSelected = selectedDataset === item.id;
                  return (
                    <button
                      key={item.id}
                      onClick={() => setSelectedDataset(item.id as any)}
                      className={`p-3 rounded-xl border text-left flex flex-col gap-1.5 transition-all ${
                        isSelected
                          ? 'bg-blue-50 dark:bg-blue-950/40 border-blue-500 text-blue-900 dark:text-blue-100 shadow-2xs'
                          : 'bg-white dark:bg-[#111C38] border-slate-200 dark:border-[#1E2D5A] hover:border-slate-300'
                      }`}
                    >
                      <div className="flex items-center justify-between">
                        <Icon className={`w-4 h-4 ${isSelected ? 'text-blue-600 dark:text-blue-400' : 'text-slate-400'}`} />
                        <span className="text-[10px] text-slate-400">{item.count}</span>
                      </div>
                      <span className="font-bold text-xs">{item.label}</span>
                    </button>
                  );
                })}
              </div>
            </div>

            {/* Step 2: Choose File Format */}
            <div className="space-y-2">
              <label className="font-bold text-slate-900 dark:text-white uppercase tracking-wider text-[11px]">
                2. Select Export Format
              </label>

              <div className="grid grid-cols-2 gap-3">
                <button
                  onClick={() => setExportFormat('excel')}
                  className={`p-3.5 rounded-xl border flex items-center gap-3 transition-all ${
                    exportFormat === 'excel'
                      ? 'bg-emerald-50 dark:bg-emerald-950/40 border-emerald-500 text-emerald-950 dark:text-emerald-100 shadow-2xs'
                      : 'bg-white dark:bg-[#111C38] border-slate-200 dark:border-[#1E2D5A] hover:border-slate-300'
                  }`}
                >
                  <div className="w-10 h-10 rounded-lg bg-emerald-600 text-white flex items-center justify-center shrink-0">
                    <FileSpreadsheet className="w-5 h-5" />
                  </div>
                  <div className="text-left">
                    <span className="font-bold text-sm block">Microsoft Excel (.xlsx)</span>
                    <span className="text-[11px] text-slate-500 dark:text-slate-400">
                      Editable spreadsheet with auto-fitted columns and headers
                    </span>
                  </div>
                </button>

                <button
                  onClick={() => setExportFormat('pdf')}
                  className={`p-3.5 rounded-xl border flex items-center gap-3 transition-all ${
                    exportFormat === 'pdf'
                      ? 'bg-red-50 dark:bg-red-950/40 border-red-500 text-red-950 dark:text-red-100 shadow-2xs'
                      : 'bg-white dark:bg-[#111C38] border-slate-200 dark:border-[#1E2D5A] hover:border-slate-300'
                  }`}
                >
                  <div className="w-10 h-10 rounded-lg bg-red-600 text-white flex items-center justify-center shrink-0">
                    <FileText className="w-5 h-5" />
                  </div>
                  <div className="text-left">
                    <span className="font-bold text-sm block">PDF Document (.pdf)</span>
                    <span className="text-[11px] text-slate-500 dark:text-slate-400">
                      Institutional printable layout with company letterhead & styling
                    </span>
                  </div>
                </button>
              </div>
            </div>

            {/* Action Card */}
            <div className="p-4 bg-slate-50 dark:bg-slate-900/60 border border-slate-200 dark:border-slate-800 rounded-xl flex items-center justify-between">
              <div>
                <span className="font-bold text-slate-900 dark:text-white block">Ready to Generate Download</span>
                <span className="text-[11px] text-slate-500 dark:text-slate-400">
                  Exporting {selectedDataset} as {exportFormat.toUpperCase()} with active system date ({systemDate})
                </span>
              </div>

              <button
                onClick={handleExecuteExport}
                className="flex items-center gap-2 px-5 py-2.5 bg-blue-600 hover:bg-blue-500 text-white rounded-xl font-bold shadow-xs transition-colors"
              >
                <Download className="w-4 h-4" />
                <span>Download {exportFormat.toUpperCase()}</span>
              </button>
            </div>
          </div>
        )}

        {/* ----------------------------------------------------------------- */}
        {/* TAB 2: IMPORT VIEW */}
        {/* ----------------------------------------------------------------- */}
        {activeTab === 'import' && (
          <div className="space-y-5">
            {/* Success Banner */}
            {importSuccessMessage && (
              <div className="p-3.5 bg-emerald-50 dark:bg-emerald-950/40 border border-emerald-300 dark:border-emerald-800 rounded-xl flex items-center gap-2.5 text-emerald-800 dark:text-emerald-200 font-semibold">
                <CheckCircle2 className="w-5 h-5 text-emerald-600 shrink-0" />
                <span>{importSuccessMessage}</span>
              </div>
            )}

            {/* Step 1: Target entity & Template download */}
            <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 p-3.5 bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl">
              <div>
                <span className="font-bold text-slate-900 dark:text-white block">1. What are you importing?</span>
                <div className="flex items-center gap-4 mt-1.5">
                  <label className="flex items-center gap-2 cursor-pointer font-medium">
                    <input
                      type="radio"
                      name="importTarget"
                      checked={importTarget === 'clients'}
                      onChange={() => {
                        setImportTarget('clients');
                        setClientParseResult(null);
                        setLoanParseResult(null);
                        setImportedFile(null);
                      }}
                      className="text-blue-600"
                    />
                    <span>Borrower Clients Registry</span>
                  </label>

                  <label className="flex items-center gap-2 cursor-pointer font-medium">
                    <input
                      type="radio"
                      name="importTarget"
                      checked={importTarget === 'loans'}
                      onChange={() => {
                        setImportTarget('loans');
                        setClientParseResult(null);
                        setLoanParseResult(null);
                        setImportedFile(null);
                      }}
                      className="text-blue-600"
                    />
                    <span>Loan Applications</span>
                  </label>
                </div>
              </div>

              {/* Download Template Button */}
              <button
                onClick={() => {
                  if (importTarget === 'clients') downloadClientsExcelTemplate();
                  else downloadLoansExcelTemplate(clients);
                }}
                className="flex items-center gap-1.5 px-3 py-1.5 bg-white dark:bg-slate-800 border border-slate-300 dark:border-slate-700 rounded-lg text-slate-700 dark:text-slate-200 font-semibold hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors shadow-2xs"
              >
                <FileDown className="w-4 h-4 text-emerald-600" />
                <span>Download Sample Excel Template</span>
              </button>
            </div>

            {/* Step 2: Upload Excel File */}
            <div className="space-y-2">
              <label className="font-bold text-slate-900 dark:text-white uppercase tracking-wider text-[11px]">
                2. Upload Excel / CSV File
              </label>

              <label className="border-2 border-dashed border-slate-300 dark:border-slate-700 hover:border-blue-500 dark:hover:border-blue-500 rounded-2xl p-6 flex flex-col items-center justify-center gap-2 cursor-pointer bg-slate-50/50 dark:bg-slate-900/40 transition-colors">
                <Upload className="w-8 h-8 text-blue-500" />
                <span className="font-bold text-slate-800 dark:text-slate-200">
                  {importedFile ? importedFile.name : 'Click to select or drag and drop Excel workbook'}
                </span>
                <span className="text-[11px] text-slate-400">Supports .xlsx, .xls, and .csv files</span>
                <input
                  type="file"
                  accept=".xlsx, .xls, .csv"
                  onChange={handleFileChange}
                  className="hidden"
                />
              </label>
            </div>

            {/* Step 3: Parsed Results Preview */}
            {isParsing && (
              <div className="p-4 text-center text-slate-500 dark:text-slate-400">
                <span className="animate-pulse">Parsing and validating spreadsheet rows...</span>
              </div>
            )}

            {clientParseResult && (
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <CheckCircle2 className="w-4 h-4 text-emerald-500" />
                    <span className="font-bold text-slate-900 dark:text-white">
                      {clientParseResult.valid.length} Valid Clients Ready to Import
                    </span>
                    {clientParseResult.errors.length > 0 && (
                      <span className="px-2 py-0.5 rounded bg-red-100 dark:bg-red-950 text-red-700 dark:text-red-300 font-semibold text-[10px]">
                        {clientParseResult.errors.length} Rows with Errors
                      </span>
                    )}
                  </div>

                  <button
                    disabled={clientParseResult.valid.length === 0}
                    onClick={handleExecuteImport}
                    className="flex items-center gap-1.5 px-4 py-2 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white rounded-xl font-bold shadow-xs transition-colors"
                  >
                    <span>Import {clientParseResult.valid.length} Clients</span>
                    <ArrowRight className="w-4 h-4" />
                  </button>
                </div>

                {/* Preview Table */}
                <div className="max-h-48 overflow-y-auto border border-slate-200 dark:border-slate-800 rounded-xl">
                  <table className="w-full text-left text-[11px]">
                    <thead className="bg-slate-100 dark:bg-slate-800 sticky top-0 text-slate-600 dark:text-slate-300 font-bold">
                      <tr>
                        <th className="px-3 py-2">Name</th>
                        <th className="px-3 py-2">National ID</th>
                        <th className="px-3 py-2">Phone</th>
                        <th className="px-3 py-2">Location</th>
                        <th className="px-3 py-2">Occupation</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                      {clientParseResult.valid.slice(0, 10).map((c, idx) => (
                        <tr key={idx} className="hover:bg-slate-50 dark:hover:bg-slate-800/40">
                          <td className="px-3 py-1.5 font-medium">{c.firstName} {c.lastName}</td>
                          <td className="px-3 py-1.5 font-mono">{c.nationalId}</td>
                          <td className="px-3 py-1.5">{c.phone}</td>
                          <td className="px-3 py-1.5">{c.location}</td>
                          <td className="px-3 py-1.5">{c.occupation}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {clientParseResult.valid.length > 10 && (
                    <div className="p-2 text-center text-[10px] text-slate-400 bg-slate-50 dark:bg-slate-900 border-t border-slate-200 dark:border-slate-800">
                      + {clientParseResult.valid.length - 10} more client records
                    </div>
                  )}
                </div>
              </div>
            )}

            {loanParseResult && (
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <CheckCircle2 className="w-4 h-4 text-emerald-500" />
                    <span className="font-bold text-slate-900 dark:text-white">
                      {loanParseResult.valid.length} Valid Loans Ready to Import
                    </span>
                    {loanParseResult.errors.length > 0 && (
                      <span className="px-2 py-0.5 rounded bg-red-100 dark:bg-red-950 text-red-700 dark:text-red-300 font-semibold text-[10px]">
                        {loanParseResult.errors.length} Rows with Errors
                      </span>
                    )}
                  </div>

                  <button
                    disabled={loanParseResult.valid.length === 0}
                    onClick={handleExecuteImport}
                    className="flex items-center gap-1.5 px-4 py-2 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white rounded-xl font-bold shadow-xs transition-colors"
                  >
                    <span>Import {loanParseResult.valid.length} Loans</span>
                    <ArrowRight className="w-4 h-4" />
                  </button>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </Modal>
  );
};
