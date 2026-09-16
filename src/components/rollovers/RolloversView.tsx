import React, { useState } from 'react';
import { RefreshCw, CheckCircle2, PlusCircle } from 'lucide-react';
import { useApp } from '../../context/AppContext';
import { formatMoney } from '../../utils/money';
import { Header } from '../common/Header';
import { StatusBadge } from '../common/Badge';
import { Modal } from '../common/Modal';

export const RolloversView: React.FC = () => {
  const { loans, clients, schedules, rollovers, requestRollover, approveRollover } = useApp();

  const [isModalOpen, setIsModalOpen] = useState(false);
  const [selectedLoanId, setSelectedLoanId] = useState<number>(0);
  const [reason, setReason] = useState('');

  // Eligible active loans with outstanding principal
  const activeLoans = loans.filter((l) => l.status === 'Active');

  const selectedLoanOutstanding = (() => {
    if (!selectedLoanId) return 0;
    const loanSched = schedules.filter((s) => s.loanId === selectedLoanId);
    return loanSched.reduce((sum, s) => sum + (s.principalDue - s.principalPaid), 0);
  })();

  const handleRequest = (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedLoanId) return;

    requestRollover(selectedLoanId, reason);
    setIsModalOpen(false);
    setSelectedLoanId(0);
    setReason('');
  };

  return (
    <div id="rollovers-view" className="space-y-6">
      <Header
        title="Loan Restructuring & Rollovers"
        subtitle="Manage loan modifications, debt restructuring, and sequential RN- numbered rollover loans"
        actions={
          <button
            id="btn-request-rollover"
            onClick={() => setIsModalOpen(true)}
            className="flex items-center gap-1.5 px-3 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-xs font-semibold shadow-xs transition-colors"
          >
            <PlusCircle className="w-4 h-4" />
            Request Rollover
          </button>
        }
      />

      {/* Info card */}
      <div className="p-4 bg-[#111C38] border border-[#1E2D5A] rounded-xl flex items-start gap-3">
        <RefreshCw className="w-5 h-5 text-indigo-400 shrink-0 mt-0.5" />
        <div className="text-xs space-y-1">
          <p className="font-bold text-white">Sequential RN- Loan Rollover Policy</p>
          <p className="text-slate-400 leading-relaxed">
            When an active loan undergoes rollover restructuring, the outstanding principal balance
            is transferred to a freshly initialized loan prefixed with{' '}
            <span className="font-mono text-blue-400">RN-</span>. The parent loan is preserved and
            marked as <span className="font-semibold text-slate-200">RolledOver</span> for auditing,
            and a standard restructuring fee is applied.
          </p>
        </div>
      </div>

      {/* Rollover Records Table */}
      <div className="bg-[#111C38] border border-[#1E2D5A] rounded-xl overflow-hidden">
        <div className="px-5 py-3.5 border-b border-[#1E2D5A]">
          <h3 className="text-sm font-bold text-white">Rollover History & Requests</h3>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="bg-[#0B1329] text-slate-400 uppercase text-[10px] tracking-wider border-b border-[#1E2D5A]">
              <tr>
                <th className="px-4 py-3">Date</th>
                <th className="px-4 py-3">Original Loan</th>
                <th className="px-4 py-3">Borrower</th>
                <th className="px-4 py-3">Balance Rolled</th>
                <th className="px-4 py-3">Restructure Fee</th>
                <th className="px-4 py-3">New Loan #</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3 text-right">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#1E2D5A]">
              {rollovers.length === 0 ? (
                <tr>
                  <td colSpan={8} className="px-4 py-12 text-center text-slate-500 text-xs">
                    No rollover applications on record. Click &quot;Request Rollover&quot; to restructure an active loan.
                  </td>
                </tr>
              ) : (
                rollovers.map((r) => {
                  const origLoan = loans.find((l) => l.id === r.originalLoanId);
                  const client = origLoan ? clients.find((c) => c.id === origLoan.clientId) : null;
                  const newLoan = r.newLoanId ? loans.find((l) => l.id === r.newLoanId) : null;

                  return (
                    <tr key={r.id} className="hover:bg-slate-800/40 transition-colors">
                      <td className="px-4 py-3 font-mono text-slate-400">{r.rolloverDate}</td>
                      <td className="px-4 py-3 font-mono font-bold text-blue-400">
                        {origLoan?.loanNo || `Loan #${r.originalLoanId}`}
                      </td>
                      <td className="px-4 py-3 font-semibold text-white">
                        {client ? `${client.firstName} ${client.lastName}` : '-'}
                      </td>
                      <td className="px-4 py-3 font-bold text-white">
                        {formatMoney(r.outstandingBalance)}
                      </td>
                      <td className="px-4 py-3 text-emerald-400">
                        {formatMoney(r.rolloverFee)}
                      </td>
                      <td className="px-4 py-3 font-mono text-indigo-400 font-semibold">
                        {newLoan?.loanNo || (r.status === 'Completed' ? 'RN-Pending' : '-')}
                      </td>
                      <td className="px-4 py-3">
                        <StatusBadge status={r.status} />
                      </td>
                      <td className="px-4 py-3 text-right">
                        {r.status === 'Pending' && (
                          <button
                            onClick={() => approveRollover(r.id)}
                            className="px-3 py-1.5 bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg text-xs font-semibold shadow-xs transition-colors inline-flex items-center gap-1"
                          >
                            <CheckCircle2 className="w-3.5 h-3.5" />
                            Approve & Generate RN-
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Request Modal */}
      <Modal
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        title="Request Loan Rollover / Restructure"
        maxWidth="md"
      >
        <form onSubmit={handleRequest} className="space-y-4">
          <div>
            <label className="block text-xs font-semibold text-slate-300 mb-1">
              Select Active Loan to Restructure *
            </label>
            <select
              value={selectedLoanId}
              onChange={(e) => setSelectedLoanId(Number(e.target.value))}
              className="w-full px-3 py-2 bg-[#162244] border border-[#1E2D5A] rounded-lg text-xs text-white focus:outline-hidden focus:border-blue-500"
              required
            >
              <option value={0}>-- Select Active Loan --</option>
              {activeLoans.map((l) => {
                const c = clients.find((client) => client.id === l.clientId);
                return (
                  <option key={l.id} value={l.id}>
                    {l.loanNo} - {c?.firstName} {c?.lastName}
                  </option>
                );
              })}
            </select>
          </div>

          {selectedLoanId > 0 && (
            <div className="p-3 bg-[#0B1329] border border-[#1E2D5A] rounded-lg text-xs space-y-2">
              <div className="flex justify-between">
                <span className="text-slate-400">Current Outstanding Principal:</span>
                <span className="font-bold text-white">
                  {formatMoney(selectedLoanOutstanding)}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-400">Standard Restructuring Fee (3%):</span>
                <span className="font-semibold text-emerald-400">
                  {formatMoney(selectedLoanOutstanding * 0.03)}
                </span>
              </div>
            </div>
          )}

          <div>
            <label className="block text-xs font-semibold text-slate-300 mb-1">
              Justification / Reason for Restructuring
            </label>
            <textarea
              rows={3}
              required
              placeholder="e.g. Seasonal agricultural cashflow delay, client request for term extension..."
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              className="w-full px-3 py-2 bg-[#162244] border border-[#1E2D5A] rounded-lg text-xs text-white focus:outline-hidden focus:border-blue-500"
            />
          </div>

          <div className="flex justify-end gap-2 pt-2 border-t border-[#1E2D5A]">
            <button
              type="button"
              onClick={() => setIsModalOpen(false)}
              className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-xs font-semibold transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={!selectedLoanId}
              className="px-4 py-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white rounded-lg text-xs font-semibold shadow-xs transition-colors"
            >
              Submit Request
            </button>
          </div>
        </form>
      </Modal>
    </div>
  );
};
