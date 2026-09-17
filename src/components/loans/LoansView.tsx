import React, { useState, useMemo } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import {
  Coins,
  Search,
  PlusCircle,
  CheckCircle,
  XCircle,
  Banknote,
  ArrowDownLeft,
  Calendar,
  AlertCircle,
  Calculator,
  UserCheck,
} from 'lucide-react';
import { useApp } from '../../context/AppContext';
import {
  Disbursement,
  InterestMethod,
  Loan,
  RatePeriod,
  Repayment,
  RepaymentFrequency,
} from '../../types';
import { formatMoney, roundMoney } from '../../utils/money';
import { calculateSchedule, nextDueDate } from '../../utils/amortization';
import { Header } from '../common/Header';
import { StatusBadge } from '../common/Badge';
import { Modal } from '../common/Modal';

interface LoansViewProps {
  initialSubTab?: string;
  preselectedClientId?: number;
}

export const LoansView: React.FC<LoansViewProps> = ({
  initialSubTab = 'all',
  preselectedClientId,
}) => {
  const {
    loans,
    clients,
    loanProducts,
    schedules,
    systemDate,
    createLoanApplication,
    approveLoan,
    declineLoan,
    disburseLoan,
    recordRepayment,
  } = useApp();

  const [activeSubTab, setActiveSubTab] = useState<'all' | 'new' | 'approvals' | 'disbursements' | 'repayments'>(
    (initialSubTab as any) || 'all'
  );

  const [searchTerm, setSearchTerm] = useState('');
  const [statusFilter, setStatusFilter] = useState('All');
  const [selectedLoan, setSelectedLoan] = useState<Loan | null>(null);

  // Disbursement Modal State
  const [disburseModalOpen, setDisburseModalOpen] = useState(false);
  const [disburseTargetLoan, setDisburseTargetLoan] = useState<Loan | null>(null);
  const [disburseForm, setDisburseForm] = useState({
    date: systemDate,
    method: 'Bank Transfer' as Disbursement['method'],
    reference: '',
    notes: '',
  });

  // Repayment Modal / Form State
  const [repaymentForm, setRepaymentForm] = useState({
    loanId: 0,
    amount: '',
    date: systemDate,
    method: 'Bank Transfer' as Repayment['method'],
    reference: '',
    notes: '',
  });
  const [repaymentMessage, setRepaymentMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  // New Application Form State
  const [appForm, setAppForm] = useState({
    clientId: preselectedClientId || (clients[0]?.id ?? 1),
    productId: loanProducts[0]?.id ?? 1,
    principal: '1000',
    interestRate: '10',
    interestMethod: 'flat' as InterestMethod,
    ratePeriod: 'month' as RatePeriod,
    termMonths: '3',
    repaymentFrequency: 'monthly' as RepaymentFrequency,
    purpose: '',
    collateral: '',
  });

  // When a loan product is picked in New Application, autofill product defaults
  const handleProductChange = (prodId: number) => {
    const prod = loanProducts.find((p) => p.id === prodId);
    if (prod) {
      setAppForm((prev) => ({
        ...prev,
        productId: prod.id,
        interestRate: prod.interestRate.toString(),
        interestMethod: prod.interestMethod,
        ratePeriod: prod.ratePeriod,
        repaymentFrequency: prod.repaymentFrequency,
      }));
    }
  };

  // Preview schedule for New Application
  const previewSchedule = useMemo(() => {
    const principalNum = parseFloat(appForm.principal) || 0;
    const rateNum = parseFloat(appForm.interestRate) || 0;
    const termNum = parseInt(appForm.termMonths, 10) || 1;
    if (principalNum <= 0 || termNum <= 0) return [];

    const firstDueDate = nextDueDate(systemDate, appForm.repaymentFrequency);
    return calculateSchedule(
      principalNum,
      rateNum,
      appForm.interestMethod,
      appForm.ratePeriod,
      termNum,
      firstDueDate,
      appForm.repaymentFrequency
    );
  }, [appForm, systemDate]);

  const previewTotals = useMemo(() => {
    const totalPrincipal = previewSchedule.reduce((acc, i) => acc + i.principalDue, 0);
    const totalInterest = previewSchedule.reduce((acc, i) => acc + i.interestDue, 0);
    return {
      principal: roundMoney(totalPrincipal),
      interest: roundMoney(totalInterest),
      total: roundMoney(totalPrincipal + totalInterest),
    };
  }, [previewSchedule]);

  const handleCreateApplication = (e: React.FormEvent) => {
    e.preventDefault();
    const principalNum = parseFloat(appForm.principal);
    const termNum = parseInt(appForm.termMonths, 10);
    const rateNum = parseFloat(appForm.interestRate);

    if (!principalNum || principalNum <= 0) {
      alert('Please enter a valid loan principal amount.');
      return;
    }

    const newLoan = createLoanApplication({
      clientId: Number(appForm.clientId),
      productId: Number(appForm.productId),
      principal: principalNum,
      interestRate: rateNum,
      interestMethod: appForm.interestMethod,
      ratePeriod: appForm.ratePeriod,
      termMonths: termNum,
      repaymentFrequency: appForm.repaymentFrequency,
      applicationDate: systemDate,
      purpose: appForm.purpose,
      collateral: appForm.collateral,
    });

    setSelectedLoan(newLoan);
    setActiveSubTab('all');
  };

  const handleOpenDisburse = (loan: Loan) => {
    setDisburseTargetLoan(loan);
    setDisburseForm({
      date: systemDate,
      method: 'Bank Transfer',
      reference: `DISB-${loan.loanNo}`,
      notes: '',
    });
    setDisburseModalOpen(true);
  };

  const handleConfirmDisbursement = (e: React.FormEvent) => {
    e.preventDefault();
    if (!disburseTargetLoan) return;

    disburseLoan(disburseTargetLoan.id, {
      disbursementDate: disburseForm.date,
      method: disburseForm.method,
      reference: disburseForm.reference,
      notes: disburseForm.notes,
    });

    setDisburseModalOpen(false);
    setSelectedLoan(loans.find((l) => l.id === disburseTargetLoan.id) || null);
    setActiveSubTab('all');
  };

  const handleExecuteRepayment = (e: React.FormEvent) => {
    e.preventDefault();
    const amountNum = parseFloat(repaymentForm.amount);
    if (!repaymentForm.loanId || !amountNum || amountNum <= 0) {
      setRepaymentMessage({ type: 'error', text: 'Please select a loan and enter a valid payment amount.' });
      return;
    }

    const result = recordRepayment({
      loanId: Number(repaymentForm.loanId),
      amount: amountNum,
      paymentDate: repaymentForm.date,
      method: repaymentForm.method,
      reference: repaymentForm.reference,
      notes: repaymentForm.notes,
    });

    if (result.success) {
      setRepaymentMessage({
        type: 'success',
        text: `${result.message} (Allocated: Principal ${formatMoney(result.allocation?.principalPaid)}, Interest ${formatMoney(result.allocation?.interestPaid)}, Penalty ${formatMoney(result.allocation?.penaltyPaid)})`,
      });
      setRepaymentForm((prev) => ({ ...prev, amount: '', reference: '', notes: '' }));
    } else {
      setRepaymentMessage({ type: 'error', text: result.message });
    }
  };

  // Filtered loans list
  const filteredLoans = loans.filter((l) => {
    const client = clients.find((c) => c.id === l.clientId);
    const clientName = client ? `${client.firstName} ${client.lastName}` : '';
    const q = searchTerm.toLowerCase();

    const matchesSearch =
      !searchTerm ||
      l.loanNo.toLowerCase().includes(q) ||
      clientName.toLowerCase().includes(q);

    const matchesStatus = statusFilter === 'All' || l.status === statusFilter;
    return matchesSearch && matchesStatus;
  });

  // Approvals & disbursements queues
  const pendingApprovalLoans = loans.filter(
    (l) => l.status === 'Pending' && l.approvalStatus === 'Pending'
  );
  const approvedLoansAwaitingDisbursement = loans.filter(
    (l) => l.status === 'Pending' && l.approvalStatus === 'Approved'
  );

  // Active loans for repayment dropdown
  const activeLoans = loans.filter((l) => l.status === 'Active');

  // Selected Loan schedules
  const selectedLoanSchedules = selectedLoan
    ? schedules.filter((s) => s.loanId === selectedLoan.id)
    : [];

  return (
    <div id="loans-view" className="space-y-6">
      <Header
        title="Loan Portfolio & Workflows"
        subtitle="Manage loan underwriting, credit review, fund disbursements, and statutory waterfall repayments"
        actions={
          <div className="flex items-center gap-2">
            <button
              id="btn-subtab-new-loan"
              onClick={() => setActiveSubTab('new')}
              className={`flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-semibold transition-all cursor-pointer shadow-xs ${
                activeSubTab === 'new'
                  ? 'bg-blue-600 text-white shadow-blue-500/25'
                  : 'bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-700 border border-slate-200 dark:border-slate-700'
              }`}
            >
              <PlusCircle className="w-4 h-4" />
              New Loan Application
            </button>
          </div>
        }
      />

      {/* Sub-Navigation Tabs */}
      <div className="bg-slate-100/90 dark:bg-[#0B1329] p-1.5 rounded-2xl border border-slate-200/80 dark:border-[#1E2D5A] flex items-center gap-1.5 overflow-x-auto shadow-2xs">
        <button
          onClick={() => setActiveSubTab('all')}
          className={`px-4 py-2.5 rounded-xl flex items-center gap-2 text-sm font-semibold transition-all cursor-pointer whitespace-nowrap ${
            activeSubTab === 'all'
              ? 'bg-blue-600 text-white shadow-sm'
              : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white hover:bg-white/80 dark:hover:bg-slate-800/60'
          }`}
        >
          <Coins className="w-4 h-4" />
          All Loans ({loans.length})
        </button>

        <button
          onClick={() => setActiveSubTab('new')}
          className={`px-4 py-2.5 rounded-xl flex items-center gap-2 text-sm font-semibold transition-all cursor-pointer whitespace-nowrap ${
            activeSubTab === 'new'
              ? 'bg-blue-600 text-white shadow-sm'
              : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white hover:bg-white/80 dark:hover:bg-slate-800/60'
          }`}
        >
          <Calculator className="w-4 h-4" />
          Loan Calculator & Application
        </button>

        <button
          onClick={() => setActiveSubTab('approvals')}
          className={`px-4 py-2.5 rounded-xl flex items-center gap-2 text-sm font-semibold transition-all cursor-pointer whitespace-nowrap ${
            activeSubTab === 'approvals'
              ? 'bg-blue-600 text-white shadow-sm'
              : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white hover:bg-white/80 dark:hover:bg-slate-800/60'
          }`}
        >
          <UserCheck className="w-4 h-4" />
          Approvals
          {pendingApprovalLoans.length > 0 && (
            <span className="px-2 py-0.5 bg-amber-500 text-slate-950 font-bold rounded-full text-xs">
              {pendingApprovalLoans.length}
            </span>
          )}
        </button>

        <button
          onClick={() => setActiveSubTab('disbursements')}
          className={`px-4 py-2.5 rounded-xl flex items-center gap-2 text-sm font-semibold transition-all cursor-pointer whitespace-nowrap ${
            activeSubTab === 'disbursements'
              ? 'bg-blue-600 text-white shadow-sm'
              : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white hover:bg-white/80 dark:hover:bg-slate-800/60'
          }`}
        >
          <Banknote className="w-4 h-4" />
          Disbursements
          {approvedLoansAwaitingDisbursement.length > 0 && (
            <span className="px-2 py-0.5 bg-emerald-500 text-slate-950 font-bold rounded-full text-xs">
              {approvedLoansAwaitingDisbursement.length}
            </span>
          )}
        </button>

        <button
          onClick={() => setActiveSubTab('repayments')}
          className={`px-4 py-2.5 rounded-xl flex items-center gap-2 text-sm font-semibold transition-all cursor-pointer whitespace-nowrap ${
            activeSubTab === 'repayments'
              ? 'bg-blue-600 text-white shadow-sm'
              : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white hover:bg-white/80 dark:hover:bg-slate-800/60'
          }`}
        >
          <ArrowDownLeft className="w-4 h-4" />
          Waterfall Repayment
        </button>
      </div>

      <AnimatePresence mode="wait" initial={false}>
        <motion.div
          key={activeSubTab}
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -6 }}
          transition={{ duration: 0.15, ease: 'easeOut' }}
        >
          {/* SUBTAB 1: ALL LOANS */}
          {activeSubTab === 'all' && (
            <div className="space-y-5">
              <div className="flex flex-col sm:flex-row gap-3 items-center justify-between">
                <div className="relative w-full sm:w-80">
                  <Search className="w-4 h-4 text-slate-400 absolute left-3.5 top-1/2 -translate-y-1/2" />
                  <input
                    type="text"
                    placeholder="Search loan # or borrower name..."
                    value={searchTerm}
                    onChange={(e) => setSearchTerm(e.target.value)}
                    className="w-full pl-10 pr-4 py-2.5 bg-white dark:bg-[#111C38] border border-slate-200/80 dark:border-[#1E2D5A] rounded-xl text-sm text-slate-900 dark:text-white placeholder-slate-400 focus:outline-hidden focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 shadow-2xs transition-all"
                  />
                </div>

                <select
                  value={statusFilter}
                  onChange={(e) => setStatusFilter(e.target.value)}
                  className="w-full sm:w-auto px-4 py-2.5 bg-white dark:bg-[#111C38] border border-slate-200/80 dark:border-[#1E2D5A] rounded-xl text-sm text-slate-800 dark:text-slate-200 focus:outline-hidden focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 shadow-2xs transition-all"
                >
                  <option value="All">All Statuses</option>
                  <option value="Pending">Pending</option>
                  <option value="Active">Active</option>
                  <option value="Closed">Closed</option>
                  <option value="RolledOver">RolledOver</option>
                  <option value="BadDebt">BadDebt</option>
                </select>
              </div>

              <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                {/* Table */}
                <div className="lg:col-span-2 bg-white dark:bg-[#111C38] border border-slate-200/80 dark:border-[#1E2D5A] rounded-2xl overflow-hidden flex flex-col shadow-2xs">
                  <div className="px-5 py-3.5 border-b border-slate-100 dark:border-[#1E2D5A] flex items-center justify-between bg-slate-50/50 dark:bg-transparent">
                    <span className="text-sm font-bold text-slate-800 dark:text-slate-200">
                      Active & Historical Loans ({filteredLoans.length})
                    </span>
                    <span className="text-xs text-slate-500 dark:text-slate-400">
                      Select a loan to view amortization file
                    </span>
                  </div>

                  <div className="overflow-x-auto">
                    <table className="w-full text-left text-sm">
                      <thead className="bg-slate-50 dark:bg-[#0B1329] text-slate-500 dark:text-slate-400 uppercase text-xs font-semibold tracking-wider border-b border-slate-200/80 dark:border-[#1E2D5A]">
                        <tr>
                          <th className="px-5 py-3.5">Loan #</th>
                          <th className="px-5 py-3.5">Borrower</th>
                          <th className="px-5 py-3.5">Principal</th>
                          <th className="px-5 py-3.5">Interest Rate</th>
                          <th className="px-5 py-3.5">Term</th>
                          <th className="px-5 py-3.5">Status</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-100 dark:divide-[#1E2D5A]">
                        {filteredLoans.length === 0 ? (
                          <tr>
                            <td colSpan={6} className="px-5 py-12 text-center text-slate-500 dark:text-slate-400 text-sm">
                              No loans found matching the criteria.
                            </td>
                          </tr>
                        ) : (
                          filteredLoans.map((l) => {
                            const client = clients.find((c) => c.id === l.clientId);
                            const isSelected = selectedLoan?.id === l.id;
                            return (
                              <tr
                                key={l.id}
                                onClick={() => setSelectedLoan(l)}
                                className={`cursor-pointer transition-colors ${
                                  isSelected
                                    ? 'bg-blue-50 dark:bg-blue-900/30 text-slate-900 dark:text-white font-medium'
                                    : 'hover:bg-slate-50/80 dark:hover:bg-slate-800/40 text-slate-700 dark:text-slate-300'
                                }`}
                              >
                                <td className="px-5 py-4 font-mono font-bold text-blue-600 dark:text-blue-400">
                                  {l.loanNo}
                                </td>
                                <td className="px-5 py-4 font-semibold text-slate-900 dark:text-white">
                                  {client ? `${client.firstName} ${client.lastName}` : `Client #${l.clientId}`}
                                </td>
                                <td className="px-5 py-4 font-bold text-slate-900 dark:text-white">
                                  {formatMoney(l.principal)}
                                </td>
                                <td className="px-5 py-4 text-slate-600 dark:text-slate-400">
                                  {l.interestRate}% / {l.ratePeriod}
                                </td>
                                <td className="px-5 py-4 text-slate-600 dark:text-slate-300 capitalize">
                                  {l.termMonths} {l.repaymentFrequency}
                                </td>
                                <td className="px-5 py-4">
                                  <StatusBadge status={l.status} />
                                </td>
                              </tr>
                            );
                          })
                        )}
                      </tbody>
                    </table>
                  </div>
                </div>

                {/* Loan Detail & Schedule Drawer */}
                <div className="bg-white dark:bg-[#111C38] border border-slate-200/80 dark:border-[#1E2D5A] rounded-2xl p-6 flex flex-col space-y-5 shadow-2xs">
                  {selectedLoan ? (
                    <div className="space-y-5">
                      <div className="border-b border-slate-200/80 dark:border-[#1E2D5A] pb-4">
                        <div className="flex items-center justify-between">
                          <span className="font-mono text-base font-bold text-blue-600 dark:text-blue-400">
                            {selectedLoan.loanNo}
                          </span>
                          <StatusBadge status={selectedLoan.status} />
                        </div>
                        <p className="text-sm text-slate-700 dark:text-slate-300 mt-1.5 font-semibold">
                          Client:{' '}
                          {clients.find((c) => c.id === selectedLoan.clientId)?.firstName}{' '}
                          {clients.find((c) => c.id === selectedLoan.clientId)?.lastName}
                        </p>
                      </div>

                      {/* Loan Parameters */}
                      <div className="grid grid-cols-2 gap-3 text-sm">
                        <div className="p-3 bg-slate-50 dark:bg-[#0B1329] rounded-xl border border-slate-200/80 dark:border-[#1E2D5A]">
                          <p className="text-xs text-slate-500 dark:text-slate-400 uppercase font-medium">Principal</p>
                          <p className="font-bold text-slate-900 dark:text-white mt-0.5">{formatMoney(selectedLoan.principal)}</p>
                        </div>
                        <div className="p-3 bg-slate-50 dark:bg-[#0B1329] rounded-xl border border-slate-200/80 dark:border-[#1E2D5A]">
                          <p className="text-xs text-slate-500 dark:text-slate-400 uppercase font-medium">Interest Method</p>
                          <p className="font-semibold text-slate-800 dark:text-slate-200 capitalize mt-0.5">
                            {selectedLoan.interestMethod.replace(/_/g, ' ')}
                          </p>
                        </div>
                        <div className="p-3 bg-slate-50 dark:bg-[#0B1329] rounded-xl border border-slate-200/80 dark:border-[#1E2D5A]">
                          <p className="text-xs text-slate-500 dark:text-slate-400 uppercase font-medium">Admin Fee</p>
                          <p className="font-semibold text-slate-800 dark:text-slate-200 mt-0.5">{formatMoney(selectedLoan.adminFee)}</p>
                        </div>
                        <div className="p-3 bg-slate-50 dark:bg-[#0B1329] rounded-xl border border-slate-200/80 dark:border-[#1E2D5A]">
                          <p className="text-xs text-slate-500 dark:text-slate-400 uppercase font-medium">Disbursed Date</p>
                          <p className="font-mono text-slate-700 dark:text-slate-300 mt-0.5">
                            {selectedLoan.disbursementDate || 'Not yet disbursed'}
                          </p>
                        </div>
                      </div>

                      {/* Quick Action Buttons */}
                      {selectedLoan.status === 'Pending' && selectedLoan.approvalStatus === 'Approved' && (
                        <button
                          onClick={() => handleOpenDisburse(selectedLoan)}
                          className="w-full py-3 bg-emerald-600 hover:bg-emerald-500 text-white text-sm font-bold rounded-xl shadow-sm transition-all flex items-center justify-center gap-2 cursor-pointer"
                        >
                          <Banknote className="w-4 h-4" />
                          Disburse This Loan
                        </button>
                      )}

                      {selectedLoan.status === 'Active' && (
                        <button
                          onClick={() => {
                            setRepaymentForm((prev) => ({
                              ...prev,
                              loanId: selectedLoan.id,
                            }));
                            setActiveSubTab('repayments');
                          }}
                          className="w-full py-3 bg-blue-600 hover:bg-blue-500 text-white text-sm font-bold rounded-xl shadow-sm transition-all flex items-center justify-center gap-2 cursor-pointer"
                        >
                          <ArrowDownLeft className="w-4 h-4" />
                          Record Repayment for this Loan
                        </button>
                      )}

                      {/* Amortization Schedule Table */}
                      <div className="border-t border-slate-200/80 dark:border-[#1E2D5A] pt-4">
                        <h4 className="text-sm font-bold text-slate-900 dark:text-white mb-3 flex items-center justify-between">
                          <span>Repayment Schedule</span>
                          <span className="text-xs text-slate-500 dark:text-slate-400">
                            {selectedLoanSchedules.length} installments
                          </span>
                        </h4>

                        {selectedLoanSchedules.length === 0 ? (
                          <p className="text-sm text-slate-500 dark:text-slate-400 italic py-2">
                            Schedule will be generated upon loan disbursement.
                          </p>
                        ) : (
                          <div className="max-h-64 overflow-y-auto space-y-2 pr-1">
                            {selectedLoanSchedules.map((item) => (
                              <div
                                key={item.id}
                                className="p-3 bg-slate-50 dark:bg-[#0B1329] border border-slate-200/80 dark:border-[#1E2D5A] rounded-xl text-xs sm:text-sm flex items-center justify-between"
                              >
                                <div>
                                  <span className="font-mono font-bold text-blue-600 dark:text-blue-400">
                                    #{item.installmentNo}
                                  </span>{' '}
                                  • Due: <span className="font-mono text-slate-700 dark:text-slate-300">{item.dueDate}</span>
                                  <p className="text-slate-500 dark:text-slate-400 mt-1">
                                    Total Due: {formatMoney(item.totalDue)} (Paid:{' '}
                                    {formatMoney(item.principalPaid + item.interestPaid + item.penaltyPaid)})
                                  </p>
                                </div>
                                <StatusBadge status={item.status} />
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    </div>
                  ) : (
                    <div className="flex flex-col items-center justify-center py-20 text-center text-slate-400 dark:text-slate-500 space-y-3">
                      <Coins className="w-12 h-12 text-slate-300 dark:text-slate-600" />
                      <p className="text-sm font-medium">Select any loan from the registry table to inspect its credit file, payment history, and schedule.</p>
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* SUBTAB 2: NEW LOAN APPLICATION & AMORTIZATION CALCULATOR */}
          {activeSubTab === 'new' && (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              {/* Application Form */}
              <div className="bg-white dark:bg-[#111C38] border border-slate-200/80 dark:border-[#1E2D5A] rounded-2xl p-6 space-y-5 shadow-2xs">
                <h3 className="text-base font-bold text-slate-900 dark:text-white flex items-center gap-2">
                  <Calculator className="w-5 h-5 text-blue-500" />
                  Loan Application & Credit Underwriting
                </h3>

                <form onSubmit={handleCreateApplication} className="space-y-4">
                  <div>
                    <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5">
                      Borrower Client *
                    </label>
                    <select
                      value={appForm.clientId}
                      onChange={(e) => setAppForm({ ...appForm, clientId: Number(e.target.value) })}
                      className="w-full px-4 py-2.5 bg-white dark:bg-[#162244] border border-slate-300 dark:border-[#1E2D5A] rounded-xl text-sm text-slate-900 dark:text-white focus:outline-hidden focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 font-medium transition-all"
                    >
                      {clients.map((c) => (
                        <option key={c.id} value={c.id}>
                          {c.clientNo} - {c.firstName} {c.lastName} ({c.location})
                        </option>
                      ))}
                    </select>
                  </div>

                  <div>
                    <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5">
                      Loan Product
                    </label>
                    <select
                      value={appForm.productId}
                      onChange={(e) => handleProductChange(Number(e.target.value))}
                      className="w-full px-4 py-2.5 bg-white dark:bg-[#162244] border border-slate-300 dark:border-[#1E2D5A] rounded-xl text-sm text-slate-900 dark:text-white focus:outline-hidden focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 font-medium transition-all"
                    >
                      {loanProducts.map((p) => (
                        <option key={p.id} value={p.id}>
                          {p.name} ({p.interestMethod} - {p.interestRate}% / {p.ratePeriod})
                        </option>
                      ))}
                    </select>
                  </div>

                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5">
                        Principal Amount ($) *
                      </label>
                      <input
                        type="number"
                        step="any"
                        required
                        value={appForm.principal}
                        onChange={(e) => setAppForm({ ...appForm, principal: e.target.value })}
                        className="w-full px-4 py-2.5 bg-white dark:bg-[#162244] border border-slate-300 dark:border-[#1E2D5A] rounded-xl text-sm text-slate-900 dark:text-white font-bold focus:outline-hidden focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all"
                      />
                    </div>
                    <div>
                      <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5">
                        Interest Rate (%) *
                      </label>
                      <input
                        type="number"
                        step="any"
                        required
                        value={appForm.interestRate}
                        onChange={(e) => setAppForm({ ...appForm, interestRate: e.target.value })}
                        className="w-full px-4 py-2.5 bg-white dark:bg-[#162244] border border-slate-300 dark:border-[#1E2D5A] rounded-xl text-sm text-slate-900 dark:text-white focus:outline-hidden focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 font-medium transition-all"
                      />
                    </div>
                  </div>

                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5">
                        Interest Method
                      </label>
                      <select
                        value={appForm.interestMethod}
                        onChange={(e) =>
                          setAppForm({ ...appForm, interestMethod: e.target.value as InterestMethod })
                        }
                        className="w-full px-4 py-2.5 bg-white dark:bg-[#162244] border border-slate-300 dark:border-[#1E2D5A] rounded-xl text-sm text-slate-900 dark:text-white focus:outline-hidden focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 font-medium transition-all"
                      >
                        <option value="flat">Flat Interest</option>
                        <option value="reducing_balance">Reducing Balance</option>
                        <option value="interest_only_balloon">Interest-Only Balloon</option>
                      </select>
                    </div>
                    <div>
                      <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5">
                        Rate Period
                      </label>
                      <select
                        value={appForm.ratePeriod}
                        onChange={(e) =>
                          setAppForm({ ...appForm, ratePeriod: e.target.value as RatePeriod })
                        }
                        className="w-full px-4 py-2.5 bg-white dark:bg-[#162244] border border-slate-300 dark:border-[#1E2D5A] rounded-xl text-sm text-slate-900 dark:text-white focus:outline-hidden focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 font-medium transition-all"
                      >
                        <option value="month">Per Month</option>
                        <option value="loan_term">Over Entire Loan Term</option>
                        <option value="year">Per Annum (Year)</option>
                      </select>
                    </div>
                  </div>

                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5">
                        Term (Periods)
                      </label>
                      <input
                        type="number"
                        min="1"
                        required
                        value={appForm.termMonths}
                        onChange={(e) => setAppForm({ ...appForm, termMonths: e.target.value })}
                        className="w-full px-4 py-2.5 bg-white dark:bg-[#162244] border border-slate-300 dark:border-[#1E2D5A] rounded-xl text-sm text-slate-900 dark:text-white focus:outline-hidden focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 font-medium transition-all"
                      />
                    </div>
                    <div>
                      <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5">
                        Repayment Frequency
                      </label>
                      <select
                        value={appForm.repaymentFrequency}
                        onChange={(e) =>
                          setAppForm({
                            ...appForm,
                            repaymentFrequency: e.target.value as RepaymentFrequency,
                          })
                        }
                        className="w-full px-4 py-2.5 bg-white dark:bg-[#162244] border border-slate-300 dark:border-[#1E2D5A] rounded-xl text-sm text-slate-900 dark:text-white focus:outline-hidden focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 font-medium transition-all"
                      >
                        <option value="monthly">Monthly</option>
                        <option value="weekly">Weekly</option>
                        <option value="biweekly">Bi-Weekly</option>
                      </select>
                    </div>
                  </div>

                  <div>
                    <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5">
                      Loan Purpose
                    </label>
                    <input
                      type="text"
                      placeholder="e.g. Stock purchase, agricultural supplies, working capital..."
                      value={appForm.purpose}
                      onChange={(e) => setAppForm({ ...appForm, purpose: e.target.value })}
                      className="w-full px-4 py-2.5 bg-white dark:bg-[#162244] border border-slate-300 dark:border-[#1E2D5A] rounded-xl text-sm text-slate-900 dark:text-white placeholder-slate-400 focus:outline-hidden focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 font-medium transition-all"
                    />
                  </div>

                  <div>
                    <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5">
                      Collateral / Security
                    </label>
                    <input
                      type="text"
                      placeholder="e.g. Delivery vehicle, workshop machinery, personal guarantor..."
                      value={appForm.collateral}
                      onChange={(e) => setAppForm({ ...appForm, collateral: e.target.value })}
                      className="w-full px-4 py-2.5 bg-white dark:bg-[#162244] border border-slate-300 dark:border-[#1E2D5A] rounded-xl text-sm text-slate-900 dark:text-white placeholder-slate-400 focus:outline-hidden focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 font-medium transition-all"
                    />
                  </div>

                  <button
                    type="submit"
                    className="w-full py-3.5 bg-blue-600 hover:bg-blue-500 text-white font-semibold text-sm rounded-xl shadow-md transition-all cursor-pointer"
                  >
                    Submit Loan Application for Credit Review
                  </button>
                </form>
              </div>

              {/* Real-time Schedule Simulation */}
              <div className="bg-white dark:bg-[#111C38] border border-slate-200/80 dark:border-[#1E2D5A] rounded-2xl p-6 space-y-5 flex flex-col justify-between shadow-2xs">
                <div>
                  <h3 className="text-base font-bold text-slate-900 dark:text-white flex items-center justify-between border-b border-slate-200/80 dark:border-[#1E2D5A] pb-4">
                    <span className="flex items-center gap-2">
                      <Calendar className="w-5 h-5 text-emerald-500" />
                      Simulated Amortization Schedule
                    </span>
                    <span className="text-xs font-semibold text-slate-500 dark:text-slate-400">
                      {previewSchedule.length} Installment(s)
                    </span>
                  </h3>

                  {/* Summary KPIs */}
                  <div className="grid grid-cols-3 gap-3 my-4">
                    <div className="p-3.5 bg-slate-50 dark:bg-[#0B1329] border border-slate-200/80 dark:border-[#1E2D5A] rounded-xl text-center">
                      <p className="text-xs text-slate-500 dark:text-slate-400 uppercase font-medium">Principal</p>
                      <p className="text-base sm:text-lg font-bold text-slate-900 dark:text-white mt-0.5">
                        {formatMoney(previewTotals.principal)}
                      </p>
                    </div>
                    <div className="p-3.5 bg-slate-50 dark:bg-[#0B1329] border border-slate-200/80 dark:border-[#1E2D5A] rounded-xl text-center">
                      <p className="text-xs text-slate-500 dark:text-slate-400 uppercase font-medium">Total Interest</p>
                      <p className="text-base sm:text-lg font-bold text-emerald-600 dark:text-emerald-400 mt-0.5">
                        {formatMoney(previewTotals.interest)}
                      </p>
                    </div>
                    <div className="p-3.5 bg-slate-50 dark:bg-[#0B1329] border border-slate-200/80 dark:border-[#1E2D5A] rounded-xl text-center">
                      <p className="text-xs text-slate-500 dark:text-slate-400 uppercase font-medium">Total Repayment</p>
                      <p className="text-base sm:text-lg font-bold text-blue-600 dark:text-blue-400 mt-0.5">
                        {formatMoney(previewTotals.total)}
                      </p>
                    </div>
                  </div>

                  {/* Table */}
                  <div className="overflow-x-auto max-h-80 overflow-y-auto border border-slate-200/80 dark:border-[#1E2D5A] rounded-xl">
                    <table className="w-full text-left text-xs sm:text-sm">
                      <thead className="bg-slate-50 dark:bg-[#0B1329] text-slate-500 dark:text-slate-400 uppercase text-xs font-semibold tracking-wider sticky top-0 border-b border-slate-200/80 dark:border-[#1E2D5A]">
                        <tr>
                          <th className="px-4 py-3">#</th>
                          <th className="px-4 py-3">Due Date</th>
                          <th className="px-4 py-3">Principal</th>
                          <th className="px-4 py-3">Interest</th>
                          <th className="px-4 py-3">Installment</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-100 dark:divide-[#1E2D5A]">
                        {previewSchedule.map((row) => (
                          <tr key={row.installmentNo} className="hover:bg-slate-50/80 dark:hover:bg-slate-800/30">
                            <td className="px-4 py-3 font-mono font-bold text-blue-600 dark:text-blue-400">
                              {row.installmentNo}
                            </td>
                            <td className="px-4 py-3 font-mono text-slate-700 dark:text-slate-300">{row.dueDate}</td>
                            <td className="px-4 py-3 text-slate-800 dark:text-slate-200">{formatMoney(row.principalDue)}</td>
                            <td className="px-4 py-3 text-emerald-600 dark:text-emerald-400 font-semibold">
                              {formatMoney(row.interestDue)}
                            </td>
                            <td className="px-4 py-3 font-bold text-slate-900 dark:text-white">
                              {formatMoney(row.totalDue)}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>

                <div className="text-xs text-slate-500 dark:text-slate-400 italic bg-slate-50 dark:bg-[#0B1329] p-3.5 rounded-xl border border-slate-200/80 dark:border-[#1E2D5A] mt-4">
                  Note: The first installment date will automatically default to the next period
                  following disbursement date, with waterfall allocation enforcing penalty, interest,
                  then principal payments.
                </div>
              </div>
            </div>
          )}

          {/* SUBTAB 3: APPROVALS QUEUE */}
          {activeSubTab === 'approvals' && (
            <div className="bg-white dark:bg-[#111C38] border border-slate-200/80 dark:border-[#1E2D5A] rounded-2xl overflow-hidden shadow-2xs">
              <div className="px-6 py-4 border-b border-slate-200/80 dark:border-[#1E2D5A] bg-slate-50/50 dark:bg-transparent">
                <h3 className="text-base font-bold text-slate-900 dark:text-white">
                  Underwriting & Approvals Queue ({pendingApprovalLoans.length})
                </h3>
                <p className="text-xs sm:text-sm text-slate-500 dark:text-slate-400 mt-0.5">
                  Review credit risk, borrower capacity, collateral, and decide on application approval.
                </p>
              </div>

              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead className="bg-slate-50 dark:bg-[#0B1329] text-slate-500 dark:text-slate-400 uppercase text-xs font-semibold tracking-wider border-b border-slate-200/80 dark:border-[#1E2D5A]">
                    <tr>
                      <th className="px-5 py-3.5">Loan #</th>
                      <th className="px-5 py-3.5">Borrower</th>
                      <th className="px-5 py-3.5">Principal</th>
                      <th className="px-5 py-3.5">Term & Rate</th>
                      <th className="px-5 py-3.5">Purpose & Collateral</th>
                      <th className="px-5 py-3.5 text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100 dark:divide-[#1E2D5A]">
                    {pendingApprovalLoans.length === 0 ? (
                      <tr>
                        <td colSpan={6} className="px-5 py-12 text-center text-slate-500 dark:text-slate-400 text-sm">
                          No loan applications pending approval.
                        </td>
                      </tr>
                    ) : (
                      pendingApprovalLoans.map((l) => {
                        const client = clients.find((c) => c.id === l.clientId);
                        return (
                          <tr key={l.id} className="hover:bg-slate-50/80 dark:hover:bg-slate-800/40 transition-colors">
                            <td className="px-5 py-4 font-mono font-bold text-blue-600 dark:text-blue-400">{l.loanNo}</td>
                            <td className="px-5 py-4">
                              <p className="font-semibold text-slate-900 dark:text-white">
                                {client ? `${client.firstName} ${client.lastName}` : `Client #${l.clientId}`}
                              </p>
                              <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
                                Income: {formatMoney(client?.averageIncome)}/mo
                              </p>
                            </td>
                            <td className="px-5 py-4 font-bold text-slate-900 dark:text-white">
                              {formatMoney(l.principal)}
                            </td>
                            <td className="px-5 py-4 text-slate-700 dark:text-slate-300">
                              {l.termMonths} {l.repaymentFrequency} @ {l.interestRate}%
                            </td>
                            <td className="px-5 py-4 text-slate-600 dark:text-slate-300 max-w-xs truncate">
                              <p className="truncate font-medium">{l.purpose || 'General business'}</p>
                              <p className="text-xs text-slate-500 dark:text-slate-400 truncate mt-0.5">
                                Sec: {l.collateral || 'Guarantor'}
                              </p>
                            </td>
                            <td className="px-5 py-4 text-right space-x-2">
                              <button
                                onClick={() => approveLoan(l.id)}
                                className="px-3.5 py-2 bg-emerald-600 hover:bg-emerald-500 text-white rounded-xl text-xs sm:text-sm font-semibold shadow-xs transition-all inline-flex items-center gap-1.5 cursor-pointer"
                              >
                                <CheckCircle className="w-4 h-4" />
                                Approve
                              </button>
                              <button
                                onClick={() => declineLoan(l.id, 'Declined by credit committee')}
                                className="px-3.5 py-2 bg-rose-600 hover:bg-rose-500 text-white rounded-xl text-xs sm:text-sm font-semibold transition-all inline-flex items-center gap-1.5 cursor-pointer"
                              >
                                <XCircle className="w-4 h-4" />
                                Decline
                              </button>
                            </td>
                          </tr>
                        );
                      })
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* SUBTAB 4: DISBURSEMENTS QUEUE */}
          {activeSubTab === 'disbursements' && (
            <div className="bg-white dark:bg-[#111C38] border border-slate-200/80 dark:border-[#1E2D5A] rounded-2xl overflow-hidden shadow-2xs">
              <div className="px-6 py-4 border-b border-slate-200/80 dark:border-[#1E2D5A] bg-slate-50/50 dark:bg-transparent">
                <h3 className="text-base font-bold text-slate-900 dark:text-white">
                  Approved Loans Ready for Disbursement ({approvedLoansAwaitingDisbursement.length})
                </h3>
                <p className="text-xs sm:text-sm text-slate-500 dark:text-slate-400 mt-0.5">
                  Payout authorized loans, generate repayment schedules, and post double-entry general ledger records.
                </p>
              </div>

              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead className="bg-slate-50 dark:bg-[#0B1329] text-slate-500 dark:text-slate-400 uppercase text-xs font-semibold tracking-wider border-b border-slate-200/80 dark:border-[#1E2D5A]">
                    <tr>
                      <th className="px-5 py-3.5">Loan #</th>
                      <th className="px-5 py-3.5">Borrower</th>
                      <th className="px-5 py-3.5">Approved Principal</th>
                      <th className="px-5 py-3.5">Approved Date</th>
                      <th className="px-5 py-3.5">Admin Fee</th>
                      <th className="px-5 py-3.5 text-right">Action</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100 dark:divide-[#1E2D5A]">
                    {approvedLoansAwaitingDisbursement.length === 0 ? (
                      <tr>
                        <td colSpan={6} className="px-5 py-12 text-center text-slate-500 dark:text-slate-400 text-sm">
                          No approved loans waiting for disbursement.
                        </td>
                      </tr>
                    ) : (
                      approvedLoansAwaitingDisbursement.map((l) => {
                        const client = clients.find((c) => c.id === l.clientId);
                        return (
                          <tr key={l.id} className="hover:bg-slate-50/80 dark:hover:bg-slate-800/40 transition-colors">
                            <td className="px-5 py-4 font-mono font-bold text-blue-600 dark:text-blue-400">{l.loanNo}</td>
                            <td className="px-5 py-4 font-semibold text-slate-900 dark:text-white">
                              {client ? `${client.firstName} ${client.lastName}` : `Client #${l.clientId}`}
                            </td>
                            <td className="px-5 py-4 font-bold text-slate-900 dark:text-white">
                              {formatMoney(l.principal)}
                            </td>
                            <td className="px-5 py-4 font-mono text-slate-600 dark:text-slate-400">{l.approvedAt}</td>
                            <td className="px-5 py-4 text-emerald-600 dark:text-emerald-400 font-semibold">
                              {formatMoney(l.adminFee)}
                            </td>
                            <td className="px-5 py-4 text-right">
                              <button
                                onClick={() => handleOpenDisburse(l)}
                                className="px-4 py-2 bg-emerald-600 hover:bg-emerald-500 text-white rounded-xl text-xs sm:text-sm font-semibold shadow-xs transition-all inline-flex items-center gap-1.5 cursor-pointer"
                              >
                                <Banknote className="w-4 h-4" />
                                Disburse Funds
                              </button>
                            </td>
                          </tr>
                        );
                      })
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* SUBTAB 5: WATERFALL REPAYMENTS */}
          {activeSubTab === 'repayments' && (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <div className="bg-white dark:bg-[#111C38] border border-slate-200/80 dark:border-[#1E2D5A] rounded-2xl p-6 space-y-5 shadow-2xs">
                <h3 className="text-base font-bold text-slate-900 dark:text-white flex items-center gap-2">
                  <ArrowDownLeft className="w-5 h-5 text-emerald-500" />
                  Record Waterfall Repayment
                </h3>

                {repaymentMessage && (
                  <div
                    className={`p-4 rounded-xl text-sm border font-medium ${
                      repaymentMessage.type === 'success'
                        ? 'bg-emerald-50 dark:bg-emerald-950/60 border-emerald-300 dark:border-emerald-800 text-emerald-800 dark:text-emerald-300'
                        : 'bg-rose-50 dark:bg-rose-950/60 border-rose-300 dark:border-rose-800 text-rose-800 dark:text-rose-300'
                    }`}
                  >
                    {repaymentMessage.text}
                  </div>
                )}

                <form onSubmit={handleExecuteRepayment} className="space-y-4">
                  <div>
                    <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5">
                      Select Active Loan *
                    </label>
                    <select
                      value={repaymentForm.loanId}
                      onChange={(e) =>
                        setRepaymentForm({ ...repaymentForm, loanId: Number(e.target.value) })
                      }
                      className="w-full px-4 py-2.5 bg-white dark:bg-[#162244] border border-slate-300 dark:border-[#1E2D5A] rounded-xl text-sm text-slate-900 dark:text-white focus:outline-hidden focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 font-medium transition-all"
                    >
                      <option value={0}>-- Select Active Loan --</option>
                      {activeLoans.map((l) => {
                        const c = clients.find((client) => client.id === l.clientId);
                        return (
                          <option key={l.id} value={l.id}>
                            {l.loanNo} - {c?.firstName} {c?.lastName} (Principal: {formatMoney(l.principal)})
                          </option>
                        );
                      })}
                    </select>
                  </div>

                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5">
                        Repayment Amount ($) *
                      </label>
                      <input
                        type="number"
                        step="any"
                        required
                        placeholder="0.00"
                        value={repaymentForm.amount}
                        onChange={(e) => setRepaymentForm({ ...repaymentForm, amount: e.target.value })}
                        className="w-full px-4 py-2.5 bg-white dark:bg-[#162244] border border-slate-300 dark:border-[#1E2D5A] rounded-xl text-sm text-slate-900 dark:text-white font-bold focus:outline-hidden focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all"
                      />
                    </div>
                    <div>
                      <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5">
                        Payment Date *
                      </label>
                      <input
                        type="date"
                        required
                        value={repaymentForm.date}
                        onChange={(e) => setRepaymentForm({ ...repaymentForm, date: e.target.value })}
                        className="w-full px-4 py-2.5 bg-white dark:bg-[#162244] border border-slate-300 dark:border-[#1E2D5A] rounded-xl text-sm text-slate-900 dark:text-white font-mono focus:outline-hidden focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all"
                      />
                    </div>
                  </div>

                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5">
                        Payment Method
                      </label>
                      <select
                        value={repaymentForm.method}
                        onChange={(e) =>
                          setRepaymentForm({
                            ...repaymentForm,
                            method: e.target.value as Repayment['method'],
                          })
                        }
                        className="w-full px-4 py-2.5 bg-white dark:bg-[#162244] border border-slate-300 dark:border-[#1E2D5A] rounded-xl text-sm text-slate-900 dark:text-white focus:outline-hidden focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 font-medium transition-all"
                      >
                        <option value="Cash">Cash at Counter</option>
                        <option value="Bank Transfer">Bank Transfer</option>
                        <option value="Mobile Money">Mobile Money (EcoCash/OneMoney)</option>
                        <option value="Other">Other</option>
                      </select>
                    </div>
                    <div>
                      <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5">
                        Receipt / Reference #
                      </label>
                      <input
                        type="text"
                        placeholder="e.g. REC-88219"
                        value={repaymentForm.reference}
                        onChange={(e) =>
                          setRepaymentForm({ ...repaymentForm, reference: e.target.value })
                        }
                        className="w-full px-4 py-2.5 bg-white dark:bg-[#162244] border border-slate-300 dark:border-[#1E2D5A] rounded-xl text-sm text-slate-900 dark:text-white font-mono focus:outline-hidden focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all"
                      />
                    </div>
                  </div>

                  <div>
                    <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5">
                      Notes / Memo
                    </label>
                    <input
                      type="text"
                      placeholder="Optional teller notes"
                      value={repaymentForm.notes}
                      onChange={(e) => setRepaymentForm({ ...repaymentForm, notes: e.target.value })}
                      className="w-full px-4 py-2.5 bg-white dark:bg-[#162244] border border-slate-300 dark:border-[#1E2D5A] rounded-xl text-sm text-slate-900 dark:text-white focus:outline-hidden focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all font-medium"
                    />
                  </div>

                  <button
                    type="submit"
                    className="w-full py-3.5 bg-emerald-600 hover:bg-emerald-500 text-white font-semibold text-sm rounded-xl shadow-md transition-all cursor-pointer"
                  >
                    Execute Waterfall Allocation & Post Journal
                  </button>
                </form>
              </div>

              {/* Waterfall Allocation Explanation & Rules */}
              <div className="bg-white dark:bg-[#111C38] border border-slate-200/80 dark:border-[#1E2D5A] rounded-2xl p-6 space-y-5 shadow-2xs">
                <h3 className="text-base font-bold text-slate-900 dark:text-white flex items-center gap-2 border-b border-slate-200/80 dark:border-[#1E2D5A] pb-4">
                  <AlertCircle className="w-5 h-5 text-blue-500" />
                  Statutory Waterfall Allocation Rules
                </h3>

                <div className="space-y-4 text-sm text-slate-600 dark:text-slate-300">
                  <p>
                    In strict adherence to microfinance banking regulations, all received funds are
                    applied according to the following chronological waterfall priority across pending
                    installments:
                  </p>

                  <div className="p-4 bg-slate-50 dark:bg-[#0B1329] rounded-xl border border-slate-200/80 dark:border-[#1E2D5A] space-y-3">
                    <div className="flex items-center gap-2.5">
                      <span className="w-6 h-6 rounded-full bg-rose-600/20 text-rose-600 dark:text-rose-400 font-bold flex items-center justify-center text-xs">
                        1
                      </span>
                      <span className="font-semibold text-slate-900 dark:text-white">Default Penalties & Late Fees</span>
                    </div>
                    <p className="text-xs sm:text-sm text-slate-500 dark:text-slate-400 pl-8">
                      Any outstanding delinquency penalties charged on overdue installments are settled first.
                    </p>

                    <div className="flex items-center gap-2.5 pt-1">
                      <span className="w-6 h-6 rounded-full bg-amber-600/20 text-amber-600 dark:text-amber-400 font-bold flex items-center justify-center text-xs">
                        2
                      </span>
                      <span className="font-semibold text-slate-900 dark:text-white">Earned Interest Income</span>
                    </div>
                    <p className="text-xs sm:text-sm text-slate-500 dark:text-slate-400 pl-8">
                      Accrued interest across due installments is recognized and credited to general ledger Account 4000.
                    </p>

                    <div className="flex items-center gap-2.5 pt-1">
                      <span className="w-6 h-6 rounded-full bg-emerald-600/20 text-emerald-600 dark:text-emerald-400 font-bold flex items-center justify-center text-xs">
                        3
                      </span>
                      <span className="font-semibold text-slate-900 dark:text-white">Principal Balance Reduction</span>
                    </div>
                    <p className="text-xs sm:text-sm text-slate-500 dark:text-slate-400 pl-8">
                      Remaining funds reduce the loan asset principal (Account 1100). If the entire loan schedule reaches zero balance, the loan status automatically updates to Closed.
                    </p>
                  </div>

                  <div className="p-4 bg-blue-50 dark:bg-blue-950/40 border border-blue-200 dark:border-blue-800/60 rounded-xl text-xs sm:text-sm text-blue-900 dark:text-blue-300">
                    Double-entry balancing is automatically enforced. Cash and Bank (1000) is debited for
                    the gross payment received, with offsetting credits to Principal, Interest, and Penalty
                    revenue ledgers.
                  </div>
                </div>
              </div>
            </div>
          )}
        </motion.div>
      </AnimatePresence>

      {/* Disburse Loan Modal */}
      <Modal
        isOpen={disburseModalOpen}
        onClose={() => setDisburseModalOpen(false)}
        title={`Disburse Loan: ${disburseTargetLoan?.loanNo}`}
        maxWidth="md"
      >
        <form onSubmit={handleConfirmDisbursement} className="space-y-4">
          <div className="p-4 bg-slate-50 dark:bg-[#0B1329] border border-slate-200/80 dark:border-[#1E2D5A] rounded-xl text-sm space-y-1.5">
            <p className="text-slate-600 dark:text-slate-400">
              Borrower:{' '}
              <span className="text-slate-900 dark:text-white font-semibold">
                {clients.find((c) => c.id === disburseTargetLoan?.clientId)?.firstName}{' '}
                {clients.find((c) => c.id === disburseTargetLoan?.clientId)?.lastName}
              </span>
            </p>
            <p className="text-slate-600 dark:text-slate-400">
              Disbursement Amount:{' '}
              <span className="text-emerald-600 dark:text-emerald-400 font-bold text-base">
                {formatMoney(disburseTargetLoan?.principal)}
              </span>
            </p>
            {disburseTargetLoan && disburseTargetLoan.adminFee > 0 && (
              <p className="text-slate-600 dark:text-slate-400">
                Admin Fee Recognized:{' '}
                <span className="text-blue-600 dark:text-blue-400 font-semibold">
                  {formatMoney(disburseTargetLoan.adminFee)}
                </span>
              </p>
            )}
          </div>

          <div>
            <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5">
              Disbursement Date *
            </label>
            <input
              type="date"
              required
              value={disburseForm.date}
              onChange={(e) => setDisburseForm({ ...disburseForm, date: e.target.value })}
              className="w-full px-4 py-2.5 bg-white dark:bg-[#162244] border border-slate-300 dark:border-[#1E2D5A] rounded-xl text-sm text-slate-900 dark:text-white font-mono focus:outline-hidden focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all"
            />
          </div>

          <div>
            <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5">
              Disbursement Method *
            </label>
            <select
              value={disburseForm.method}
              onChange={(e) =>
                setDisburseForm({
                  ...disburseForm,
                  method: e.target.value as Disbursement['method'],
                })
              }
              className="w-full px-4 py-2.5 bg-white dark:bg-[#162244] border border-slate-300 dark:border-[#1E2D5A] rounded-xl text-sm text-slate-900 dark:text-white focus:outline-hidden focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 font-medium transition-all"
            >
              <option value="Bank Transfer">Bank Transfer (RTGS / ZIPIT / EFT)</option>
              <option value="Cash">Cash Payout</option>
              <option value="Mobile Money">Mobile Money (EcoCash)</option>
            </select>
          </div>

          <div>
            <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5">
              Transaction Reference / Voucher #
            </label>
            <input
              type="text"
              value={disburseForm.reference}
              onChange={(e) => setDisburseForm({ ...disburseForm, reference: e.target.value })}
              className="w-full px-4 py-2.5 bg-white dark:bg-[#162244] border border-slate-300 dark:border-[#1E2D5A] rounded-xl text-sm text-slate-900 dark:text-white font-mono focus:outline-hidden focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all"
            />
          </div>

          <div className="flex justify-end gap-3 pt-3 border-t border-slate-200/80 dark:border-[#1E2D5A]">
            <button
              type="button"
              onClick={() => setDisburseModalOpen(false)}
              className="px-4 py-2.5 bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-300 rounded-xl text-sm font-semibold transition-colors cursor-pointer"
            >
              Cancel
            </button>
            <button
              type="submit"
              className="px-5 py-2.5 bg-emerald-600 hover:bg-emerald-500 text-white rounded-xl text-sm font-semibold shadow-xs transition-all cursor-pointer"
            >
              Confirm Disbursement
            </button>
          </div>
        </form>
      </Modal>
    </div>
  );
};
