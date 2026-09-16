import React, { useState } from 'react';
import {
  AlertOctagon,
  TrendingUp,
} from 'lucide-react';
import { useApp } from '../../context/AppContext';
import { formatMoney } from '../../utils/money';
import { Header } from '../common/Header';
import { StatusBadge } from '../common/Badge';
import { Modal } from '../common/Modal';

export const BadDebtsView: React.FC = () => {
  const {
    loans,
    clients,
    schedules,
    badDebts,
    badDebtRecoveries,
    writeOffBadDebt,
    recordBadDebtRecovery,
  } = useApp();

  const [writeOffModalOpen, setWriteOffModalOpen] = useState(false);
  const [recoveryModalOpen, setRecoveryModalOpen] = useState(false);

  const [selectedLoanId, setSelectedLoanId] = useState<number>(0);
  const [writeOffReason, setWriteOffReason] = useState('');

  const [recoveryBadDebtId, setRecoveryBadDebtId] = useState<number>(0);
  const [recoveryAmount, setRecoveryAmount] = useState('');
  const [recoveryMethod, setRecoveryMethod] = useState('Cash');
  const [recoveryReference, setRecoveryReference] = useState('');

  // Overdue or active loans available for write-off
  const eligibleLoans = loans.filter((l) => l.status === 'Active');

  const selectedLoanAmounts = (() => {
    if (!selectedLoanId) return { principal: 0, interest: 0, total: 0 };
    const loanSched = schedules.filter((s) => s.loanId === selectedLoanId);
    const principal = loanSched.reduce((s, i) => s + (i.principalDue - i.principalPaid), 0);
    const interest = loanSched.reduce((s, i) => s + (i.interestDue - i.interestPaid), 0);
    return { principal, interest, total: principal + interest };
  })();

  const handleWriteOff = (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedLoanId) return;

    writeOffBadDebt(selectedLoanId, writeOffReason);
    setWriteOffModalOpen(false);
    setSelectedLoanId(0);
    setWriteOffReason('');
  };

  const handleRecovery = (e: React.FormEvent) => {
    e.preventDefault();
    const amountNum = parseFloat(recoveryAmount);
    if (!recoveryBadDebtId || !amountNum || amountNum <= 0) return;

    recordBadDebtRecovery(recoveryBadDebtId, amountNum, recoveryMethod, recoveryReference);
    setRecoveryModalOpen(false);
    setRecoveryBadDebtId(0);
    setRecoveryAmount('');
    setRecoveryReference('');
  };

  const totalWrittenOff = badDebts.reduce((sum, b) => sum + b.amountWrittenOff, 0);
  const totalRecovered = badDebtRecoveries.reduce((sum, r) => sum + r.amount, 0);

  return (
    <div id="bad-debts-view" className="space-y-6">
      <Header
        title="Bad Debts & Delinquency Recovery"
        subtitle="Manage written-off uncollectible loans, statutory provisioning, and post-writeoff recoveries"
        actions={
          <div className="flex items-center gap-2">
            <button
              id="btn-writeoff-loan"
              onClick={() => setWriteOffModalOpen(true)}
              className="flex items-center gap-1.5 px-3 py-2 bg-rose-600 hover:bg-rose-500 text-white rounded-lg text-xs font-semibold shadow-xs transition-colors"
            >
              <AlertOctagon className="w-4 h-4" />
              Write Off Loan
            </button>
            <button
              id="btn-record-recovery"
              onClick={() => setRecoveryModalOpen(true)}
              className="flex items-center gap-1.5 px-3 py-2 bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg text-xs font-semibold shadow-xs transition-colors"
            >
              <TrendingUp className="w-4 h-4" />
              Record Recovery
            </button>
          </div>
        }
      />

      {/* KPI Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div className="p-4 bg-[#111C38] border border-[#1E2D5A] rounded-xl space-y-1">
          <p className="text-xs text-slate-400 font-medium">Total Cumulative Bad Debts Written Off</p>
          <p className="text-2xl font-bold text-rose-400 tracking-tight">{formatMoney(totalWrittenOff)}</p>
          <p className="text-[11px] text-slate-500">{badDebts.length} delinquent account(s) charged off</p>
        </div>

        <div className="p-4 bg-[#111C38] border border-[#1E2D5A] rounded-xl space-y-1">
          <p className="text-xs text-slate-400 font-medium">Total Recoveries Collected (Account 4300)</p>
          <p className="text-2xl font-bold text-emerald-400 tracking-tight">{formatMoney(totalRecovered)}</p>
          <p className="text-[11px] text-emerald-400">
            {totalWrittenOff > 0 ? `${((totalRecovered / totalWrittenOff) * 100).toFixed(1)}% recovery rate` : '0%'}
          </p>
        </div>
      </div>

      {/* Bad Debts Written Off Table */}
      <div className="bg-[#111C38] border border-[#1E2D5A] rounded-xl overflow-hidden">
        <div className="px-5 py-3.5 border-b border-[#1E2D5A]">
          <h3 className="text-sm font-bold text-white">Written-Off Loans Ledger</h3>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="bg-[#0B1329] text-slate-400 uppercase text-[10px] tracking-wider border-b border-[#1E2D5A]">
              <tr>
                <th className="px-4 py-3">Date</th>
                <th className="px-4 py-3">Loan #</th>
                <th className="px-4 py-3">Borrower</th>
                <th className="px-4 py-3">Principal Written Off</th>
                <th className="px-4 py-3">Total Amount</th>
                <th className="px-4 py-3">Reason</th>
                <th className="px-4 py-3">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#1E2D5A]">
              {badDebts.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-4 py-12 text-center text-slate-500 text-xs">
                    No bad debts written off. Excellent credit quality!
                  </td>
                </tr>
              ) : (
                badDebts.map((b) => {
                  const loan = loans.find((l) => l.id === b.loanId);
                  const client = loan ? clients.find((c) => c.id === loan.clientId) : null;
                  return (
                    <tr key={b.id} className="hover:bg-slate-800/40 transition-colors">
                      <td className="px-4 py-3 font-mono text-slate-400">{b.dateWrittenOff}</td>
                      <td className="px-4 py-3 font-mono font-bold text-rose-400">
                        {loan?.loanNo || `Loan #${b.loanId}`}
                      </td>
                      <td className="px-4 py-3 font-semibold text-white">
                        {client ? `${client.firstName} ${client.lastName}` : '-'}
                      </td>
                      <td className="px-4 py-3 font-mono text-slate-300">
                        {formatMoney(b.principalWrittenOff)}
                      </td>
                      <td className="px-4 py-3 font-bold text-rose-300">
                        {formatMoney(b.amountWrittenOff)}
                      </td>
                      <td className="px-4 py-3 text-slate-400 max-w-xs truncate">{b.reason}</td>
                      <td className="px-4 py-3">
                        <StatusBadge status={b.status} />
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Recoveries Table */}
      <div className="bg-[#111C38] border border-[#1E2D5A] rounded-xl overflow-hidden">
        <div className="px-5 py-3.5 border-b border-[#1E2D5A]">
          <h3 className="text-sm font-bold text-white">Delinquency Recoveries History</h3>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="bg-[#0B1329] text-slate-400 uppercase text-[10px] tracking-wider border-b border-[#1E2D5A]">
              <tr>
                <th className="px-4 py-3">Date</th>
                <th className="px-4 py-3">Debt File #</th>
                <th className="px-4 py-3">Amount Recovered</th>
                <th className="px-4 py-3">Method</th>
                <th className="px-4 py-3">Reference</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#1E2D5A]">
              {badDebtRecoveries.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-4 py-8 text-center text-slate-500 text-xs">
                    No recoveries logged yet.
                  </td>
                </tr>
              ) : (
                badDebtRecoveries.map((r) => (
                  <tr key={r.id} className="hover:bg-slate-800/40 transition-colors">
                    <td className="px-4 py-3 font-mono text-slate-400">{r.recoveryDate}</td>
                    <td className="px-4 py-3 font-mono text-blue-400 font-semibold">
                      Debt #{r.badDebtId}
                    </td>
                    <td className="px-4 py-3 font-bold text-emerald-400">
                      {formatMoney(r.amount)}
                    </td>
                    <td className="px-4 py-3 text-slate-300">{r.method}</td>
                    <td className="px-4 py-3 font-mono text-slate-400">{r.reference || '-'}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Write Off Modal */}
      <Modal
        isOpen={writeOffModalOpen}
        onClose={() => setWriteOffModalOpen(false)}
        title="Authorise Bad Debt Write-Off"
        maxWidth="md"
      >
        <form onSubmit={handleWriteOff} className="space-y-4">
          <div>
            <label className="block text-xs font-semibold text-slate-300 mb-1">
              Select Delinquent Loan *
            </label>
            <select
              value={selectedLoanId}
              onChange={(e) => setSelectedLoanId(Number(e.target.value))}
              className="w-full px-3 py-2 bg-[#162244] border border-[#1E2D5A] rounded-lg text-xs text-white focus:outline-hidden focus:border-blue-500"
              required
            >
              <option value={0}>-- Select Active / Overdue Loan --</option>
              {eligibleLoans.map((l) => {
                const c = clients.find((cl) => cl.id === l.clientId);
                return (
                  <option key={l.id} value={l.id}>
                    {l.loanNo} - {c?.firstName} {c?.lastName}
                  </option>
                );
              })}
            </select>
          </div>

          {selectedLoanId > 0 && (
            <div className="p-3 bg-[#0B1329] border border-rose-900/50 rounded-lg text-xs space-y-1">
              <div className="flex justify-between">
                <span className="text-slate-400">Unpaid Principal:</span>
                <span className="font-bold text-white">
                  {formatMoney(selectedLoanAmounts.principal)}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-400">Unpaid Interest:</span>
                <span className="text-slate-300">
                  {formatMoney(selectedLoanAmounts.interest)}
                </span>
              </div>
              <div className="flex justify-between pt-1 border-t border-slate-800">
                <span className="font-bold text-rose-300">Total Charge-Off:</span>
                <span className="font-bold text-rose-400 text-sm">
                  {formatMoney(selectedLoanAmounts.total)}
                </span>
              </div>
            </div>
          )}

          <div>
            <label className="block text-xs font-semibold text-slate-300 mb-1">
              Resolution / Justification *
            </label>
            <textarea
              rows={3}
              required
              placeholder="e.g. Borrower absconded, exhausted recovery efforts, Board Minute #44/26..."
              value={writeOffReason}
              onChange={(e) => setWriteOffReason(e.target.value)}
              className="w-full px-3 py-2 bg-[#162244] border border-[#1E2D5A] rounded-lg text-xs text-white focus:outline-hidden focus:border-blue-500"
            />
          </div>

          <div className="flex justify-end gap-2 pt-2 border-t border-[#1E2D5A]">
            <button
              type="button"
              onClick={() => setWriteOffModalOpen(false)}
              className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-xs font-semibold transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={!selectedLoanId}
              className="px-4 py-2 bg-rose-600 hover:bg-rose-500 disabled:opacity-50 text-white rounded-lg text-xs font-semibold shadow-xs transition-colors"
            >
              Authorize Write-Off
            </button>
          </div>
        </form>
      </Modal>

      {/* Recovery Modal */}
      <Modal
        isOpen={recoveryModalOpen}
        onClose={() => setRecoveryModalOpen(false)}
        title="Record Bad Debt Recovery"
        maxWidth="md"
      >
        <form onSubmit={handleRecovery} className="space-y-4">
          <div>
            <label className="block text-xs font-semibold text-slate-300 mb-1">
              Select Written-Off File *
            </label>
            <select
              value={recoveryBadDebtId}
              onChange={(e) => setRecoveryBadDebtId(Number(e.target.value))}
              className="w-full px-3 py-2 bg-[#162244] border border-[#1E2D5A] rounded-lg text-xs text-white focus:outline-hidden focus:border-blue-500"
              required
            >
              <option value={0}>-- Select Bad Debt Record --</option>
              {badDebts.map((b) => {
                const l = loans.find((item) => item.id === b.loanId);
                const c = l ? clients.find((client) => client.id === l.clientId) : null;
                return (
                  <option key={b.id} value={b.id}>
                    Debt #{b.id} ({l?.loanNo}) - {c?.firstName} {c?.lastName} (Written: {formatMoney(b.amountWrittenOff)})
                  </option>
                );
              })}
            </select>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1">
                Recovered Amount ($) *
              </label>
              <input
                type="number"
                step="any"
                required
                value={recoveryAmount}
                onChange={(e) => setRecoveryAmount(e.target.value)}
                className="w-full px-3 py-2 bg-[#162244] border border-[#1E2D5A] rounded-lg text-xs text-white font-bold focus:outline-hidden focus:border-blue-500"
              />
            </div>
            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1">Payment Method</label>
              <select
                value={recoveryMethod}
                onChange={(e) => setRecoveryMethod(e.target.value)}
                className="w-full px-3 py-2 bg-[#162244] border border-[#1E2D5A] rounded-lg text-xs text-white focus:outline-hidden focus:border-blue-500"
              >
                <option value="Cash">Cash</option>
                <option value="Bank Transfer">Bank Transfer</option>
                <option value="Mobile Money">Mobile Money</option>
              </select>
            </div>
          </div>

          <div>
            <label className="block text-xs font-semibold text-slate-300 mb-1">Reference / Receipt</label>
            <input
              type="text"
              placeholder="e.g. REC-BD-991"
              value={recoveryReference}
              onChange={(e) => setRecoveryReference(e.target.value)}
              className="w-full px-3 py-2 bg-[#162244] border border-[#1E2D5A] rounded-lg text-xs text-white font-mono focus:outline-hidden focus:border-blue-500"
            />
          </div>

          <div className="flex justify-end gap-2 pt-2 border-t border-[#1E2D5A]">
            <button
              type="button"
              onClick={() => setRecoveryModalOpen(false)}
              className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-xs font-semibold transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={!recoveryBadDebtId || !recoveryAmount}
              className="px-4 py-2 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white rounded-lg text-xs font-semibold shadow-xs transition-colors"
            >
              Record Recovery
            </button>
          </div>
        </form>
      </Modal>
    </div>
  );
};
