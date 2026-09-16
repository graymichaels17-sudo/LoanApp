import React, { useState, useMemo } from 'react';
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
        subtitle="Manage loan underwriting, approvals, disbursements, waterfall repayments, and amortization"
        actions={
          <div className="flex items-center gap-2">
            <button
              id="btn-subtab-new-loan"
              onClick={() => setActiveSubTab('new')}
              className={`flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-semibold transition-colors ${
                activeSubTab === 'new'
                  ? 'bg-blue-600 text-white'
                  : 'bg-slate-800 text-slate-300 hover:bg-slate-700'
              }`}
            >
              <PlusCircle className="w-4 h-4" />
              New Loan Application
            </button>
          </div>
        }
      />

      {/* Sub-Navigation Tabs */}
      <div className="flex items-center gap-1 border-b border-slate-800 pb-2 text-xs font-semibold overflow-x-auto">
        <button
          onClick={() => setActiveSubTab('all')}
          className={`px-3.5 py-2 rounded-lg flex items-center gap-2 transition-colors ${
            activeSubTab === 'all'
              ? 'bg-blue-600 text-white'
              : 'text-slate-400 hover:text-white hover:bg-slate-800/60'
          }`}
        >
          <Coins className="w-4 h-4" />
          All Loans ({loans.length})
        </button>

        <button
          onClick={() => setActiveSubTab('new')}
          className={`px-3.5 py-2 rounded-lg flex items-center gap-2 transition-colors ${
            activeSubTab === 'new'
              ? 'bg-blue-600 text-white'
              : 'text-slate-400 hover:text-white hover:bg-slate-800/60'
          }`}
        >
          <Calculator className="w-4 h-4" />
          Loan Calculator & Application
        </button>

        <button
          onClick={() => setActiveSubTab('approvals')}
          className={`px-3.5 py-2 rounded-lg flex items-center gap-2 transition-colors ${
            activeSubTab === 'approvals'
              ? 'bg-blue-600 text-white'
              : 'text-slate-400 hover:text-white hover:bg-slate-800/60'
          }`}
        >
          <UserCheck className="w-4 h-4" />
          Approvals
          {pendingApprovalLoans.length > 0 && (
            <span className="px-1.5 py-0.2 bg-amber-500 text-slate-950 font-bold rounded-full text-[10px]">
              {pendingApprovalLoans.length}
            </span>
          )}
        </button>

        <button
          onClick={() => setActiveSubTab('disbursements')}
          className={`px-3.5 py-2 rounded-lg flex items-center gap-2 transition-colors ${
            activeSubTab === 'disbursements'
              ? 'bg-blue-600 text-white'
              : 'text-slate-400 hover:text-white hover:bg-slate-800/60'
          }`}
        >
          <Banknote className="w-4 h-4" />
          Disbursements
          {approvedLoansAwaitingDisbursement.length > 0 && (
            <span className="px-1.5 py-0.2 bg-emerald-500 text-slate-950 font-bold rounded-full text-[10px]">
              {approvedLoansAwaitingDisbursement.length}
            </span>
          )}
        </button>

        <button
          onClick={() => setActiveSubTab('repayments')}
          className={`px-3.5 py-2 rounded-lg flex items-center gap-2 transition-colors ${
            activeSubTab === 'repayments'
              ? 'bg-blue-600 text-white'
              : 'text-slate-400 hover:text-white hover:bg-slate-800/60'
          }`}
        >
          <ArrowDownLeft className="w-4 h-4" />
          Waterfall Repayment
        </button>
      </div>

      {/* SUBTAB 1: ALL LOANS */}
      {activeSubTab === 'all' && (
        <div className="space-y-4">
          <div className="flex flex-col sm:flex-row gap-3 items-center justify-between">
            <div className="relative w-full sm:w-80">
              <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
              <input
                type="text"
                placeholder="Search loan # or borrower name..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                className="w-full pl-9 pr-3 py-2 bg-[#111C38] border border-[#1E2D5A] rounded-lg text-xs text-white placeholder-slate-400 focus:outline-hidden focus:border-blue-500"
              />
            </div>

            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="px-3 py-2 bg-[#111C38] border border-[#1E2D5A] rounded-lg text-xs text-slate-200 focus:outline-hidden focus:border-blue-500"
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
            <div className="lg:col-span-2 bg-[#111C38] border border-[#1E2D5A] rounded-xl overflow-hidden flex flex-col">
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead className="bg-[#0B1329] text-slate-400 uppercase text-[10px] tracking-wider border-b border-[#1E2D5A]">
                    <tr>
                      <th className="px-4 py-3">Loan #</th>
                      <th className="px-4 py-3">Borrower</th>
                      <th className="px-4 py-3">Principal</th>
                      <th className="px-4 py-3">Interest Rate</th>
                      <th className="px-4 py-3">Term</th>
                      <th className="px-4 py-3">Status</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#1E2D5A]">
                    {filteredLoans.length === 0 ? (
                      <tr>
                        <td colSpan={6} className="px-4 py-8 text-center text-slate-500 text-xs">
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
                                ? 'bg-blue-900/30 text-white font-medium'
                                : 'hover:bg-slate-800/40 text-slate-300'
                            }`}
                          >
                            <td className="px-4 py-3 font-mono font-semibold text-blue-400">
                              {l.loanNo}
                            </td>
                            <td className="px-4 py-3 font-semibold text-white">
                              {client ? `${client.firstName} ${client.lastName}` : `Client #${l.clientId}`}
                            </td>
                            <td className="px-4 py-3 font-bold text-white">
                              {formatMoney(l.principal)}
                            </td>
                            <td className="px-4 py-3 text-slate-400">
                              {l.interestRate}% / {l.ratePeriod}
                            </td>
                            <td className="px-4 py-3 text-slate-300">
                              {l.termMonths} {l.repaymentFrequency}
                            </td>
                            <td className="px-4 py-3">
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
            <div className="bg-[#111C38] border border-[#1E2D5A] rounded-xl p-5 flex flex-col space-y-4">
              {selectedLoan ? (
                <div className="space-y-4">
                  <div className="border-b border-[#1E2D5A] pb-3">
                    <div className="flex items-center justify-between">
                      <span className="font-mono text-sm font-bold text-blue-400">
                        {selectedLoan.loanNo}
                      </span>
                      <StatusBadge status={selectedLoan.status} />
                    </div>
                    <p className="text-xs text-slate-300 mt-1 font-semibold">
                      Client:{' '}
                      {clients.find((c) => c.id === selectedLoan.clientId)?.firstName}{' '}
                      {clients.find((c) => c.id === selectedLoan.clientId)?.lastName}
                    </p>
                  </div>

                  {/* Loan Parameters */}
                  <div className="grid grid-cols-2 gap-2 text-xs">
                    <div className="p-2 bg-[#0B1329] rounded-lg border border-[#1E2D5A]">
                      <p className="text-[10px] text-slate-400 uppercase">Principal</p>
                      <p className="font-bold text-white">{formatMoney(selectedLoan.principal)}</p>
                    </div>
                    <div className="p-2 bg-[#0B1329] rounded-lg border border-[#1E2D5A]">
                      <p className="text-[10px] text-slate-400 uppercase">Interest Method</p>
                      <p className="font-semibold text-slate-200 capitalize">
                        {selectedLoan.interestMethod.replace(/_/g, ' ')}
                      </p>
                    </div>
                    <div className="p-2 bg-[#0B1329] rounded-lg border border-[#1E2D5A]">
                      <p className="text-[10px] text-slate-400 uppercase">Admin Fee</p>
                      <p className="font-semibold text-slate-200">{formatMoney(selectedLoan.adminFee)}</p>
                    </div>
                    <div className="p-2 bg-[#0B1329] rounded-lg border border-[#1E2D5A]">
                      <p className="text-[10px] text-slate-400 uppercase">Disbursed Date</p>
                      <p className="font-mono text-slate-300">
                        {selectedLoan.disbursementDate || 'Not yet disbursed'}
                      </p>
                    </div>
                  </div>

                  {/* Quick Action Buttons */}
                  {selectedLoan.status === 'Pending' && selectedLoan.approvalStatus === 'Approved' && (
                    <button
                      onClick={() => handleOpenDisburse(selectedLoan)}
                      className="w-full py-2 bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-bold rounded-lg shadow-sm transition-colors flex items-center justify-center gap-1.5"
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
                      className="w-full py-2 bg-blue-600 hover:bg-blue-500 text-white text-xs font-bold rounded-lg shadow-sm transition-colors flex items-center justify-center gap-1.5"
                    >
                      <ArrowDownLeft className="w-4 h-4" />
                      Record Repayment for this Loan
                    </button>
                  )}

                  {/* Amortization Schedule Table */}
                  <div className="border-t border-[#1E2D5A] pt-3">
                    <h4 className="text-xs font-bold text-white mb-2 flex items-center justify-between">
                      <span>Repayment Schedule</span>
                      <span className="text-[11px] text-slate-400">
                        {selectedLoanSchedules.length} installments
                      </span>
                    </h4>

                    {selectedLoanSchedules.length === 0 ? (
                      <p className="text-xs text-slate-500 italic py-2">
                        Schedule will be generated upon loan disbursement.
                      </p>
                    ) : (
                      <div className="max-h-56 overflow-y-auto space-y-1.5 pr-1">
                        {selectedLoanSchedules.map((item) => (
                          <div
                            key={item.id}
                            className="p-2 bg-[#0B1329] border border-[#1E2D5A] rounded-lg text-[11px] flex items-center justify-between"
                          >
                            <div>
                              <span className="font-mono font-bold text-blue-400">
                                #{item.installmentNo}
                              </span>{' '}
                              • Due: <span className="font-mono text-slate-300">{item.dueDate}</span>
                              <p className="text-slate-400 mt-0.5">
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
                <div className="flex flex-col items-center justify-center py-16 text-center text-slate-500 space-y-2">
                  <Coins className="w-10 h-10 text-slate-600" />
                  <p className="text-xs">Select any loan from the table to view its credit file and schedule.</p>
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
          <div className="bg-[#111C38] border border-[#1E2D5A] rounded-xl p-5 space-y-4">
            <h3 className="text-sm font-bold text-white flex items-center gap-2">
              <Calculator className="w-4 h-4 text-blue-400" />
              Loan Application Details
            </h3>

            <form onSubmit={handleCreateApplication} className="space-y-4">
              <div>
                <label className="block text-xs font-semibold text-slate-300 mb-1">Borrower Client *</label>
                <select
                  value={appForm.clientId}
                  onChange={(e) => setAppForm({ ...appForm, clientId: Number(e.target.value) })}
                  className="w-full px-3 py-2 bg-[#162244] border border-[#1E2D5A] rounded-lg text-xs text-white focus:outline-hidden focus:border-blue-500"
                >
                  {clients.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.clientNo} - {c.firstName} {c.lastName} ({c.location})
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-300 mb-1">Loan Product</label>
                <select
                  value={appForm.productId}
                  onChange={(e) => handleProductChange(Number(e.target.value))}
                  className="w-full px-3 py-2 bg-[#162244] border border-[#1E2D5A] rounded-lg text-xs text-white focus:outline-hidden focus:border-blue-500"
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
                  <label className="block text-xs font-semibold text-slate-300 mb-1">
                    Principal Amount ($) *
                  </label>
                  <input
                    type="number"
                    step="any"
                    required
                    value={appForm.principal}
                    onChange={(e) => setAppForm({ ...appForm, principal: e.target.value })}
                    className="w-full px-3 py-2 bg-[#162244] border border-[#1E2D5A] rounded-lg text-xs text-white font-bold focus:outline-hidden focus:border-blue-500"
                  />
                </div>
                <div>
                  <label className="block text-xs font-semibold text-slate-300 mb-1">
                    Interest Rate (%) *
                  </label>
                  <input
                    type="number"
                    step="any"
                    required
                    value={appForm.interestRate}
                    onChange={(e) => setAppForm({ ...appForm, interestRate: e.target.value })}
                    className="w-full px-3 py-2 bg-[#162244] border border-[#1E2D5A] rounded-lg text-xs text-white focus:outline-hidden focus:border-blue-500"
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-semibold text-slate-300 mb-1">Interest Method</label>
                  <select
                    value={appForm.interestMethod}
                    onChange={(e) =>
                      setAppForm({ ...appForm, interestMethod: e.target.value as InterestMethod })
                    }
                    className="w-full px-3 py-2 bg-[#162244] border border-[#1E2D5A] rounded-lg text-xs text-white focus:outline-hidden focus:border-blue-500"
                  >
                    <option value="flat">Flat Interest</option>
                    <option value="reducing_balance">Reducing Balance</option>
                    <option value="interest_only_balloon">Interest-Only Balloon</option>
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-semibold text-slate-300 mb-1">Rate Period</label>
                  <select
                    value={appForm.ratePeriod}
                    onChange={(e) =>
                      setAppForm({ ...appForm, ratePeriod: e.target.value as RatePeriod })
                    }
                    className="w-full px-3 py-2 bg-[#162244] border border-[#1E2D5A] rounded-lg text-xs text-white focus:outline-hidden focus:border-blue-500"
                  >
                    <option value="month">Per Month</option>
                    <option value="loan_term">Over Entire Loan Term</option>
                    <option value="year">Per Annum (Year)</option>
                  </select>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-semibold text-slate-300 mb-1">Term (Periods)</label>
                  <input
                    type="number"
                    min="1"
                    required
                    value={appForm.termMonths}
                    onChange={(e) => setAppForm({ ...appForm, termMonths: e.target.value })}
                    className="w-full px-3 py-2 bg-[#162244] border border-[#1E2D5A] rounded-lg text-xs text-white focus:outline-hidden focus:border-blue-500"
                  />
                </div>
                <div>
                  <label className="block text-xs font-semibold text-slate-300 mb-1">
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
                    className="w-full px-3 py-2 bg-[#162244] border border-[#1E2D5A] rounded-lg text-xs text-white focus:outline-hidden focus:border-blue-500"
                  >
                    <option value="monthly">Monthly</option>
                    <option value="weekly">Weekly</option>
                    <option value="biweekly">Bi-Weekly</option>
                  </select>
                </div>
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-300 mb-1">Loan Purpose</label>
                <input
                  type="text"
                  placeholder="e.g. Stock purchase, working capital..."
                  value={appForm.purpose}
                  onChange={(e) => setAppForm({ ...appForm, purpose: e.target.value })}
                  className="w-full px-3 py-2 bg-[#162244] border border-[#1E2D5A] rounded-lg text-xs text-white focus:outline-hidden focus:border-blue-500"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-300 mb-1">
                  Collateral / Security
                </label>
                <input
                  type="text"
                  placeholder="e.g. Delivery vehicle, workshop machinery, personal guarantor..."
                  value={appForm.collateral}
                  onChange={(e) => setAppForm({ ...appForm, collateral: e.target.value })}
                  className="w-full px-3 py-2 bg-[#162244] border border-[#1E2D5A] rounded-lg text-xs text-white focus:outline-hidden focus:border-blue-500"
                />
              </div>

              <button
                type="submit"
                className="w-full py-2.5 bg-blue-600 hover:bg-blue-500 text-white font-bold text-xs rounded-lg shadow-sm transition-colors"
              >
                Submit Loan Application for Review
              </button>
            </form>
          </div>

          {/* Real-time Schedule Simulation */}
          <div className="bg-[#111C38] border border-[#1E2D5A] rounded-xl p-5 space-y-4 flex flex-col justify-between">
            <div>
              <h3 className="text-sm font-bold text-white flex items-center justify-between border-b border-[#1E2D5A] pb-3">
                <span className="flex items-center gap-2">
                  <Calendar className="w-4 h-4 text-emerald-400" />
                  Simulated Amortization Schedule
                </span>
                <span className="text-[11px] text-slate-400">
                  {previewSchedule.length} Installment(s)
                </span>
              </h3>

              {/* Summary KPIs */}
              <div className="grid grid-cols-3 gap-2 my-3 text-xs">
                <div className="p-2.5 bg-[#0B1329] border border-[#1E2D5A] rounded-lg text-center">
                  <p className="text-[10px] text-slate-400 uppercase">Principal</p>
                  <p className="font-bold text-white">{formatMoney(previewTotals.principal)}</p>
                </div>
                <div className="p-2.5 bg-[#0B1329] border border-[#1E2D5A] rounded-lg text-center">
                  <p className="text-[10px] text-slate-400 uppercase">Total Interest</p>
                  <p className="font-bold text-emerald-400">{formatMoney(previewTotals.interest)}</p>
                </div>
                <div className="p-2.5 bg-[#0B1329] border border-[#1E2D5A] rounded-lg text-center">
                  <p className="text-[10px] text-slate-400 uppercase">Total Repayment</p>
                  <p className="font-bold text-blue-400">{formatMoney(previewTotals.total)}</p>
                </div>
              </div>

              {/* Table */}
              <div className="overflow-x-auto max-h-80 overflow-y-auto border border-[#1E2D5A] rounded-lg">
                <table className="w-full text-left text-[11px]">
                  <thead className="bg-[#0B1329] text-slate-400 uppercase text-[9px] tracking-wider sticky top-0 border-b border-[#1E2D5A]">
                    <tr>
                      <th className="px-3 py-2">#</th>
                      <th className="px-3 py-2">Due Date</th>
                      <th className="px-3 py-2">Principal</th>
                      <th className="px-3 py-2">Interest</th>
                      <th className="px-3 py-2">Installment</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#1E2D5A]">
                    {previewSchedule.map((row) => (
                      <tr key={row.installmentNo} className="hover:bg-slate-800/30">
                        <td className="px-3 py-2 font-mono font-bold text-blue-400">
                          {row.installmentNo}
                        </td>
                        <td className="px-3 py-2 font-mono text-slate-300">{row.dueDate}</td>
                        <td className="px-3 py-2 text-slate-200">{formatMoney(row.principalDue)}</td>
                        <td className="px-3 py-2 text-emerald-400">
                          {formatMoney(row.interestDue)}
                        </td>
                        <td className="px-3 py-2 font-bold text-white">
                          {formatMoney(row.totalDue)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            <div className="text-[11px] text-slate-400 italic bg-[#0B1329] p-3 rounded-lg border border-[#1E2D5A]">
              Note: The first installment date will automatically default to the next period
              following disbursement date, with waterfall allocation enforcing penalty, interest,
              then principal payments.
            </div>
          </div>
        </div>
      )}

      {/* SUBTAB 3: APPROVALS QUEUE */}
      {activeSubTab === 'approvals' && (
        <div className="bg-[#111C38] border border-[#1E2D5A] rounded-xl overflow-hidden">
          <div className="px-5 py-3.5 border-b border-[#1E2D5A]">
            <h3 className="text-sm font-bold text-white">
              Underwriting & Approvals Queue ({pendingApprovalLoans.length})
            </h3>
            <p className="text-xs text-slate-400">
              Review credit risk, borrower capacity, collateral, and decide on application approval.
            </p>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-[#0B1329] text-slate-400 uppercase text-[10px] tracking-wider border-b border-[#1E2D5A]">
                <tr>
                  <th className="px-4 py-3">Loan #</th>
                  <th className="px-4 py-3">Borrower</th>
                  <th className="px-4 py-3">Principal</th>
                  <th className="px-4 py-3">Term & Rate</th>
                  <th className="px-4 py-3">Purpose & Collateral</th>
                  <th className="px-4 py-3 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#1E2D5A]">
                {pendingApprovalLoans.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="px-4 py-12 text-center text-slate-500 text-xs">
                      No loan applications pending approval.
                    </td>
                  </tr>
                ) : (
                  pendingApprovalLoans.map((l) => {
                    const client = clients.find((c) => c.id === l.clientId);
                    return (
                      <tr key={l.id} className="hover:bg-slate-800/40 transition-colors">
                        <td className="px-4 py-3 font-mono font-bold text-blue-400">{l.loanNo}</td>
                        <td className="px-4 py-3">
                          <p className="font-semibold text-white">
                            {client ? `${client.firstName} ${client.lastName}` : `Client #${l.clientId}`}
                          </p>
                          <p className="text-[11px] text-slate-400">
                            Income: {formatMoney(client?.averageIncome)}/mo
                          </p>
                        </td>
                        <td className="px-4 py-3 font-bold text-white">
                          {formatMoney(l.principal)}
                        </td>
                        <td className="px-4 py-3 text-slate-300">
                          {l.termMonths} {l.repaymentFrequency} @ {l.interestRate}%
                        </td>
                        <td className="px-4 py-3 text-slate-300 max-w-xs truncate">
                          <p className="truncate">{l.purpose || 'General business'}</p>
                          <p className="text-[10px] text-slate-400 truncate">
                            Sec: {l.collateral || 'Guarantor'}
                          </p>
                        </td>
                        <td className="px-4 py-3 text-right space-x-2">
                          <button
                            onClick={() => approveLoan(l.id)}
                            className="px-3 py-1.5 bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg text-xs font-semibold shadow-xs transition-colors inline-flex items-center gap-1"
                          >
                            <CheckCircle className="w-3.5 h-3.5" />
                            Approve
                          </button>
                          <button
                            onClick={() => declineLoan(l.id, 'Declined by credit committee')}
                            className="px-3 py-1.5 bg-rose-600/80 hover:bg-rose-600 text-white rounded-lg text-xs font-semibold transition-colors inline-flex items-center gap-1"
                          >
                            <XCircle className="w-3.5 h-3.5" />
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
        <div className="bg-[#111C38] border border-[#1E2D5A] rounded-xl overflow-hidden">
          <div className="px-5 py-3.5 border-b border-[#1E2D5A]">
            <h3 className="text-sm font-bold text-white">
              Approved Loans Ready for Disbursement ({approvedLoansAwaitingDisbursement.length})
            </h3>
            <p className="text-xs text-slate-400">
              Payout authorized loans, generate repayment schedules, and post double-entry general ledger records.
            </p>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-[#0B1329] text-slate-400 uppercase text-[10px] tracking-wider border-b border-[#1E2D5A]">
                <tr>
                  <th className="px-4 py-3">Loan #</th>
                  <th className="px-4 py-3">Borrower</th>
                  <th className="px-4 py-3">Approved Principal</th>
                  <th className="px-4 py-3">Approved Date</th>
                  <th className="px-4 py-3">Admin Fee</th>
                  <th className="px-4 py-3 text-right">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#1E2D5A]">
                {approvedLoansAwaitingDisbursement.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="px-4 py-12 text-center text-slate-500 text-xs">
                      No approved loans waiting for disbursement.
                    </td>
                  </tr>
                ) : (
                  approvedLoansAwaitingDisbursement.map((l) => {
                    const client = clients.find((c) => c.id === l.clientId);
                    return (
                      <tr key={l.id} className="hover:bg-slate-800/40 transition-colors">
                        <td className="px-4 py-3 font-mono font-bold text-blue-400">{l.loanNo}</td>
                        <td className="px-4 py-3 font-semibold text-white">
                          {client ? `${client.firstName} ${client.lastName}` : `Client #${l.clientId}`}
                        </td>
                        <td className="px-4 py-3 font-bold text-white">
                          {formatMoney(l.principal)}
                        </td>
                        <td className="px-4 py-3 font-mono text-slate-400">{l.approvedAt}</td>
                        <td className="px-4 py-3 text-emerald-400 font-semibold">
                          {formatMoney(l.adminFee)}
                        </td>
                        <td className="px-4 py-3 text-right">
                          <button
                            onClick={() => handleOpenDisburse(l)}
                            className="px-3.5 py-1.5 bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg text-xs font-semibold shadow-xs transition-colors inline-flex items-center gap-1"
                          >
                            <Banknote className="w-3.5 h-3.5" />
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
          <div className="bg-[#111C38] border border-[#1E2D5A] rounded-xl p-5 space-y-4">
            <h3 className="text-sm font-bold text-white flex items-center gap-2">
              <ArrowDownLeft className="w-4 h-4 text-emerald-400" />
              Record Repayment
            </h3>

            {repaymentMessage && (
              <div
                className={`p-3 rounded-lg text-xs border ${
                  repaymentMessage.type === 'success'
                    ? 'bg-emerald-950/60 border-emerald-800 text-emerald-300'
                    : 'bg-rose-950/60 border-rose-800 text-rose-300'
                }`}
              >
                {repaymentMessage.text}
              </div>
            )}

            <form onSubmit={handleExecuteRepayment} className="space-y-4">
              <div>
                <label className="block text-xs font-semibold text-slate-300 mb-1">
                  Select Active Loan *
                </label>
                <select
                  value={repaymentForm.loanId}
                  onChange={(e) =>
                    setRepaymentForm({ ...repaymentForm, loanId: Number(e.target.value) })
                  }
                  className="w-full px-3 py-2 bg-[#162244] border border-[#1E2D5A] rounded-lg text-xs text-white focus:outline-hidden focus:border-blue-500"
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
                  <label className="block text-xs font-semibold text-slate-300 mb-1">
                    Repayment Amount ($) *
                  </label>
                  <input
                    type="number"
                    step="any"
                    required
                    placeholder="0.00"
                    value={repaymentForm.amount}
                    onChange={(e) => setRepaymentForm({ ...repaymentForm, amount: e.target.value })}
                    className="w-full px-3 py-2 bg-[#162244] border border-[#1E2D5A] rounded-lg text-xs text-white font-bold focus:outline-hidden focus:border-blue-500"
                  />
                </div>
                <div>
                  <label className="block text-xs font-semibold text-slate-300 mb-1">Payment Date *</label>
                  <input
                    type="date"
                    required
                    value={repaymentForm.date}
                    onChange={(e) => setRepaymentForm({ ...repaymentForm, date: e.target.value })}
                    className="w-full px-3 py-2 bg-[#162244] border border-[#1E2D5A] rounded-lg text-xs text-white font-mono focus:outline-hidden focus:border-blue-500"
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-semibold text-slate-300 mb-1">Payment Method</label>
                  <select
                    value={repaymentForm.method}
                    onChange={(e) =>
                      setRepaymentForm({
                        ...repaymentForm,
                        method: e.target.value as Repayment['method'],
                      })
                    }
                    className="w-full px-3 py-2 bg-[#162244] border border-[#1E2D5A] rounded-lg text-xs text-white focus:outline-hidden focus:border-blue-500"
                  >
                    <option value="Cash">Cash at Counter</option>
                    <option value="Bank Transfer">Bank Transfer</option>
                    <option value="Mobile Money">Mobile Money (EcoCash/OneMoney)</option>
                    <option value="Other">Other</option>
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-semibold text-slate-300 mb-1">
                    Receipt / Reference #
                  </label>
                  <input
                    type="text"
                    placeholder="e.g. REC-88219"
                    value={repaymentForm.reference}
                    onChange={(e) =>
                      setRepaymentForm({ ...repaymentForm, reference: e.target.value })
                    }
                    className="w-full px-3 py-2 bg-[#162244] border border-[#1E2D5A] rounded-lg text-xs text-white font-mono focus:outline-hidden focus:border-blue-500"
                  />
                </div>
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-300 mb-1">Notes / Memo</label>
                <input
                  type="text"
                  placeholder="Optional teller notes"
                  value={repaymentForm.notes}
                  onChange={(e) => setRepaymentForm({ ...repaymentForm, notes: e.target.value })}
                  className="w-full px-3 py-2 bg-[#162244] border border-[#1E2D5A] rounded-lg text-xs text-white focus:outline-hidden focus:border-blue-500"
                />
              </div>

              <button
                type="submit"
                className="w-full py-2.5 bg-emerald-600 hover:bg-emerald-500 text-white font-bold text-xs rounded-lg shadow-sm transition-colors"
              >
                Execute Waterfall Allocation & Post Journal
              </button>
            </form>
          </div>

          {/* Waterfall Allocation Explanation & Rules */}
          <div className="bg-[#111C38] border border-[#1E2D5A] rounded-xl p-5 space-y-4">
            <h3 className="text-sm font-bold text-white flex items-center gap-2 border-b border-[#1E2D5A] pb-3">
              <AlertCircle className="w-4 h-4 text-blue-400" />
              Statutory Waterfall Allocation Rules
            </h3>

            <div className="space-y-3 text-xs text-slate-300">
              <p>
                In strict adherence to microfinance banking regulations, all received funds are
                applied according to the following chronological waterfall priority across pending
                installments:
              </p>

              <div className="p-3 bg-[#0B1329] rounded-lg border border-[#1E2D5A] space-y-2">
                <div className="flex items-center gap-2">
                  <span className="w-5 h-5 rounded-full bg-rose-600/30 text-rose-400 font-bold flex items-center justify-center text-[10px]">
                    1
                  </span>
                  <span className="font-semibold text-white">Default Penalties & Late Fees</span>
                </div>
                <p className="text-[11px] text-slate-400 pl-7">
                  Any outstanding delinquency penalties charged on overdue installments are settled first.
                </p>

                <div className="flex items-center gap-2">
                  <span className="w-5 h-5 rounded-full bg-amber-600/30 text-amber-400 font-bold flex items-center justify-center text-[10px]">
                    2
                  </span>
                  <span className="font-semibold text-white">Earned Interest Income</span>
                </div>
                <p className="text-[11px] text-slate-400 pl-7">
                  Accrued interest across due installments is recognized and credited to general ledger Account 4000.
                </p>

                <div className="flex items-center gap-2">
                  <span className="w-5 h-5 rounded-full bg-emerald-600/30 text-emerald-400 font-bold flex items-center justify-center text-[10px]">
                    3
                  </span>
                  <span className="font-semibold text-white">Principal Balance Reduction</span>
                </div>
                <p className="text-[11px] text-slate-400 pl-7">
                  Remaining funds reduce the loan asset principal (Account 1100). If the entire loan schedule reaches zero balance, the loan status automatically updates to Closed.
                </p>
              </div>

              <div className="p-3 bg-blue-950/40 border border-blue-800/60 rounded-lg text-[11px] text-blue-300">
                Double-entry balancing is automatically enforced. Cash and Bank (1000) is debited for
                the gross payment received, with offsetting credits to Principal, Interest, and Penalty
                revenue ledgers.
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Disburse Loan Modal */}
      <Modal
        isOpen={disburseModalOpen}
        onClose={() => setDisburseModalOpen(false)}
        title={`Disburse Loan: ${disburseTargetLoan?.loanNo}`}
        maxWidth="md"
      >
        <form onSubmit={handleConfirmDisbursement} className="space-y-4">
          <div className="p-3 bg-[#0B1329] border border-[#1E2D5A] rounded-lg text-xs space-y-1">
            <p className="text-slate-400">
              Borrower:{' '}
              <span className="text-white font-semibold">
                {clients.find((c) => c.id === disburseTargetLoan?.clientId)?.firstName}{' '}
                {clients.find((c) => c.id === disburseTargetLoan?.clientId)?.lastName}
              </span>
            </p>
            <p className="text-slate-400">
              Disbursement Amount:{' '}
              <span className="text-emerald-400 font-bold text-sm">
                {formatMoney(disburseTargetLoan?.principal)}
              </span>
            </p>
            {disburseTargetLoan && disburseTargetLoan.adminFee > 0 && (
              <p className="text-slate-400">
                Admin Fee Recognized:{' '}
                <span className="text-blue-400 font-semibold">
                  {formatMoney(disburseTargetLoan.adminFee)}
                </span>
              </p>
            )}
          </div>

          <div>
            <label className="block text-xs font-semibold text-slate-300 mb-1">
              Disbursement Date *
            </label>
            <input
              type="date"
              required
              value={disburseForm.date}
              onChange={(e) => setDisburseForm({ ...disburseForm, date: e.target.value })}
              className="w-full px-3 py-2 bg-[#162244] border border-[#1E2D5A] rounded-lg text-xs text-white font-mono focus:outline-hidden focus:border-blue-500"
            />
          </div>

          <div>
            <label className="block text-xs font-semibold text-slate-300 mb-1">
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
              className="w-full px-3 py-2 bg-[#162244] border border-[#1E2D5A] rounded-lg text-xs text-white focus:outline-hidden focus:border-blue-500"
            >
              <option value="Bank Transfer">Bank Transfer (RTGS / ZIPIT / EFT)</option>
              <option value="Cash">Cash Payout</option>
              <option value="Mobile Money">Mobile Money (EcoCash)</option>
            </select>
          </div>

          <div>
            <label className="block text-xs font-semibold text-slate-300 mb-1">
              Transaction Reference / Voucher #
            </label>
            <input
              type="text"
              value={disburseForm.reference}
              onChange={(e) => setDisburseForm({ ...disburseForm, reference: e.target.value })}
              className="w-full px-3 py-2 bg-[#162244] border border-[#1E2D5A] rounded-lg text-xs text-white font-mono focus:outline-hidden focus:border-blue-500"
            />
          </div>

          <div className="flex justify-end gap-2 pt-2 border-t border-[#1E2D5A]">
            <button
              type="button"
              onClick={() => setDisburseModalOpen(false)}
              className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-xs font-semibold transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              className="px-4 py-2 bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg text-xs font-semibold shadow-xs transition-colors"
            >
              Confirm Disbursement
            </button>
          </div>
        </form>
      </Modal>
    </div>
  );
};
