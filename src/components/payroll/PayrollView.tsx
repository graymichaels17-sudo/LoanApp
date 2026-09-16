import React, { useState, useMemo } from 'react';
import {
  Receipt,
  UserPlus,
  Printer,
  CheckCircle2,
  FileText,
  Building,
} from 'lucide-react';
import { useApp } from '../../context/AppContext';
import { Payslip } from '../../types';
import { formatMoney, roundMoney } from '../../utils/money';
import { Header } from '../common/Header';
import { Modal } from '../common/Modal';

export const PayrollView: React.FC = () => {
  const { employees, addEmployee, addJournalEntry, systemDate } = useApp();

  const [activeSubTab, setActiveSubTab] = useState<'run' | 'employees'>('run');
  const [selectedMonth, setSelectedMonth] = useState('2026-09');

  // Employee Modal
  const [empModalOpen, setEmpModalOpen] = useState(false);
  const [empForm, setEmpForm] = useState({
    employeeNo: '',
    firstName: '',
    lastName: '',
    nationalId: '',
    jobTitle: '',
    department: '',
    dateHired: systemDate,
    basicSalary: '800',
    bankName: 'Stanbic Bank',
    bankAccountNo: '',
    nssaNumber: '',
    taxNumber: '',
  });

  // Payslip Modal State
  const [selectedPayslip, setSelectedPayslip] = useState<Payslip | null>(null);
  const [payslipModalOpen, setPayslipModalOpen] = useState(false);

  // Compute statutory payroll for all active employees
  // Standard statutory formulas (Zimbabwe PAYE + NSSA + AIDS Levy):
  // NSSA = 4.5% of basic salary capped at $700 = max $31.50
  // PAYE: 0% up to $100; 20% on $101-$300; 25% on $301-$600; 30% above $600
  // AIDS Levy = 3% of PAYE tax
  const payslips = useMemo<Payslip[]>(() => {
    return employees
      .filter((e) => e.active)
      .map((emp) => {
        const basic = emp.basicSalary;
        const gross = basic;

        // NSSA calculation
        const nssaInsurableCeiling = 700;
        const nssaDeduction = roundMoney(Math.min(basic, nssaInsurableCeiling) * 0.045);

        // PAYE Tax calculation on taxable income (basic - NSSA)
        const taxable = Math.max(0, basic - nssaDeduction);
        let paye = 0;
        if (taxable > 600) {
          paye = 0 + 200 * 0.2 + 300 * 0.25 + (taxable - 600) * 0.3;
        } else if (taxable > 300) {
          paye = 0 + 200 * 0.2 + (taxable - 300) * 0.25;
        } else if (taxable > 100) {
          paye = (taxable - 100) * 0.2;
        }
        paye = roundMoney(paye);

        // AIDS Levy
        const aidsLevy = roundMoney(paye * 0.03);

        const totalDeductions = roundMoney(nssaDeduction + paye + aidsLevy);
        const netPay = roundMoney(gross - totalDeductions);

        return {
          id: emp.id,
          payrollPeriodId: 1,
          employeeId: emp.id,
          periodMonth: selectedMonth,
          basicSalary: basic,
          allowances: 0,
          grossPay: gross,
          grossSalary: gross,
          taxableIncome: taxable,
          nssaInsurable: Math.min(basic, nssaInsurableCeiling),
          paye,
          payeTax: paye,
          aidsLevy,
          nssaEmployee: nssaDeduction,
          nssaDeduction,
          nssaEmployer: nssaDeduction,
          zimdefEmployer: roundMoney(gross * 0.01),
          otherDeductions: 0,
          totalDeductions,
          netPay,
          netSalary: netPay,
          generatedDate: systemDate,
        };
      });
  }, [employees, selectedMonth, systemDate]);

  const payrollTotals = useMemo(() => {
    const gross = payslips.reduce((s, p) => s + (p.grossSalary ?? p.grossPay ?? 0), 0);
    const paye = payslips.reduce((s, p) => s + (p.payeTax ?? p.paye ?? 0), 0);
    const nssa = payslips.reduce((s, p) => s + (p.nssaDeduction ?? p.nssaEmployee ?? 0), 0);
    const aids = payslips.reduce((s, p) => s + (p.aidsLevy ?? 0), 0);
    const net = payslips.reduce((s, p) => s + (p.netSalary ?? p.netPay ?? 0), 0);

    return {
      gross: roundMoney(gross),
      paye: roundMoney(paye),
      nssa: roundMoney(nssa),
      aids: roundMoney(aids),
      net: roundMoney(net),
      totalDeductions: roundMoney(paye + nssa + aids),
    };
  }, [payslips]);

  const handleCreateEmployee = (e: React.FormEvent) => {
    e.preventDefault();
    const sal = parseFloat(empForm.basicSalary) || 0;
    const nextNo = `EMP-${String(employees.length + 1).padStart(3, '0')}`;

    addEmployee({
      employeeNo: empForm.employeeNo.trim() || nextNo,
      firstName: empForm.firstName.trim(),
      lastName: empForm.lastName.trim(),
      nationalId: empForm.nationalId.trim(),
      jobTitle: empForm.jobTitle.trim(),
      department: empForm.department.trim(),
      dateHired: empForm.dateHired,
      basicSalary: sal,
      bankName: empForm.bankName.trim(),
      bankAccountNo: empForm.bankAccountNo.trim(),
      nssaNumber: empForm.nssaNumber.trim(),
      taxNumber: empForm.taxNumber.trim(),
      active: true,
    });

    setEmpModalOpen(false);
  };

  const handlePostPayrollToLedger = () => {
    // Debit: Salaries and Wages Expense (5100) -> Gross
    // Credit: PAYE Payable (2100)
    // Credit: NSSA Payable (2150)
    // Credit: AIDS Levy Payable (2160)
    // Credit: Cash and Bank (1000) -> Net Pay
    const ref = `PR-${selectedMonth}`;
    const ok = addJournalEntry({
      entryDate: systemDate,
      reference: ref,
      sourceType: 'payroll',
      description: `Payroll run for period ${selectedMonth} (${payslips.length} staff)`,
      lines: [
        {
          id: 1,
          journalEntryId: 0,
          accountId: 17, // Salaries & Wages Expense
          debit: payrollTotals.gross,
          credit: 0,
          memo: `Gross payroll liability for ${selectedMonth}`,
        },
        {
          id: 2,
          journalEntryId: 0,
          accountId: 6, // PAYE Payable
          debit: 0,
          credit: payrollTotals.paye,
          memo: `Statutory PAYE withholding`,
        },
        {
          id: 3,
          journalEntryId: 0,
          accountId: 7, // NSSA Payable
          debit: 0,
          credit: payrollTotals.nssa,
          memo: `Statutory social security pension`,
        },
        {
          id: 4,
          journalEntryId: 0,
          accountId: 8, // AIDS Levy Payable
          debit: 0,
          credit: payrollTotals.aids,
          memo: `Statutory AIDS levy (3% of PAYE)`,
        },
        {
          id: 5,
          journalEntryId: 0,
          accountId: 1, // Cash and Bank
          debit: 0,
          credit: payrollTotals.net,
          memo: `Net salary payout via bank direct credit`,
        },
      ],
    });

    if (ok) {
      alert(`Payroll for ${selectedMonth} successfully posted to General Ledger! (Ref: ${ref})`);
    }
  };

  const openPayslip = (payslip: Payslip) => {
    setSelectedPayslip(payslip);
    setPayslipModalOpen(true);
  };

  const selectedPayslipEmployee = selectedPayslip
    ? employees.find((e) => e.id === selectedPayslip.employeeId)
    : null;

  return (
    <div id="payroll-view" className="space-y-6">
      <Header
        title="Staff Payroll & Statutory Remittances"
        subtitle="Compute monthly gross pay, PAYE tax bands, NSSA social security, AIDS levy, and generate payslips"
        actions={
          <div className="flex items-center gap-2">
            <button
              id="btn-add-employee"
              onClick={() => setEmpModalOpen(true)}
              className="flex items-center gap-1.5 px-3 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-xs font-semibold shadow-xs transition-colors"
            >
              <UserPlus className="w-4 h-4" />
              Add Employee
            </button>
            <button
              id="btn-post-payroll"
              onClick={handlePostPayrollToLedger}
              className="flex items-center gap-1.5 px-3 py-2 bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg text-xs font-semibold shadow-xs transition-colors"
            >
              <CheckCircle2 className="w-4 h-4" />
              Post Payroll to Ledger
            </button>
          </div>
        }
      />

      {/* Sub-tabs */}
      <div className="flex items-center gap-2 border-b border-slate-800 pb-2 text-xs font-semibold">
        <button
          onClick={() => setActiveSubTab('run')}
          className={`px-3.5 py-2 rounded-lg flex items-center gap-2 transition-colors ${
            activeSubTab === 'run'
              ? 'bg-blue-600 text-white'
              : 'text-slate-400 hover:text-white hover:bg-slate-800/60'
          }`}
        >
          <Receipt className="w-4 h-4" />
          Monthly Payroll Run
        </button>

        <button
          onClick={() => setActiveSubTab('employees')}
          className={`px-3.5 py-2 rounded-lg flex items-center gap-2 transition-colors ${
            activeSubTab === 'employees'
              ? 'bg-blue-600 text-white'
              : 'text-slate-400 hover:text-white hover:bg-slate-800/60'
          }`}
        >
          <Building className="w-4 h-4" />
          Employee Directory ({employees.length})
        </button>
      </div>

      {/* SUBTAB 1: MONTHLY PAYROLL RUN */}
      {activeSubTab === 'run' && (
        <div className="space-y-6">
          {/* Month Selector & KPI Cards */}
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
            <div className="flex items-center gap-2 text-xs">
              <span className="text-slate-300 font-semibold">Payroll Period:</span>
              <input
                type="month"
                value={selectedMonth}
                onChange={(e) => setSelectedMonth(e.target.value)}
                className="px-3 py-1.5 bg-[#111C38] border border-[#1E2D5A] rounded-lg text-xs text-white font-mono focus:outline-hidden focus:border-blue-500"
              />
            </div>
            <span className="text-xs text-slate-400">
              {payslips.length} active staff scheduled for disbursement
            </span>
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            <div className="p-4 bg-[#111C38] border border-[#1E2D5A] rounded-xl space-y-1">
              <p className="text-xs text-slate-400">Total Gross Salaries</p>
              <p className="text-xl font-bold text-white tracking-tight">
                {formatMoney(payrollTotals.gross)}
              </p>
              <p className="text-[10px] text-slate-500">Account 5100</p>
            </div>

            <div className="p-4 bg-[#111C38] border border-[#1E2D5A] rounded-xl space-y-1">
              <p className="text-xs text-slate-400">Total PAYE Withheld</p>
              <p className="text-xl font-bold text-amber-400 tracking-tight">
                {formatMoney(payrollTotals.paye)}
              </p>
              <p className="text-[10px] text-slate-500">Account 2100</p>
            </div>

            <div className="p-4 bg-[#111C38] border border-[#1E2D5A] rounded-xl space-y-1">
              <p className="text-xs text-slate-400">NSSA &amp; AIDS Levy</p>
              <p className="text-xl font-bold text-purple-400 tracking-tight">
                {formatMoney(payrollTotals.nssa + payrollTotals.aids)}
              </p>
              <p className="text-[10px] text-slate-500">Statutory remittances</p>
            </div>

            <div className="p-4 bg-[#111C38] border border-emerald-600/40 rounded-xl space-y-1 bg-emerald-950/20">
              <p className="text-xs text-emerald-400 font-semibold">Net Payout to Bank</p>
              <p className="text-xl font-bold text-emerald-300 tracking-tight">
                {formatMoney(payrollTotals.net)}
              </p>
              <p className="text-[10px] text-slate-400">Direct credit</p>
            </div>
          </div>

          {/* Payslips Table */}
          <div className="bg-[#111C38] border border-[#1E2D5A] rounded-xl overflow-hidden">
            <div className="px-5 py-3.5 border-b border-[#1E2D5A] flex items-center justify-between">
              <h3 className="text-sm font-bold text-white">Payroll Schedule Breakdown</h3>
              <span className="text-[11px] text-slate-400">Click &quot;Payslip&quot; to preview or print</span>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="bg-[#0B1329] text-slate-400 uppercase text-[10px] tracking-wider border-b border-[#1E2D5A]">
                  <tr>
                    <th className="px-4 py-3">Emp #</th>
                    <th className="px-4 py-3">Employee Name</th>
                    <th className="px-4 py-3">Designation</th>
                    <th className="px-4 py-3">Gross Salary</th>
                    <th className="px-4 py-3">PAYE Tax</th>
                    <th className="px-4 py-3">NSSA</th>
                    <th className="px-4 py-3">AIDS Levy</th>
                    <th className="px-4 py-3">Net Pay</th>
                    <th className="px-4 py-3 text-right">Action</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#1E2D5A]">
                  {payslips.map((p) => {
                    const emp = employees.find((e) => e.id === p.employeeId);
                    return (
                      <tr key={p.id} className="hover:bg-slate-800/40 transition-colors">
                        <td className="px-4 py-3 font-mono font-bold text-blue-400">
                          {emp?.employeeNo}
                        </td>
                        <td className="px-4 py-3 font-semibold text-white">
                          {emp ? `${emp.firstName} ${emp.lastName}` : '-'}
                        </td>
                        <td className="px-4 py-3 text-slate-400">{emp?.jobTitle}</td>
                        <td className="px-4 py-3 font-semibold text-white">
                          {formatMoney(p.grossSalary)}
                        </td>
                        <td className="px-4 py-3 text-amber-400 font-mono">
                          {formatMoney(p.payeTax)}
                        </td>
                        <td className="px-4 py-3 text-purple-400 font-mono">
                          {formatMoney(p.nssaDeduction)}
                        </td>
                        <td className="px-4 py-3 text-rose-400 font-mono">
                          {formatMoney(p.aidsLevy)}
                        </td>
                        <td className="px-4 py-3 font-bold text-emerald-400">
                          {formatMoney(p.netSalary)}
                        </td>
                        <td className="px-4 py-3 text-right">
                          <button
                            onClick={() => openPayslip(p)}
                            className="px-2.5 py-1 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-md text-[11px] font-semibold transition-colors inline-flex items-center gap-1 border border-slate-700"
                          >
                            <FileText className="w-3 h-3 text-blue-400" />
                            Payslip
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* SUBTAB 2: EMPLOYEE DIRECTORY */}
      {activeSubTab === 'employees' && (
        <div className="bg-[#111C38] border border-[#1E2D5A] rounded-xl overflow-hidden">
          <div className="px-5 py-3.5 border-b border-[#1E2D5A]">
            <h3 className="text-sm font-bold text-white">Registered Staff Directory</h3>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-[#0B1329] text-slate-400 uppercase text-[10px] tracking-wider border-b border-[#1E2D5A]">
                <tr>
                  <th className="px-4 py-3">Emp #</th>
                  <th className="px-4 py-3">Name</th>
                  <th className="px-4 py-3">National ID</th>
                  <th className="px-4 py-3">Job Title</th>
                  <th className="px-4 py-3">Department</th>
                  <th className="px-4 py-3">Basic Salary</th>
                  <th className="px-4 py-3">Bank Details</th>
                  <th className="px-4 py-3">NSSA #</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#1E2D5A]">
                {employees.map((e) => (
                  <tr key={e.id} className="hover:bg-slate-800/40 transition-colors">
                    <td className="px-4 py-3 font-mono font-bold text-blue-400">{e.employeeNo}</td>
                    <td className="px-4 py-3 font-semibold text-white">
                      {e.firstName} {e.lastName}
                    </td>
                    <td className="px-4 py-3 font-mono text-slate-400 text-[11px]">{e.nationalId}</td>
                    <td className="px-4 py-3 text-slate-300">{e.jobTitle}</td>
                    <td className="px-4 py-3 text-slate-400">{e.department}</td>
                    <td className="px-4 py-3 font-bold text-white">
                      {formatMoney(e.basicSalary)}
                    </td>
                    <td className="px-4 py-3 text-slate-300">
                      <p>{e.bankName}</p>
                      <p className="text-[10px] font-mono text-slate-500">{e.bankAccountNo}</p>
                    </td>
                    <td className="px-4 py-3 font-mono text-slate-400 text-[11px]">
                      {e.nssaNumber || '-'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Add Employee Modal */}
      <Modal
        isOpen={empModalOpen}
        onClose={() => setEmpModalOpen(false)}
        title="Add Employee to Payroll"
        maxWidth="lg"
      >
        <form onSubmit={handleCreateEmployee} className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1">First Name *</label>
              <input
                type="text"
                required
                value={empForm.firstName}
                onChange={(e) => setEmpForm({ ...empForm, firstName: e.target.value })}
                className="w-full px-3 py-2 bg-[#162244] border border-[#1E2D5A] rounded-lg text-xs text-white focus:outline-hidden focus:border-blue-500"
              />
            </div>
            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1">Last Name *</label>
              <input
                type="text"
                required
                value={empForm.lastName}
                onChange={(e) => setEmpForm({ ...empForm, lastName: e.target.value })}
                className="w-full px-3 py-2 bg-[#162244] border border-[#1E2D5A] rounded-lg text-xs text-white focus:outline-hidden focus:border-blue-500"
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1">
                National ID Number *
              </label>
              <input
                type="text"
                required
                placeholder="63-000000-X-00"
                value={empForm.nationalId}
                onChange={(e) => setEmpForm({ ...empForm, nationalId: e.target.value })}
                className="w-full px-3 py-2 bg-[#162244] border border-[#1E2D5A] rounded-lg text-xs text-white font-mono focus:outline-hidden focus:border-blue-500"
              />
            </div>
            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1">
                Basic Monthly Salary ($) *
              </label>
              <input
                type="number"
                step="any"
                required
                value={empForm.basicSalary}
                onChange={(e) => setEmpForm({ ...empForm, basicSalary: e.target.value })}
                className="w-full px-3 py-2 bg-[#162244] border border-[#1E2D5A] rounded-lg text-xs text-white font-bold focus:outline-hidden focus:border-blue-500"
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1">Job Title</label>
              <input
                type="text"
                value={empForm.jobTitle}
                onChange={(e) => setEmpForm({ ...empForm, jobTitle: e.target.value })}
                className="w-full px-3 py-2 bg-[#162244] border border-[#1E2D5A] rounded-lg text-xs text-white focus:outline-hidden focus:border-blue-500"
              />
            </div>
            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1">Department</label>
              <input
                type="text"
                value={empForm.department}
                onChange={(e) => setEmpForm({ ...empForm, department: e.target.value })}
                className="w-full px-3 py-2 bg-[#162244] border border-[#1E2D5A] rounded-lg text-xs text-white focus:outline-hidden focus:border-blue-500"
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4 border-t border-[#1E2D5A] pt-3">
            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1">Bank Name</label>
              <input
                type="text"
                value={empForm.bankName}
                onChange={(e) => setEmpForm({ ...empForm, bankName: e.target.value })}
                className="w-full px-3 py-2 bg-[#162244] border border-[#1E2D5A] rounded-lg text-xs text-white focus:outline-hidden focus:border-blue-500"
              />
            </div>
            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1">
                Bank Account Number
              </label>
              <input
                type="text"
                value={empForm.bankAccountNo}
                onChange={(e) => setEmpForm({ ...empForm, bankAccountNo: e.target.value })}
                className="w-full px-3 py-2 bg-[#162244] border border-[#1E2D5A] rounded-lg text-xs text-white font-mono focus:outline-hidden focus:border-blue-500"
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1">
                NSSA Number
              </label>
              <input
                type="text"
                value={empForm.nssaNumber}
                onChange={(e) => setEmpForm({ ...empForm, nssaNumber: e.target.value })}
                className="w-full px-3 py-2 bg-[#162244] border border-[#1E2D5A] rounded-lg text-xs text-white font-mono focus:outline-hidden focus:border-blue-500"
              />
            </div>
            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1">TIN / Tax Number</label>
              <input
                type="text"
                value={empForm.taxNumber}
                onChange={(e) => setEmpForm({ ...empForm, taxNumber: e.target.value })}
                className="w-full px-3 py-2 bg-[#162244] border border-[#1E2D5A] rounded-lg text-xs text-white font-mono focus:outline-hidden focus:border-blue-500"
              />
            </div>
          </div>

          <div className="flex justify-end gap-2 pt-2 border-t border-[#1E2D5A]">
            <button
              type="button"
              onClick={() => setEmpModalOpen(false)}
              className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-xs font-semibold transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-xs font-semibold shadow-xs transition-colors"
            >
              Save Employee
            </button>
          </div>
        </form>
      </Modal>

      {/* Payslip View Modal */}
      <Modal
        isOpen={payslipModalOpen}
        onClose={() => setPayslipModalOpen(false)}
        title="Official Employee Payslip"
        maxWidth="md"
      >
        {selectedPayslip && selectedPayslipEmployee && (
          <div className="space-y-4 p-2 bg-[#0B1329] rounded-xl border border-[#1E2D5A] text-xs">
            {/* Header */}
            <div className="text-center border-b border-[#1E2D5A] pb-3 space-y-1">
              <h3 className="text-base font-bold text-white tracking-tight">
                MICROFINANCE MANAGER (PVT) LTD
              </h3>
              <p className="text-[11px] text-slate-400">
                Staff Confidential Remuneration Slip • Period: {selectedPayslip.periodMonth}
              </p>
            </div>

            {/* Employee Particulars */}
            <div className="grid grid-cols-2 gap-2 text-[11px]">
              <div>
                <p className="text-slate-400">Employee Name:</p>
                <p className="font-bold text-white">
                  {selectedPayslipEmployee.firstName} {selectedPayslipEmployee.lastName}
                </p>
              </div>
              <div>
                <p className="text-slate-400">Employee Number:</p>
                <p className="font-mono text-blue-400 font-bold">
                  {selectedPayslipEmployee.employeeNo}
                </p>
              </div>
              <div>
                <p className="text-slate-400">National ID:</p>
                <p className="font-mono text-slate-300">{selectedPayslipEmployee.nationalId}</p>
              </div>
              <div>
                <p className="text-slate-400">Designation:</p>
                <p className="text-slate-200">{selectedPayslipEmployee.jobTitle}</p>
              </div>
              <div>
                <p className="text-slate-400">Bank &amp; Account:</p>
                <p className="font-mono text-slate-300">
                  {selectedPayslipEmployee.bankName} - {selectedPayslipEmployee.bankAccountNo}
                </p>
              </div>
              <div>
                <p className="text-slate-400">NSSA Number:</p>
                <p className="font-mono text-slate-300">{selectedPayslipEmployee.nssaNumber || '-'}</p>
              </div>
            </div>

            {/* Earnings & Deductions Tables */}
            <div className="border-t border-[#1E2D5A] pt-3 space-y-2">
              <div className="flex justify-between font-semibold text-slate-200">
                <span>Basic Salary</span>
                <span className="font-mono">{formatMoney(selectedPayslip.basicSalary)}</span>
              </div>
              <div className="flex justify-between text-slate-400">
                <span>Allowances &amp; Benefits</span>
                <span className="font-mono">{formatMoney(selectedPayslip.allowances)}</span>
              </div>
              <div className="flex justify-between font-bold text-white border-t border-slate-800 pt-1">
                <span>Total Gross Earnings</span>
                <span className="font-mono text-blue-400">
                  {formatMoney(selectedPayslip.grossSalary)}
                </span>
              </div>
            </div>

            {/* Deductions */}
            <div className="border-t border-[#1E2D5A] pt-3 space-y-1.5 text-[11px]">
              <p className="font-bold uppercase text-slate-400 text-[10px]">Statutory Deductions</p>
              <div className="flex justify-between text-amber-300">
                <span>PAYE Income Tax</span>
                <span className="font-mono">-{formatMoney(selectedPayslip.payeTax)}</span>
              </div>
              <div className="flex justify-between text-purple-300">
                <span>NSSA Social Security</span>
                <span className="font-mono">-{formatMoney(selectedPayslip.nssaDeduction)}</span>
              </div>
              <div className="flex justify-between text-rose-300">
                <span>AIDS Levy (3% of PAYE)</span>
                <span className="font-mono">-{formatMoney(selectedPayslip.aidsLevy)}</span>
              </div>
              <div className="flex justify-between font-bold text-rose-400 border-t border-slate-800 pt-1">
                <span>Total Deductions</span>
                <span className="font-mono">
                  -{formatMoney(selectedPayslip.totalDeductions)}
                </span>
              </div>
            </div>

            {/* Net Payout Banner */}
            <div className="p-3 bg-[#111C38] border border-emerald-600/50 rounded-lg flex items-center justify-between">
              <div>
                <p className="text-[10px] uppercase font-bold text-emerald-400">Net Salary Payable</p>
                <p className="text-[10px] text-slate-400">Transferred via Bank Direct Credit</p>
              </div>
              <span className="text-lg font-extrabold text-emerald-400 font-mono">
                {formatMoney(selectedPayslip.netSalary)}
              </span>
            </div>

            <div className="flex justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={() => window.print()}
                className="px-3.5 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-lg text-xs font-semibold inline-flex items-center gap-1.5 border border-slate-700"
              >
                <Printer className="w-3.5 h-3.5" />
                Print Payslip
              </button>
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
};
