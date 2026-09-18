import React, { useState, useMemo } from 'react';
import {
  AlertTriangle,
  TrendingUp,
  Layers,
  Coins,
  FileSpreadsheet,
  FileText,
} from 'lucide-react';
import { useApp } from '../../context/AppContext';
import { formatMoney, roundMoney } from '../../utils/money';
import { Header } from '../common/Header';
import { downloadExcelWorkbook, downloadPDFReport } from '../../utils/exportImport';

export const ReportsView: React.FC = () => {
  const { loans, clients, schedules, disbursements, repayments, settings, systemDate } = useApp();

  const [activeReport, setActiveReport] = useState<'par' | 'disbursements' | 'collections' | 'loan_book'>('par');

  // PAR Aging Analysis Calculation
  const parAnalysis = useMemo(() => {
    const today = new Date(systemDate).getTime();

    let current = 0;
    let par1_30 = 0;
    let par31_60 = 0;
    let par61_90 = 0;
    let par90plus = 0;

    // Map each active loan to its overdue days
    const activeLoans = loans.filter((l) => l.status === 'Active');

    const loanRows = activeLoans.map((loan) => {
      const loanSched = schedules.filter((s) => s.loanId === loan.id);
      const unpaidPrincipal = loanSched.reduce((s, i) => s + (i.principalDue - i.principalPaid), 0);
      const unpaidInterest = loanSched.reduce((s, i) => s + (i.interestDue - i.interestPaid), 0);
      const totalOutstanding = unpaidPrincipal + unpaidInterest;

      // Find earliest unpaid overdue installment
      const overdueInst = loanSched.filter(
        (s) => s.status !== 'Paid' && new Date(s.dueDate).getTime() < today
      );

      let maxDaysOverdue = 0;
      if (overdueInst.length > 0) {
        const earliestDueDate = Math.min(...overdueInst.map((i) => new Date(i.dueDate).getTime()));
        maxDaysOverdue = Math.max(0, Math.floor((today - earliestDueDate) / (1000 * 60 * 60 * 24)));
      }

      let bucket = 'Current';
      if (maxDaysOverdue > 90) {
        bucket = 'PAR > 90';
        par90plus += totalOutstanding;
      } else if (maxDaysOverdue > 60) {
        bucket = 'PAR 61-90';
        par61_90 += totalOutstanding;
      } else if (maxDaysOverdue > 30) {
        bucket = 'PAR 31-60';
        par31_60 += totalOutstanding;
      } else if (maxDaysOverdue > 0) {
        bucket = 'PAR 1-30';
        par1_30 += totalOutstanding;
      } else {
        current += totalOutstanding;
      }

      const client = clients.find((c) => c.id === loan.clientId);

      return {
        loanNo: loan.loanNo,
        clientName: client ? `${client.firstName} ${client.lastName}` : `Client #${loan.clientId}`,
        location: client?.location || '-',
        disbursedDate: loan.disbursementDate,
        maturityDate: loan.maturityDate || '-',
        outstandingPrincipal: unpaidPrincipal,
        totalOutstanding,
        daysOverdue: maxDaysOverdue,
        bucket,
      };
    });

    const totalPortfolio = current + par1_30 + par31_60 + par61_90 + par90plus;
    const totalAtRisk = par1_30 + par31_60 + par61_90 + par90plus;

    return {
      current: roundMoney(current),
      par1_30: roundMoney(par1_30),
      par31_60: roundMoney(par31_60),
      par61_90: roundMoney(par61_90),
      par90plus: roundMoney(par90plus),
      totalPortfolio: roundMoney(totalPortfolio),
      totalAtRisk: roundMoney(totalAtRisk),
      parRate: totalPortfolio > 0 ? (totalAtRisk / totalPortfolio) * 100 : 0,
      loans: loanRows,
    };
  }, [loans, schedules, clients, systemDate]);

  // Export Excel Helper
  const handleExportExcel = () => {
    if (activeReport === 'par') {
      const data = parAnalysis.loans.map((row) => ({
        'Loan #': row.loanNo,
        'Borrower': row.clientName,
        'Location': row.location,
        'Disbursed Date': row.disbursedDate,
        'Maturity Date': row.maturityDate,
        'Principal Outstanding': row.outstandingPrincipal,
        'Total Outstanding': row.totalOutstanding,
        'Days Overdue': row.daysOverdue,
        'PAR Bucket': row.bucket,
      }));
      downloadExcelWorkbook(`par_aging_analysis_${systemDate}`, [{ name: 'PAR Aging Analysis', data }]);
    } else if (activeReport === 'disbursements') {
      const data = disbursements.map((d) => {
        const l = loans.find((item) => item.id === d.loanId);
        const c = l ? clients.find((client) => client.id === l.clientId) : null;
        return {
          'Date': d.disbursementDate,
          'Loan #': l?.loanNo || d.loanId,
          'Borrower': c ? `${c.firstName} ${c.lastName}` : '-',
          'Amount': d.amount,
          'Method': d.method,
          'Reference': d.reference || '-',
          'Notes': d.notes || '-',
        };
      });
      downloadExcelWorkbook(`disbursements_register_${systemDate}`, [{ name: 'Disbursements Register', data }]);
    } else if (activeReport === 'collections') {
      const data = repayments.map((r) => {
        const l = loans.find((item) => item.id === r.loanId);
        const c = l ? clients.find((client) => client.id === l.clientId) : null;
        return {
          'Date': r.paymentDate,
          'Loan #': l?.loanNo || r.loanId,
          'Borrower': c ? `${c.firstName} ${c.lastName}` : '-',
          'Total Amount': r.amount,
          'Principal Paid': r.principalPaid,
          'Interest Paid': r.interestPaid,
          'Penalty Paid': r.penaltyPaid,
          'Method': r.method,
          'Reference': r.reference || '-',
        };
      });
      downloadExcelWorkbook(`collections_register_${systemDate}`, [{ name: 'Collections Register', data }]);
    } else {
      const data = loans.map((l) => {
        const c = clients.find((client) => client.id === l.clientId);
        return {
          'Loan #': l.loanNo,
          'Borrower': c ? `${c.firstName} ${c.lastName}` : '-',
          'Principal': l.principal,
          'Method': l.interestMethod,
          'Interest Rate': `${l.interestRate}%`,
          'Term': `${l.termMonths} ${l.repaymentFrequency}`,
          'Status': l.status,
          'Application Date': l.applicationDate,
          'Disbursement Date': l.disbursementDate || '-',
        };
      });
      downloadExcelWorkbook(`loan_book_${systemDate}`, [{ name: 'Comprehensive Loan Book', data }]);
    }
  };

  // Export PDF Helper
  const handleExportPDF = () => {
    if (activeReport === 'par') {
      const columns = ['Loan #', 'Borrower', 'Location', 'Principal O/S', 'Total O/S', 'Days', 'PAR Bucket'];
      const rows = parAnalysis.loans.map((r) => [
        r.loanNo,
        r.clientName,
        r.location,
        formatMoney(r.outstandingPrincipal),
        formatMoney(r.totalOutstanding),
        r.daysOverdue.toString(),
        r.bucket,
      ]);
      downloadPDFReport({
        title: 'Portfolio at Risk (PAR) Aging Analysis',
        subtitle: `Audited PAR position as of system date ${systemDate}`,
        companyName: settings.companyName,
        systemDate,
        filename: `par_aging_analysis_${systemDate}.pdf`,
        columns,
        rows,
        summaryCards: [
          { label: 'Total Portfolio', value: formatMoney(parAnalysis.totalPortfolio) },
          { label: 'Portfolio at Risk', value: formatMoney(parAnalysis.totalAtRisk) },
          { label: 'PAR Rate %', value: `${parAnalysis.parRate.toFixed(2)}%` },
        ],
      });
    } else if (activeReport === 'disbursements') {
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
        subtitle: `Verified listing of ${disbursements.length} disbursements`,
        companyName: settings.companyName,
        systemDate,
        filename: `disbursements_report_${systemDate}.pdf`,
        columns,
        rows,
      });
    } else if (activeReport === 'collections') {
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
        subtitle: `Verified listing of ${repayments.length} collection receipts`,
        companyName: settings.companyName,
        systemDate,
        filename: `collections_report_${systemDate}.pdf`,
        columns,
        rows,
      });
    } else {
      const columns = ['Loan #', 'Borrower', 'Principal', 'Rate', 'Term', 'Status', 'Disbursed'];
      const rows = loans.map((l) => {
        const c = clients.find((client) => client.id === l.clientId);
        return [
          l.loanNo,
          c ? `${c.firstName} ${c.lastName}` : '-',
          formatMoney(l.principal),
          `${l.interestRate}%`,
          `${l.termMonths} mos`,
          l.status,
          l.disbursementDate || '-',
        ];
      });
      downloadPDFReport({
        title: 'Comprehensive Master Loan Book',
        subtitle: `Portfolio registry of ${loans.length} originated loans`,
        companyName: settings.companyName,
        systemDate,
        filename: `loan_book_${systemDate}.pdf`,
        columns,
        rows,
      });
    }
  };

  return (
    <div id="reports-view" className="space-y-6">
      <Header
        title="Portfolio Analytics & Statutory Reports"
        subtitle="Portfolio at Risk (PAR) aging analysis, collection registers, disbursements, and loan book exports"
        actions={
          <div className="flex items-center gap-2">
            <button
              id="btn-export-excel"
              onClick={handleExportExcel}
              className="flex items-center gap-1.5 px-3 py-2 bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg text-xs font-semibold shadow-xs transition-colors"
              title="Download report as formatted Microsoft Excel spreadsheet"
            >
              <FileSpreadsheet className="w-4 h-4" />
              <span>Export Excel</span>
            </button>

            <button
              id="btn-export-pdf"
              onClick={handleExportPDF}
              className="flex items-center gap-1.5 px-3 py-2 bg-red-600 hover:bg-red-500 text-white rounded-lg text-xs font-semibold shadow-xs transition-colors"
              title="Download report as formatted printable PDF document"
            >
              <FileText className="w-4 h-4" />
              <span>Export PDF</span>
            </button>
          </div>
        }
      />

      {/* Report Selector Tabs */}
      <div className="flex items-center gap-2 border-b border-slate-800 pb-2 text-xs font-semibold overflow-x-auto">
        <button
          onClick={() => setActiveReport('par')}
          className={`px-3.5 py-2 rounded-lg flex items-center gap-2 transition-colors ${
            activeReport === 'par'
              ? 'bg-blue-600 text-white'
              : 'text-slate-400 hover:text-white hover:bg-slate-800/60'
          }`}
        >
          <AlertTriangle className="w-4 h-4" />
          Portfolio at Risk (PAR) Aging
        </button>

        <button
          onClick={() => setActiveReport('disbursements')}
          className={`px-3.5 py-2 rounded-lg flex items-center gap-2 transition-colors ${
            activeReport === 'disbursements'
              ? 'bg-blue-600 text-white'
              : 'text-slate-400 hover:text-white hover:bg-slate-800/60'
          }`}
        >
          <Coins className="w-4 h-4" />
          Disbursements Register ({disbursements.length})
        </button>

        <button
          onClick={() => setActiveReport('collections')}
          className={`px-3.5 py-2 rounded-lg flex items-center gap-2 transition-colors ${
            activeReport === 'collections'
              ? 'bg-blue-600 text-white'
              : 'text-slate-400 hover:text-white hover:bg-slate-800/60'
          }`}
        >
          <TrendingUp className="w-4 h-4" />
          Collections & Repayments ({repayments.length})
        </button>

        <button
          onClick={() => setActiveReport('loan_book')}
          className={`px-3.5 py-2 rounded-lg flex items-center gap-2 transition-colors ${
            activeReport === 'loan_book'
              ? 'bg-blue-600 text-white'
              : 'text-slate-400 hover:text-white hover:bg-slate-800/60'
          }`}
        >
          <Layers className="w-4 h-4" />
          Full Loan Book Register ({loans.length})
        </button>
      </div>

      {/* REPORT 1: PAR AGING ANALYSIS */}
      {activeReport === 'par' && (
        <div className="space-y-6">
          {/* Aging Buckets Grid */}
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
            <div className="p-3.5 bg-[#111C38] border border-[#1E2D5A] rounded-xl space-y-1">
              <p className="text-[10px] uppercase font-bold text-emerald-400">Current (0 Days)</p>
              <p className="text-lg font-bold text-white">{formatMoney(parAnalysis.current)}</p>
              <p className="text-[10px] text-slate-400">Performing book</p>
            </div>

            <div className="p-3.5 bg-[#111C38] border border-[#1E2D5A] rounded-xl space-y-1">
              <p className="text-[10px] uppercase font-bold text-amber-400">PAR 1 - 30 Days</p>
              <p className="text-lg font-bold text-white">{formatMoney(parAnalysis.par1_30)}</p>
              <p className="text-[10px] text-slate-400">Early delinquency</p>
            </div>

            <div className="p-3.5 bg-[#111C38] border border-[#1E2D5A] rounded-xl space-y-1">
              <p className="text-[10px] uppercase font-bold text-orange-400">PAR 31 - 60 Days</p>
              <p className="text-lg font-bold text-white">{formatMoney(parAnalysis.par31_60)}</p>
              <p className="text-[10px] text-slate-400">Special watch</p>
            </div>

            <div className="p-3.5 bg-[#111C38] border border-[#1E2D5A] rounded-xl space-y-1">
              <p className="text-[10px] uppercase font-bold text-rose-400">PAR 61 - 90 Days</p>
              <p className="text-lg font-bold text-white">{formatMoney(parAnalysis.par61_90)}</p>
              <p className="text-[10px] text-slate-400">Sub-standard</p>
            </div>

            <div className="p-3.5 bg-[#111C38] border border-[#1E2D5A] rounded-xl space-y-1">
              <p className="text-[10px] uppercase font-bold text-rose-500">PAR &gt; 90 Days</p>
              <p className="text-lg font-bold text-rose-300">{formatMoney(parAnalysis.par90plus)}</p>
              <p className="text-[10px] text-slate-400">Doubtful / NPL</p>
            </div>

            <div className="p-3.5 bg-[#111C38] border border-blue-600/40 rounded-xl space-y-1 bg-blue-950/20">
              <p className="text-[10px] uppercase font-bold text-blue-400">Overall PAR Rate</p>
              <p className="text-lg font-bold text-blue-300">{parAnalysis.parRate.toFixed(1)}%</p>
              <p className="text-[10px] text-slate-400">
                At Risk: {formatMoney(parAnalysis.totalAtRisk)}
              </p>
            </div>
          </div>

          {/* PAR Loans Detail Table */}
          <div className="bg-[#111C38] border border-[#1E2D5A] rounded-xl overflow-hidden">
            <div className="px-5 py-3.5 border-b border-[#1E2D5A] flex items-center justify-between">
              <h3 className="text-sm font-bold text-white">Active Loans Portfolio Aging Breakdown</h3>
              <span className="text-xs text-slate-400">As of {systemDate}</span>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="bg-[#0B1329] text-slate-400 uppercase text-[10px] tracking-wider border-b border-[#1E2D5A]">
                  <tr>
                    <th className="px-4 py-3">Loan #</th>
                    <th className="px-4 py-3">Borrower</th>
                    <th className="px-4 py-3">Location</th>
                    <th className="px-4 py-3">Disbursed Date</th>
                    <th className="px-4 py-3">Principal Bal</th>
                    <th className="px-4 py-3">Total Outstanding</th>
                    <th className="px-4 py-3">Days Overdue</th>
                    <th className="px-4 py-3">Classification</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#1E2D5A]">
                  {parAnalysis.loans.map((row) => (
                    <tr key={row.loanNo} className="hover:bg-slate-800/40 transition-colors">
                      <td className="px-4 py-3 font-mono font-bold text-blue-400">{row.loanNo}</td>
                      <td className="px-4 py-3 font-semibold text-white">{row.clientName}</td>
                      <td className="px-4 py-3 text-slate-400">{row.location}</td>
                      <td className="px-4 py-3 font-mono text-slate-300">{row.disbursedDate}</td>
                      <td className="px-4 py-3 font-semibold text-white">
                        {formatMoney(row.outstandingPrincipal)}
                      </td>
                      <td className="px-4 py-3 font-bold text-slate-200">
                        {formatMoney(row.totalOutstanding)}
                      </td>
                      <td className="px-4 py-3 font-mono font-bold">
                        <span className={row.daysOverdue > 0 ? 'text-rose-400' : 'text-emerald-400'}>
                          {row.daysOverdue} d
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={`inline-flex px-2 py-0.5 rounded text-[10px] font-bold ${
                            row.bucket === 'Current'
                              ? 'bg-emerald-950 text-emerald-300 border border-emerald-800'
                              : row.bucket === 'PAR 1-30'
                              ? 'bg-amber-950 text-amber-300 border border-amber-800'
                              : 'bg-rose-950 text-rose-300 border border-rose-800'
                          }`}
                        >
                          {row.bucket}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* REPORT 2: DISBURSEMENTS REGISTER */}
      {activeReport === 'disbursements' && (
        <div className="bg-[#111C38] border border-[#1E2D5A] rounded-xl overflow-hidden">
          <div className="px-5 py-3.5 border-b border-[#1E2D5A] flex items-center justify-between">
            <h3 className="text-sm font-bold text-white">Disbursements Register</h3>
            <span className="text-xs text-emerald-400 font-bold">
              Total Disbursed:{' '}
              {formatMoney(disbursements.reduce((sum, d) => sum + d.amount, 0))}
            </span>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-[#0B1329] text-slate-400 uppercase text-[10px] tracking-wider border-b border-[#1E2D5A]">
                <tr>
                  <th className="px-4 py-3">Date</th>
                  <th className="px-4 py-3">Loan #</th>
                  <th className="px-4 py-3">Borrower</th>
                  <th className="px-4 py-3">Disbursed Amount</th>
                  <th className="px-4 py-3">Method</th>
                  <th className="px-4 py-3">Reference</th>
                  <th className="px-4 py-3">Notes</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#1E2D5A]">
                {disbursements.map((d) => {
                  const loan = loans.find((l) => l.id === d.loanId);
                  const client = loan ? clients.find((c) => c.id === loan.clientId) : null;
                  return (
                    <tr key={d.id} className="hover:bg-slate-800/40 transition-colors">
                      <td className="px-4 py-3 font-mono text-slate-400">{d.disbursementDate}</td>
                      <td className="px-4 py-3 font-mono font-bold text-blue-400">
                        {loan?.loanNo || d.loanId}
                      </td>
                      <td className="px-4 py-3 font-semibold text-white">
                        {client ? `${client.firstName} ${client.lastName}` : '-'}
                      </td>
                      <td className="px-4 py-3 font-bold text-emerald-400">
                        {formatMoney(d.amount)}
                      </td>
                      <td className="px-4 py-3 text-slate-300">{d.method}</td>
                      <td className="px-4 py-3 font-mono text-slate-400">{d.reference || '-'}</td>
                      <td className="px-4 py-3 text-slate-400 max-w-xs truncate">
                        {d.notes || '-'}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* REPORT 3: COLLECTIONS & REPAYMENTS */}
      {activeReport === 'collections' && (
        <div className="bg-[#111C38] border border-[#1E2D5A] rounded-xl overflow-hidden">
          <div className="px-5 py-3.5 border-b border-[#1E2D5A] flex items-center justify-between">
            <h3 className="text-sm font-bold text-white">Collections & Repayments Register</h3>
            <span className="text-xs text-emerald-400 font-bold">
              Total Collections:{' '}
              {formatMoney(repayments.reduce((sum, r) => sum + r.amount, 0))}
            </span>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-[#0B1329] text-slate-400 uppercase text-[10px] tracking-wider border-b border-[#1E2D5A]">
                <tr>
                  <th className="px-4 py-3">Date</th>
                  <th className="px-4 py-3">Loan #</th>
                  <th className="px-4 py-3">Borrower</th>
                  <th className="px-4 py-3">Total Amount</th>
                  <th className="px-4 py-3">Principal Settled</th>
                  <th className="px-4 py-3">Interest Earned</th>
                  <th className="px-4 py-3">Penalties</th>
                  <th className="px-4 py-3">Method</th>
                  <th className="px-4 py-3">Reference</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#1E2D5A]">
                {repayments.map((r) => {
                  const loan = loans.find((l) => l.id === r.loanId);
                  const client = loan ? clients.find((c) => c.id === loan.clientId) : null;
                  return (
                    <tr key={r.id} className="hover:bg-slate-800/40 transition-colors">
                      <td className="px-4 py-3 font-mono text-slate-400">{r.paymentDate}</td>
                      <td className="px-4 py-3 font-mono font-bold text-blue-400">
                        {loan?.loanNo || r.loanId}
                      </td>
                      <td className="px-4 py-3 font-semibold text-white">
                        {client ? `${client.firstName} ${client.lastName}` : '-'}
                      </td>
                      <td className="px-4 py-3 font-bold text-white">{formatMoney(r.amount)}</td>
                      <td className="px-4 py-3 font-mono text-slate-300">
                        {formatMoney(r.principalPaid)}
                      </td>
                      <td className="px-4 py-3 font-mono text-emerald-400">
                        {formatMoney(r.interestPaid)}
                      </td>
                      <td className="px-4 py-3 font-mono text-rose-400">
                        {formatMoney(r.penaltyPaid)}
                      </td>
                      <td className="px-4 py-3 text-slate-300">{r.method}</td>
                      <td className="px-4 py-3 font-mono text-slate-400">{r.reference || '-'}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* REPORT 4: FULL LOAN BOOK */}
      {activeReport === 'loan_book' && (
        <div className="bg-[#111C38] border border-[#1E2D5A] rounded-xl overflow-hidden">
          <div className="px-5 py-3.5 border-b border-[#1E2D5A] flex items-center justify-between">
            <h3 className="text-sm font-bold text-white">Master Loan Book Register</h3>
            <span className="text-xs text-slate-400">{loans.length} Total Loans</span>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-[#0B1329] text-slate-400 uppercase text-[10px] tracking-wider border-b border-[#1E2D5A]">
                <tr>
                  <th className="px-4 py-3">Loan #</th>
                  <th className="px-4 py-3">Borrower</th>
                  <th className="px-4 py-3">Principal</th>
                  <th className="px-4 py-3">Interest Method</th>
                  <th className="px-4 py-3">Rate</th>
                  <th className="px-4 py-3">Tenure</th>
                  <th className="px-4 py-3">Applied</th>
                  <th className="px-4 py-3">Disbursed</th>
                  <th className="px-4 py-3">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#1E2D5A]">
                {loans.map((l) => {
                  const client = clients.find((c) => c.id === l.clientId);
                  return (
                    <tr key={l.id} className="hover:bg-slate-800/40 transition-colors">
                      <td className="px-4 py-3 font-mono font-bold text-blue-400">{l.loanNo}</td>
                      <td className="px-4 py-3 font-semibold text-white">
                        {client ? `${client.firstName} ${client.lastName}` : `Client #${l.clientId}`}
                      </td>
                      <td className="px-4 py-3 font-bold text-white">{formatMoney(l.principal)}</td>
                      <td className="px-4 py-3 text-slate-400 capitalize">
                        {l.interestMethod.replace(/_/g, ' ')}
                      </td>
                      <td className="px-4 py-3 text-slate-300">
                        {l.interestRate}% / {l.ratePeriod}
                      </td>
                      <td className="px-4 py-3 text-slate-300">
                        {l.termMonths} {l.repaymentFrequency}
                      </td>
                      <td className="px-4 py-3 font-mono text-slate-400">{l.applicationDate}</td>
                      <td className="px-4 py-3 font-mono text-slate-300">
                        {l.disbursementDate || '-'}
                      </td>
                      <td className="px-4 py-3">
                        <span className="font-semibold text-slate-200">{l.status}</span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
};
