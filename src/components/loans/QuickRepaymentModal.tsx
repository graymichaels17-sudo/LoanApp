import React, { useState, useEffect } from 'react';
import {
  Coins,
  CheckCircle2,
  User,
} from 'lucide-react';
import { useApp } from '../../context/AppContext';
import { formatMoney, roundMoney } from '../../utils/money';
import { Modal } from '../common/Modal';
import { useToast } from '../../context/ToastContext';

interface QuickRepaymentModalProps {
  isOpen: boolean;
  onClose: () => void;
  defaultLoanId?: number;
}

export const QuickRepaymentModal: React.FC<QuickRepaymentModalProps> = ({
  isOpen,
  onClose,
  defaultLoanId,
}) => {
  const { loans, clients, schedules, recordRepayment, systemDate } = useApp();
  const toast = useToast();

  const activeLoans = loans.filter((l) => l.status === 'Active');

  const [selectedLoanId, setSelectedLoanId] = useState<number>(
    defaultLoanId || (activeLoans[0]?.id ?? 0)
  );
  const [amount, setAmount] = useState<string>('');
  const [paymentDate, setPaymentDate] = useState<string>(systemDate || '2026-09-16');
  const [method, setMethod] = useState<'Cash' | 'Bank Transfer' | 'Mobile Money' | 'Cheque'>('Cash');
  const [reference, setReference] = useState<string>('');
  const [notes, setNotes] = useState<string>('');
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);

  useEffect(() => {
    if (defaultLoanId) {
      setSelectedLoanId(defaultLoanId);
    } else if (activeLoans.length > 0 && !selectedLoanId) {
      setSelectedLoanId(activeLoans[0].id);
    }
  }, [defaultLoanId, activeLoans]);

  const selectedLoan = loans.find((l) => l.id === selectedLoanId);
  const selectedClient = selectedLoan
    ? clients.find((c) => c.id === selectedLoan.clientId)
    : null;

  // Compute outstanding balances for this loan
  const loanSchedules = schedules.filter((s) => s.loanId === selectedLoanId);
  const unpaidPrincipal = roundMoney(
    loanSchedules.reduce((acc, s) => acc + (s.principalDue - s.principalPaid), 0)
  );
  const unpaidInterest = roundMoney(
    loanSchedules.reduce((acc, s) => acc + (s.interestDue - s.interestPaid), 0)
  );
  const unpaidPenalty = roundMoney(
    loanSchedules.reduce((acc, s) => acc + (s.penaltyCharged - s.penaltyPaid), 0)
  );
  const totalOutstanding = roundMoney(unpaidPrincipal + unpaidInterest + unpaidPenalty);

  // Live Statutory Waterfall Calculation Preview
  const enteredAmount = parseFloat(amount) || 0;
  let remaining = enteredAmount;

  const penaltyAllocation = Math.min(remaining, unpaidPenalty);
  remaining = roundMoney(remaining - penaltyAllocation);

  const interestAllocation = Math.min(remaining, unpaidInterest);
  remaining = roundMoney(remaining - interestAllocation);

  const principalAllocation = Math.min(remaining, unpaidPrincipal);
  const excessAmount = roundMoney(Math.max(0, remaining - principalAllocation));

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedLoan) {
      toast.error('Please select an active loan.');
      return;
    }
    if (enteredAmount <= 0) {
      toast.error('Please enter a valid repayment amount greater than zero.');
      return;
    }

    setIsSubmitting(true);
    try {
      const result = recordRepayment({
        loanId: selectedLoan.id,
        amount: enteredAmount,
        paymentDate,
        method,
        reference: reference.trim() || undefined,
        notes: notes.trim() || undefined,
      });

      if (result.success) {
        toast.success(
          `Repayment of ${formatMoney(enteredAmount)} processed for ${selectedClient?.firstName || 'Client'} (${selectedLoan.loanNo})`,
          'Repayment Successful'
        );
        setAmount('');
        setReference('');
        setNotes('');
        onClose();
      } else {
        toast.error(result.message || 'Failed to process repayment');
      }
    } catch (err: any) {
      toast.error(err.message || 'An unexpected error occurred');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Modal isOpen={isOpen} onClose={onClose} title="Record Loan Repayment" maxWidth="lg">
      <form onSubmit={handleSubmit} className="space-y-4">
        {/* Loan Selector */}
        <div>
          <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
            Select Active Loan &amp; Client
          </label>
          <select
            value={selectedLoanId}
            onChange={(e) => setSelectedLoanId(Number(e.target.value))}
            className="w-full bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl px-3.5 py-2.5 text-xs text-slate-900 dark:text-slate-100 font-medium focus:ring-2 focus:ring-blue-500 focus:outline-none"
          >
            {activeLoans.map((l) => {
              const c = clients.find((client) => client.id === l.clientId);
              return (
                <option key={l.id} value={l.id}>
                  {l.loanNo} — {c ? `${c.firstName} ${c.lastName}` : 'Client'} (Principal:{' '}
                  {formatMoney(l.principal)})
                </option>
              );
            })}
          </select>
        </div>

        {/* Selected Loan Snapshot Card */}
        {selectedLoan && (
          <div className="p-3.5 bg-slate-50 dark:bg-slate-900/80 border border-slate-200 dark:border-slate-800 rounded-xl space-y-2">
            <div className="flex items-center justify-between text-xs">
              <span className="font-semibold text-slate-700 dark:text-slate-200 flex items-center gap-1.5">
                <User className="w-3.5 h-3.5 text-blue-500" />
                {selectedClient?.firstName} {selectedClient?.lastName}
              </span>
              <span className="font-mono text-[11px] text-slate-500 dark:text-slate-400">
                {selectedClient?.phone || 'No phone'}
              </span>
            </div>

            <div className="grid grid-cols-3 gap-2 pt-2 border-t border-slate-200 dark:border-slate-800 text-center">
              <div>
                <p className="text-[10px] uppercase font-bold text-slate-400">Total Due</p>
                <p className="text-xs font-mono font-bold text-slate-900 dark:text-white">
                  {formatMoney(totalOutstanding)}
                </p>
              </div>
              <div>
                <p className="text-[10px] uppercase font-bold text-slate-400">Principal Due</p>
                <p className="text-xs font-mono font-semibold text-slate-700 dark:text-slate-300">
                  {formatMoney(unpaidPrincipal)}
                </p>
              </div>
              <div>
                <p className="text-[10px] uppercase font-bold text-slate-400">Interest + Penalty</p>
                <p className="text-xs font-mono font-semibold text-amber-600 dark:text-amber-400">
                  {formatMoney(unpaidInterest + unpaidPenalty)}
                </p>
              </div>
            </div>
          </div>
        )}

        {/* Amount Input */}
        <div>
          <div className="flex items-center justify-between mb-1">
            <label className="text-xs font-semibold text-slate-700 dark:text-slate-300">
              Repayment Amount ($)
            </label>
            {totalOutstanding > 0 && (
              <button
                type="button"
                onClick={() => setAmount(String(totalOutstanding))}
                className="text-[11px] font-semibold text-blue-600 dark:text-blue-400 hover:underline"
              >
                Pay Full Balance ({formatMoney(totalOutstanding)})
              </button>
            )}
          </div>
          <div className="relative">
            <span className="absolute left-3.5 top-2.5 text-xs font-bold text-slate-400">$</span>
            <input
              type="number"
              step="0.01"
              min="0.01"
              required
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              placeholder="0.00"
              className="w-full bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl pl-8 pr-3.5 py-2.5 text-sm font-mono font-bold text-slate-900 dark:text-slate-100 focus:ring-2 focus:ring-blue-500 focus:outline-none"
            />
          </div>
        </div>

        {/* Statutory Waterfall Preview */}
        {enteredAmount > 0 && (
          <div className="p-3 bg-blue-50 dark:bg-blue-950/30 border border-blue-200 dark:border-blue-900/50 rounded-xl space-y-1.5 text-xs">
            <p className="font-bold text-blue-900 dark:text-blue-300 flex items-center gap-1.5">
              <CheckCircle2 className="w-3.5 h-3.5 text-blue-600 dark:text-blue-400" />
              Statutory Waterfall Allocation Preview
            </p>
            <div className="grid grid-cols-3 gap-2 text-[11px] pt-1">
              <div>
                <span className="text-slate-500 dark:text-slate-400">1. Penalty Paid:</span>
                <p className="font-mono font-semibold text-slate-800 dark:text-white">
                  {formatMoney(penaltyAllocation)}
                </p>
              </div>
              <div>
                <span className="text-slate-500 dark:text-slate-400">2. Interest Paid:</span>
                <p className="font-mono font-semibold text-slate-800 dark:text-white">
                  {formatMoney(interestAllocation)}
                </p>
              </div>
              <div>
                <span className="text-slate-500 dark:text-slate-400">3. Principal Paid:</span>
                <p className="font-mono font-semibold text-emerald-600 dark:text-emerald-400">
                  {formatMoney(principalAllocation)}
                </p>
              </div>
            </div>
            {excessAmount > 0 && (
              <p className="text-[11px] text-amber-700 dark:text-amber-300 font-medium pt-1">
                Excess {formatMoney(excessAmount)} will be credited to client's account balance.
              </p>
            )}
          </div>
        )}

        {/* Payment Details: Method & Date */}
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
              Payment Method
            </label>
            <select
              value={method}
              onChange={(e) => setMethod(e.target.value as any)}
              className="w-full bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl px-3 py-2 text-xs text-slate-900 dark:text-slate-100 font-medium focus:ring-2 focus:ring-blue-500 focus:outline-none"
            >
              <option value="Cash">Cash</option>
              <option value="Mobile Money">Mobile Money (EcoCash / OneMoney)</option>
              <option value="Bank Transfer">Bank Transfer</option>
              <option value="Cheque">Cheque</option>
            </select>
          </div>

          <div>
            <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
              Payment Date
            </label>
            <input
              type="date"
              value={paymentDate}
              onChange={(e) => setPaymentDate(e.target.value)}
              className="w-full bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl px-3 py-2 text-xs text-slate-900 dark:text-slate-100 font-medium focus:ring-2 focus:ring-blue-500 focus:outline-none"
            />
          </div>
        </div>

        {/* Reference & Notes */}
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
              Reference / Receipt #
            </label>
            <input
              type="text"
              placeholder="e.g. REC-84920"
              value={reference}
              onChange={(e) => setReference(e.target.value)}
              className="w-full bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl px-3 py-2 text-xs text-slate-900 dark:text-slate-100 focus:ring-2 focus:ring-blue-500 focus:outline-none"
            />
          </div>

          <div>
            <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
              Memo / Notes
            </label>
            <input
              type="text"
              placeholder="Optional notes"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              className="w-full bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl px-3 py-2 text-xs text-slate-900 dark:text-slate-100 focus:ring-2 focus:ring-blue-500 focus:outline-none"
            />
          </div>
        </div>

        {/* Actions */}
        <div className="pt-3 flex items-center justify-end gap-2 border-t border-slate-100 dark:border-slate-800">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 text-xs font-semibold rounded-xl text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={isSubmitting || enteredAmount <= 0}
            className="px-5 py-2 text-xs font-semibold rounded-xl bg-blue-600 hover:bg-blue-500 text-white flex items-center gap-1.5 shadow-sm transition-colors disabled:opacity-50"
          >
            <Coins className="w-4 h-4" />
            {isSubmitting ? 'Processing...' : 'Confirm Repayment'}
          </button>
        </div>
      </form>
    </Modal>
  );
};
