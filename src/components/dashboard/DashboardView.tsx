import React from 'react';
import {
  Coins,
  Users,
  TrendingUp,
  AlertTriangle,
  ArrowUpRight,
  PlusCircle,
  UserPlus,
  ArrowDownLeft,
  CheckCircle2,
} from 'lucide-react';
import { useApp } from '../../context/AppContext';
import { formatMoney, roundMoney } from '../../utils/money';
import { Header } from '../common/Header';
import { StatusBadge } from '../common/Badge';
import { ActiveTab } from '../layout/Sidebar';

interface DashboardViewProps {
  onNavigate: (tab: ActiveTab, subTab?: string) => void;
}

export const DashboardView: React.FC<DashboardViewProps> = ({ onNavigate }) => {
  const { clients, loans, schedules, repayments } = useApp();

  // Active loans
  const activeLoans = loans.filter((l) => l.status === 'Active');
  const pendingApprovals = loans.filter((l) => l.status === 'Pending' && l.approvalStatus === 'Pending');
  const approvedAwaitingDisburse = loans.filter((l) => l.status === 'Pending' && l.approvalStatus === 'Approved');

  // Gross Portfolio Outstanding (unpaid principal + unpaid interest across active loans)
  const activeLoanIds = new Set(activeLoans.map((l) => l.id));
  const activeSchedules = schedules.filter((s) => activeLoanIds.has(s.loanId));

  const outstandingPrincipal = roundMoney(
    activeSchedules.reduce((acc, s) => acc + (s.principalDue - s.principalPaid), 0)
  );
  const outstandingInterest = roundMoney(
    activeSchedules.reduce((acc, s) => acc + (s.interestDue - s.interestPaid), 0)
  );
  const grossPortfolio = roundMoney(outstandingPrincipal + outstandingInterest);

  // Total collections
  const totalCollections = roundMoney(
    repayments.reduce((acc, r) => acc + r.amount, 0)
  );

  // Arrears / Overdue amount
  const overdueSchedules = activeSchedules.filter((s) => s.status === 'Overdue' || s.dueDate < '2026-09-16');
  const totalArrears = roundMoney(
    overdueSchedules.reduce(
      (acc, s) =>
        acc +
        (s.principalDue - s.principalPaid) +
        (s.interestDue - s.interestPaid) +
        (s.penaltyCharged - s.penaltyPaid),
      0
    )
  );

  // Active clients with active loans
  const activeClientIds = new Set(activeLoans.map((l) => l.clientId));
  const activeClientsCount = activeClientIds.size;

  // Recent activity
  const recentLoans = [...loans].slice(0, 5);
  const recentRepayments = [...repayments].slice(0, 5);

  return (
    <div id="dashboard-view" className="space-y-6">
      <Header
        title="Portfolio Dashboard"
        subtitle="Operational overview, portfolio risk metrics, and daily collections"
        actions={
          <div className="flex items-center gap-2">
            <button
              id="btn-quick-new-loan"
              onClick={() => onNavigate('loans', 'new')}
              className="flex items-center gap-1.5 px-3 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-xl text-xs font-semibold shadow-xs transition-colors"
            >
              <PlusCircle className="w-4 h-4" />
              New Loan Application
            </button>
            <button
              id="btn-quick-new-client"
              onClick={() => onNavigate('clients', 'new')}
              className="flex items-center gap-1.5 px-3 py-2 bg-emerald-600 hover:bg-emerald-500 text-white rounded-xl text-xs font-semibold shadow-xs transition-colors"
            >
              <UserPlus className="w-4 h-4" />
              Register Client
            </button>
            <button
              id="btn-quick-repayment"
              onClick={() => onNavigate('loans', 'repayments')}
              className="flex items-center gap-1.5 px-3 py-2 bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-800 dark:text-slate-200 rounded-xl text-xs font-semibold border border-slate-200/80 dark:border-slate-700 transition-colors"
            >
              <ArrowDownLeft className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
              Record Repayment
            </button>
          </div>
        }
      />

      {/* Action alert banner if approvals or disbursements are pending */}
      {(pendingApprovals.length > 0 || approvedAwaitingDisburse.length > 0) && (
        <div className="p-4 bg-blue-50/70 dark:bg-[#111C38] border border-blue-200 dark:border-blue-600/40 rounded-2xl flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 shadow-2xs">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-xl bg-blue-100 dark:bg-blue-600/20 text-blue-600 dark:text-blue-400 flex items-center justify-center shrink-0">
              <Coins className="w-4 h-4" />
            </div>
            <div>
              <p className="text-xs font-bold text-slate-900 dark:text-white">Action Required on Loan Applications</p>
              <p className="text-[11px] text-slate-500 dark:text-slate-400">
                {pendingApprovals.length} application(s) awaiting approval •{' '}
                {approvedAwaitingDisburse.length} approved loan(s) ready for disbursement
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {pendingApprovals.length > 0 && (
              <button
                onClick={() => onNavigate('loans', 'approvals')}
                className="px-3 py-1.5 bg-blue-600 hover:bg-blue-500 text-white rounded-xl text-xs font-semibold shadow-2xs transition-colors"
              >
                Review Approvals ({pendingApprovals.length})
              </button>
            )}
            {approvedAwaitingDisburse.length > 0 && (
              <button
                onClick={() => onNavigate('loans', 'disburse')}
                className="px-3 py-1.5 bg-emerald-600 hover:bg-emerald-500 text-white rounded-xl text-xs font-semibold shadow-2xs transition-colors"
              >
                Disburse Loans ({approvedAwaitingDisburse.length})
              </button>
            )}
          </div>
        </div>
      )}

      {/* Key Portfolio Metrics Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* Gross Portfolio */}
        <div className="p-4 bg-white dark:bg-[#111C38] border border-slate-200/80 dark:border-[#1E2D5A] rounded-2xl space-y-2 shadow-2xs">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-slate-500 dark:text-slate-400">Gross Loan Portfolio</span>
            <div className="w-7 h-7 rounded-lg bg-blue-100 dark:bg-blue-600/20 text-blue-600 dark:text-blue-400 flex items-center justify-center">
              <Coins className="w-4 h-4" />
            </div>
          </div>
          <p className="text-2xl font-bold text-slate-900 dark:text-white tracking-tight">{formatMoney(grossPortfolio)}</p>
          <div className="flex items-center justify-between text-[11px] text-slate-500 dark:text-slate-400 pt-1 border-t border-slate-100 dark:border-slate-800">
            <span>Principal: {formatMoney(outstandingPrincipal)}</span>
            <span>Interest: {formatMoney(outstandingInterest)}</span>
          </div>
        </div>

        {/* Collections */}
        <div className="p-4 bg-white dark:bg-[#111C38] border border-slate-200/80 dark:border-[#1E2D5A] rounded-2xl space-y-2 shadow-2xs">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-slate-500 dark:text-slate-400">Total Repayments Collected</span>
            <div className="w-7 h-7 rounded-lg bg-emerald-100 dark:bg-emerald-600/20 text-emerald-600 dark:text-emerald-400 flex items-center justify-center">
              <TrendingUp className="w-4 h-4" />
            </div>
          </div>
          <p className="text-2xl font-bold text-slate-900 dark:text-white tracking-tight">{formatMoney(totalCollections)}</p>
          <div className="flex items-center gap-1 text-[11px] text-emerald-600 dark:text-emerald-400 pt-1 border-t border-slate-100 dark:border-slate-800 font-medium">
            <CheckCircle2 className="w-3.5 h-3.5" />
            <span>{repayments.length} transactions processed</span>
          </div>
        </div>

        {/* Arrears / Portfolio at Risk */}
        <div className="p-4 bg-white dark:bg-[#111C38] border border-slate-200/80 dark:border-[#1E2D5A] rounded-2xl space-y-2 shadow-2xs">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-slate-500 dark:text-slate-400">Portfolio at Risk (PAR)</span>
            <div className="w-7 h-7 rounded-lg bg-rose-100 dark:bg-rose-600/20 text-rose-600 dark:text-rose-400 flex items-center justify-center">
              <AlertTriangle className="w-4 h-4" />
            </div>
          </div>
          <p className="text-2xl font-bold text-rose-600 dark:text-rose-300 tracking-tight">{formatMoney(totalArrears)}</p>
          <div className="flex items-center justify-between text-[11px] text-slate-500 dark:text-slate-400 pt-1 border-t border-slate-100 dark:border-slate-800">
            <span>{overdueSchedules.length} overdue installments</span>
            <span className="text-rose-600 dark:text-rose-400 font-bold">
              {grossPortfolio > 0 ? `${((totalArrears / grossPortfolio) * 100).toFixed(1)}% PAR` : '0.0%'}
            </span>
          </div>
        </div>

        {/* Active Clients */}
        <div className="p-4 bg-white dark:bg-[#111C38] border border-slate-200/80 dark:border-[#1E2D5A] rounded-2xl space-y-2 shadow-2xs">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-slate-500 dark:text-slate-400">Active Borrowers</span>
            <div className="w-7 h-7 rounded-lg bg-purple-100 dark:bg-purple-600/20 text-purple-600 dark:text-purple-400 flex items-center justify-center">
              <Users className="w-4 h-4" />
            </div>
          </div>
          <p className="text-2xl font-bold text-slate-900 dark:text-white tracking-tight">{activeClientsCount}</p>
          <div className="flex items-center justify-between text-[11px] text-slate-500 dark:text-slate-400 pt-1 border-t border-slate-100 dark:border-slate-800">
            <span>Total Registered: {clients.length}</span>
            <span>Active Loans: {activeLoans.length}</span>
          </div>
        </div>
      </div>

      {/* Two-column layout: Recent Loans & Recent Collections */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Recent Loans */}
        <div className="bg-white dark:bg-[#111C38] border border-slate-200/80 dark:border-[#1E2D5A] rounded-2xl overflow-hidden flex flex-col shadow-2xs">
          <div className="px-5 py-3.5 border-b border-slate-100 dark:border-[#1E2D5A] flex items-center justify-between bg-slate-50/50 dark:bg-transparent">
            <h3 className="text-sm font-bold text-slate-900 dark:text-white flex items-center gap-2">
              <Coins className="w-4 h-4 text-amber-500" />
              Recent Loans
            </h3>
            <button
              onClick={() => onNavigate('loans', 'all')}
              className="text-xs text-blue-600 dark:text-blue-400 hover:underline flex items-center gap-1 font-semibold"
            >
              View all
              <ArrowUpRight className="w-3.5 h-3.5" />
            </button>
          </div>
          <div className="overflow-x-auto flex-1">
            <table className="w-full text-left text-xs">
              <thead className="bg-slate-50 dark:bg-[#0B1329] text-slate-500 dark:text-slate-400 uppercase text-[10px] tracking-wider border-b border-slate-100 dark:border-[#1E2D5A]">
                <tr>
                  <th className="px-4 py-2.5">Loan #</th>
                  <th className="px-4 py-2.5">Client</th>
                  <th className="px-4 py-2.5">Principal</th>
                  <th className="px-4 py-2.5">Method</th>
                  <th className="px-4 py-2.5">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-[#1E2D5A]">
                {recentLoans.map((l) => {
                  const client = clients.find((c) => c.id === l.clientId);
                  return (
                    <tr key={l.id} className="hover:bg-slate-50 dark:hover:bg-slate-800/40 transition-colors">
                      <td className="px-4 py-2.5 font-mono font-semibold text-blue-600 dark:text-blue-400">
                        {l.loanNo}
                      </td>
                      <td className="px-4 py-2.5 text-slate-800 dark:text-slate-200 font-medium">
                        {client ? `${client.firstName} ${client.lastName}` : `Client #${l.clientId}`}
                      </td>
                      <td className="px-4 py-2.5 font-bold text-slate-900 dark:text-white font-mono">
                        {formatMoney(l.principal)}
                      </td>
                      <td className="px-4 py-2.5 text-slate-500 dark:text-slate-400 capitalize">
                        {l.interestMethod.replace(/_/g, ' ')}
                      </td>
                      <td className="px-4 py-2.5">
                        <StatusBadge status={l.status} />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>

        {/* Recent Repayments */}
        <div className="bg-white dark:bg-[#111C38] border border-slate-200/80 dark:border-[#1E2D5A] rounded-2xl overflow-hidden flex flex-col shadow-2xs">
          <div className="px-5 py-3.5 border-b border-slate-100 dark:border-[#1E2D5A] flex items-center justify-between bg-slate-50/50 dark:bg-transparent">
            <h3 className="text-sm font-bold text-slate-900 dark:text-white flex items-center gap-2">
              <TrendingUp className="w-4 h-4 text-emerald-500" />
              Recent Repayments Received
            </h3>
            <button
              onClick={() => onNavigate('loans', 'repayments')}
              className="text-xs text-blue-600 dark:text-blue-400 hover:underline flex items-center gap-1 font-semibold"
            >
              Record payment
              <ArrowUpRight className="w-3.5 h-3.5" />
            </button>
          </div>
          <div className="overflow-x-auto flex-1">
            <table className="w-full text-left text-xs">
              <thead className="bg-slate-50 dark:bg-[#0B1329] text-slate-500 dark:text-slate-400 uppercase text-[10px] tracking-wider border-b border-slate-100 dark:border-[#1E2D5A]">
                <tr>
                  <th className="px-4 py-2.5">Date</th>
                  <th className="px-4 py-2.5">Loan #</th>
                  <th className="px-4 py-2.5">Amount</th>
                  <th className="px-4 py-2.5">Method</th>
                  <th className="px-4 py-2.5">Reference</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-[#1E2D5A]">
                {recentRepayments.map((r) => {
                  const loan = loans.find((l) => l.id === r.loanId);
                  return (
                    <tr key={r.id} className="hover:bg-slate-50 dark:hover:bg-slate-800/40 transition-colors">
                      <td className="px-4 py-2.5 text-slate-500 dark:text-slate-400 font-mono text-[11px]">
                        {r.paymentDate}
                      </td>
                      <td className="px-4 py-2.5 font-mono text-blue-600 dark:text-blue-400 font-semibold">
                        {loan?.loanNo || `Loan #${r.loanId}`}
                      </td>
                      <td className="px-4 py-2.5 font-bold text-emerald-600 dark:text-emerald-400 font-mono">
                        {formatMoney(r.amount)}
                      </td>
                      <td className="px-4 py-2.5 text-slate-700 dark:text-slate-300">{r.method}</td>
                      <td className="px-4 py-2.5 text-slate-400 font-mono text-[11px]">
                        {r.reference || '-'}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
};
