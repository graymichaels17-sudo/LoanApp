import React, { useState, useMemo } from 'react';
import {
  Scale,
  BookOpen,
  PlusCircle,
  Receipt,
  FileSpreadsheet,
  CheckCircle2,
  AlertCircle,
  TrendingDown,
} from 'lucide-react';
import { useApp } from '../../context/AppContext';
import { formatMoney, roundMoney } from '../../utils/money';
import { Header } from '../common/Header';
import { Modal } from '../common/Modal';

export const AccountingView: React.FC = () => {
  const {
    accounts,
    journalEntries,
    expenses,
    expenseCategories,
    systemDate,
    addExpense,
    addJournalEntry,
  } = useApp();

  const [activeTab, setActiveTab] = useState<'financials' | 'journal' | 'expenses' | 'coa'>('financials');
  const [statementType, setStatementType] = useState<'balance_sheet' | 'pnl' | 'trial_balance'>('balance_sheet');

  // Expense Modal State
  const [expenseModalOpen, setExpenseModalOpen] = useState(false);
  const [expenseForm, setExpenseForm] = useState({
    categoryId: expenseCategories[0]?.id || 1,
    date: systemDate,
    amount: '',
    paidTo: '',
    description: '',
    reference: '',
  });

  // Manual Journal Entry Modal State
  const [journalModalOpen, setJournalModalOpen] = useState(false);
  const [journalForm, setJournalForm] = useState({
    date: systemDate,
    reference: '',
    description: '',
    debitAccountId: accounts[0]?.id || 1,
    debitAmount: '',
    creditAccountId: accounts[1]?.id || 2,
    creditAmount: '',
  });

  // Calculate Balances for each Account from all Journal Entries
  const accountBalances = useMemo(() => {
    const map: Record<number, { debit: number; credit: number; net: number }> = {};
    accounts.forEach((a) => {
      map[a.id] = { debit: 0, credit: 0, net: 0 };
    });

    journalEntries.forEach((entry) => {
      entry.lines.forEach((line) => {
        if (!map[line.accountId]) {
          map[line.accountId] = { debit: 0, credit: 0, net: 0 };
        }
        map[line.accountId].debit = roundMoney(map[line.accountId].debit + (line.debit || 0));
        map[line.accountId].credit = roundMoney(map[line.accountId].credit + (line.credit || 0));
      });
    });

    accounts.forEach((a) => {
      const b = map[a.id];
      // Normal balance: Assets & Expenses = Debit - Credit; Liabilities, Equity, Income = Credit - Debit
      if (a.type === 'Asset' || a.type === 'Expense') {
        b.net = roundMoney(b.debit - b.credit);
      } else {
        b.net = roundMoney(b.credit - b.debit);
      }
    });

    return map;
  }, [accounts, journalEntries]);

  // Income Statement (P&L) Totals
  const incomeStatement = useMemo(() => {
    const incomeAccounts = accounts.filter((a) => a.type === 'Income');
    const expenseAccounts = accounts.filter((a) => a.type === 'Expense');

    const revenues = incomeAccounts.map((a) => ({
      account: a,
      amount: accountBalances[a.id]?.net || 0,
    }));
    const totalRevenue = roundMoney(revenues.reduce((s, r) => s + r.amount, 0));

    const costs = expenseAccounts.map((a) => ({
      account: a,
      amount: accountBalances[a.id]?.net || 0,
    }));
    const totalExpenses = roundMoney(costs.reduce((s, c) => s + c.amount, 0));

    const netProfit = roundMoney(totalRevenue - totalExpenses);

    return { revenues, totalRevenue, costs, totalExpenses, netProfit };
  }, [accounts, accountBalances]);

  // Balance Sheet Totals
  const balanceSheet = useMemo(() => {
    const assetAccounts = accounts.filter((a) => a.type === 'Asset');
    const liabilityAccounts = accounts.filter((a) => a.type === 'Liability');
    const equityAccounts = accounts.filter((a) => a.type === 'Equity');

    const assets = assetAccounts.map((a) => ({
      account: a,
      amount: accountBalances[a.id]?.net || 0,
    }));
    const totalAssets = roundMoney(assets.reduce((s, a) => s + a.amount, 0));

    const liabilities = liabilityAccounts.map((a) => ({
      account: a,
      amount: accountBalances[a.id]?.net || 0,
    }));
    const totalLiabilities = roundMoney(liabilities.reduce((s, l) => s + l.amount, 0));

    const equity = equityAccounts.map((a) => ({
      account: a,
      amount: accountBalances[a.id]?.net || 0,
    }));
    const baseEquity = roundMoney(equity.reduce((s, e) => s + e.amount, 0));
    const totalEquity = roundMoney(baseEquity + incomeStatement.netProfit);

    const isBalanced = Math.abs(totalAssets - (totalLiabilities + totalEquity)) < 0.05;

    return {
      assets,
      totalAssets,
      liabilities,
      totalLiabilities,
      equity,
      baseEquity,
      totalEquity,
      isBalanced,
    };
  }, [accounts, accountBalances, incomeStatement]);

  // Trial Balance Totals
  const trialBalance = useMemo(() => {
    let sumDebit = 0;
    let sumCredit = 0;
    const rows = accounts.map((a) => {
      const b = accountBalances[a.id] || { debit: 0, credit: 0 };
      sumDebit = roundMoney(sumDebit + b.debit);
      sumCredit = roundMoney(sumCredit + b.credit);
      return {
        account: a,
        debit: b.debit,
        credit: b.credit,
      };
    });

    return {
      rows,
      sumDebit,
      sumCredit,
      isBalanced: Math.abs(sumDebit - sumCredit) < 0.05,
    };
  }, [accounts, accountBalances]);

  const handleCreateExpense = (e: React.FormEvent) => {
    e.preventDefault();
    const amountNum = parseFloat(expenseForm.amount);
    if (!amountNum || amountNum <= 0) return;

    addExpense({
      categoryId: Number(expenseForm.categoryId),
      expenseDate: expenseForm.date,
      amount: amountNum,
      paidTo: expenseForm.paidTo.trim(),
      description: expenseForm.description.trim(),
      reference: expenseForm.reference.trim(),
    });

    setExpenseModalOpen(false);
    setExpenseForm({
      categoryId: expenseCategories[0]?.id || 1,
      date: systemDate,
      amount: '',
      paidTo: '',
      description: '',
      reference: '',
    });
  };

  const handleCreateJournal = (e: React.FormEvent) => {
    e.preventDefault();
    const debitNum = parseFloat(journalForm.debitAmount);
    const creditNum = parseFloat(journalForm.creditAmount);

    if (!debitNum || !creditNum || Math.abs(debitNum - creditNum) > 0.01) {
      alert('Debits must exactly equal Credits.');
      return;
    }

    const ok = addJournalEntry({
      entryDate: journalForm.date,
      reference: journalForm.reference.trim() || `JV-${Date.now()}`,
      description: journalForm.description.trim() || 'Manual adjustment journal entry',
      sourceType: 'manual',
      lines: [
        {
          id: 1,
          journalEntryId: 0,
          accountId: Number(journalForm.debitAccountId),
          debit: debitNum,
          credit: 0,
          memo: journalForm.description,
        },
        {
          id: 2,
          journalEntryId: 0,
          accountId: Number(journalForm.creditAccountId),
          debit: 0,
          credit: creditNum,
          memo: journalForm.description,
        },
      ],
    });

    if (ok) {
      setJournalModalOpen(false);
      setJournalForm({
        date: systemDate,
        reference: '',
        description: '',
        debitAccountId: accounts[0]?.id || 1,
        debitAmount: '',
        creditAccountId: accounts[1]?.id || 2,
        creditAmount: '',
      });
    }
  };

  return (
    <div id="accounting-view" className="space-y-6">
      <Header
        title="Accounting & General Ledger"
        subtitle="Double-entry financial reporting, Balance Sheet, Income Statement, Trial Balance, and Expense management"
        actions={
          <div className="flex items-center gap-2">
            <button
              id="btn-log-expense"
              onClick={() => setExpenseModalOpen(true)}
              className="flex items-center gap-1.5 px-3 py-2 bg-rose-600 hover:bg-rose-500 text-white rounded-lg text-xs font-semibold shadow-xs transition-colors"
            >
              <TrendingDown className="w-4 h-4" />
              Record Expense
            </button>
            <button
              id="btn-new-journal"
              onClick={() => setJournalModalOpen(true)}
              className="flex items-center gap-1.5 px-3 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-xs font-semibold shadow-xs transition-colors"
            >
              <PlusCircle className="w-4 h-4" />
              Post Journal Entry
            </button>
          </div>
        }
      />

      {/* Main Tabs */}
      <div className="flex items-center gap-2 border-b border-slate-800 pb-2 text-xs font-semibold overflow-x-auto">
        <button
          onClick={() => setActiveTab('financials')}
          className={`px-3.5 py-2 rounded-lg flex items-center gap-2 transition-colors ${
            activeTab === 'financials'
              ? 'bg-blue-600 text-white'
              : 'text-slate-400 hover:text-white hover:bg-slate-800/60'
          }`}
        >
          <Scale className="w-4 h-4" />
          Financial Statements
        </button>

        <button
          onClick={() => setActiveTab('journal')}
          className={`px-3.5 py-2 rounded-lg flex items-center gap-2 transition-colors ${
            activeTab === 'journal'
              ? 'bg-blue-600 text-white'
              : 'text-slate-400 hover:text-white hover:bg-slate-800/60'
          }`}
        >
          <BookOpen className="w-4 h-4" />
          Journal Entries ({journalEntries.length})
        </button>

        <button
          onClick={() => setActiveTab('expenses')}
          className={`px-3.5 py-2 rounded-lg flex items-center gap-2 transition-colors ${
            activeTab === 'expenses'
              ? 'bg-blue-600 text-white'
              : 'text-slate-400 hover:text-white hover:bg-slate-800/60'
          }`}
        >
          <Receipt className="w-4 h-4" />
          Operating Expenses ({expenses.length})
        </button>

        <button
          onClick={() => setActiveTab('coa')}
          className={`px-3.5 py-2 rounded-lg flex items-center gap-2 transition-colors ${
            activeTab === 'coa'
              ? 'bg-blue-600 text-white'
              : 'text-slate-400 hover:text-white hover:bg-slate-800/60'
          }`}
        >
          <FileSpreadsheet className="w-4 h-4" />
          Chart of Accounts ({accounts.length})
        </button>
      </div>

      {/* TAB 1: FINANCIAL STATEMENTS */}
      {activeTab === 'financials' && (
        <div className="space-y-4">
          <div className="flex items-center gap-2">
            <button
              onClick={() => setStatementType('balance_sheet')}
              className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors ${
                statementType === 'balance_sheet'
                  ? 'bg-slate-700 text-white'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              Balance Sheet
            </button>
            <button
              onClick={() => setStatementType('pnl')}
              className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors ${
                statementType === 'pnl'
                  ? 'bg-slate-700 text-white'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              Income Statement (P&amp;L)
            </button>
            <button
              onClick={() => setStatementType('trial_balance')}
              className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors ${
                statementType === 'trial_balance'
                  ? 'bg-slate-700 text-white'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              Trial Balance
            </button>
          </div>

          {/* BALANCE SHEET */}
          {statementType === 'balance_sheet' && (
            <div className="bg-[#111C38] border border-[#1E2D5A] rounded-xl p-6 space-y-6">
              <div className="flex items-center justify-between border-b border-[#1E2D5A] pb-4">
                <div>
                  <h3 className="text-base font-bold text-white">Statement of Financial Position</h3>
                  <p className="text-xs text-slate-400">As at {systemDate}</p>
                </div>
                <div className="flex items-center gap-1.5 text-xs">
                  {balanceSheet.isBalanced ? (
                    <span className="flex items-center gap-1 text-emerald-400 font-semibold bg-emerald-950/40 px-2.5 py-1 rounded-md border border-emerald-800">
                      <CheckCircle2 className="w-4 h-4" />
                      Balanced: Assets = Liabilities + Equity
                    </span>
                  ) : (
                    <span className="flex items-center gap-1 text-rose-400 font-semibold bg-rose-950/40 px-2.5 py-1 rounded-md border border-rose-800">
                      <AlertCircle className="w-4 h-4" />
                      Unbalanced by {formatMoney(balanceSheet.totalAssets - (balanceSheet.totalLiabilities + balanceSheet.totalEquity))}
                    </span>
                  )}
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
                {/* Left: ASSETS */}
                <div className="space-y-4">
                  <h4 className="text-xs font-bold uppercase tracking-wider text-blue-400 border-b border-slate-800 pb-1">
                    Assets
                  </h4>
                  <div className="space-y-2 text-xs">
                    {balanceSheet.assets.map((a) => (
                      <div key={a.account.id} className="flex justify-between py-1 border-b border-slate-800/50">
                        <span className="text-slate-300">
                          <span className="font-mono text-slate-400 text-[11px] mr-2">
                            {a.account.code}
                          </span>
                          {a.account.name}
                        </span>
                        <span className="font-semibold text-white font-mono">{formatMoney(a.amount)}</span>
                      </div>
                    ))}
                    <div className="flex justify-between py-2 border-t border-slate-700 font-bold text-sm text-blue-400">
                      <span>Total Assets</span>
                      <span className="font-mono">{formatMoney(balanceSheet.totalAssets)}</span>
                    </div>
                  </div>
                </div>

                {/* Right: LIABILITIES & EQUITY */}
                <div className="space-y-6">
                  {/* Liabilities */}
                  <div className="space-y-3">
                    <h4 className="text-xs font-bold uppercase tracking-wider text-amber-400 border-b border-slate-800 pb-1">
                      Liabilities
                    </h4>
                    <div className="space-y-2 text-xs">
                      {balanceSheet.liabilities.map((l) => (
                        <div key={l.account.id} className="flex justify-between py-1 border-b border-slate-800/50">
                          <span className="text-slate-300">
                            <span className="font-mono text-slate-400 text-[11px] mr-2">
                              {l.account.code}
                            </span>
                            {l.account.name}
                          </span>
                          <span className="font-semibold text-white font-mono">{formatMoney(l.amount)}</span>
                        </div>
                      ))}
                      <div className="flex justify-between py-1 font-bold text-slate-200">
                        <span>Total Liabilities</span>
                        <span className="font-mono">{formatMoney(balanceSheet.totalLiabilities)}</span>
                      </div>
                    </div>
                  </div>

                  {/* Equity */}
                  <div className="space-y-3">
                    <h4 className="text-xs font-bold uppercase tracking-wider text-purple-400 border-b border-slate-800 pb-1">
                      Equity &amp; Reserves
                    </h4>
                    <div className="space-y-2 text-xs">
                      {balanceSheet.equity.map((e) => (
                        <div key={e.account.id} className="flex justify-between py-1 border-b border-slate-800/50">
                          <span className="text-slate-300">
                            <span className="font-mono text-slate-400 text-[11px] mr-2">
                              {e.account.code}
                            </span>
                            {e.account.name}
                          </span>
                          <span className="font-semibold text-white font-mono">{formatMoney(e.amount)}</span>
                        </div>
                      ))}
                      <div className="flex justify-between py-1 border-b border-slate-800/50">
                        <span className="text-emerald-400 font-medium">Net Profit / (Loss) YTD</span>
                        <span className="font-bold text-emerald-400 font-mono">
                          {formatMoney(incomeStatement.netProfit)}
                        </span>
                      </div>
                      <div className="flex justify-between py-1 font-bold text-slate-200">
                        <span>Total Equity</span>
                        <span className="font-mono">{formatMoney(balanceSheet.totalEquity)}</span>
                      </div>
                    </div>
                  </div>

                  {/* Total Liabilities + Equity */}
                  <div className="flex justify-between py-2 border-t-2 border-slate-600 font-bold text-sm text-white">
                    <span>Total Liabilities &amp; Equity</span>
                    <span className="font-mono">
                      {formatMoney(balanceSheet.totalLiabilities + balanceSheet.totalEquity)}
                    </span>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* INCOME STATEMENT (P&L) */}
          {statementType === 'pnl' && (
            <div className="bg-[#111C38] border border-[#1E2D5A] rounded-xl p-6 space-y-6">
              <div className="border-b border-[#1E2D5A] pb-4">
                <h3 className="text-base font-bold text-white">Statement of Comprehensive Income</h3>
                <p className="text-xs text-slate-400">For the period ended {systemDate}</p>
              </div>

              <div className="space-y-6 max-w-2xl">
                {/* Revenue Section */}
                <div className="space-y-3">
                  <h4 className="text-xs font-bold uppercase tracking-wider text-emerald-400 border-b border-slate-800 pb-1">
                    Revenue &amp; Interest Income
                  </h4>
                  <div className="space-y-2 text-xs">
                    {incomeStatement.revenues.map((r) => (
                      <div key={r.account.id} className="flex justify-between py-1 border-b border-slate-800/50">
                        <span className="text-slate-300">
                          <span className="font-mono text-slate-400 text-[11px] mr-2">
                            {r.account.code}
                          </span>
                          {r.account.name}
                        </span>
                        <span className="font-semibold text-emerald-400 font-mono">
                          {formatMoney(r.amount)}
                        </span>
                      </div>
                    ))}
                    <div className="flex justify-between py-2 border-t border-slate-700 font-bold text-xs text-white">
                      <span>Total Revenue</span>
                      <span className="font-mono text-emerald-400">
                        {formatMoney(incomeStatement.totalRevenue)}
                      </span>
                    </div>
                  </div>
                </div>

                {/* Operating Expenses Section */}
                <div className="space-y-3">
                  <h4 className="text-xs font-bold uppercase tracking-wider text-rose-400 border-b border-slate-800 pb-1">
                    Operating &amp; Administrative Expenses
                  </h4>
                  <div className="space-y-2 text-xs">
                    {incomeStatement.costs.map((c) => (
                      <div key={c.account.id} className="flex justify-between py-1 border-b border-slate-800/50">
                        <span className="text-slate-300">
                          <span className="font-mono text-slate-400 text-[11px] mr-2">
                            {c.account.code}
                          </span>
                          {c.account.name}
                        </span>
                        <span className="font-semibold text-rose-400 font-mono">
                          {formatMoney(c.amount)}
                        </span>
                      </div>
                    ))}
                    <div className="flex justify-between py-2 border-t border-slate-700 font-bold text-xs text-white">
                      <span>Total Operating Expenses</span>
                      <span className="font-mono text-rose-400">
                        {formatMoney(incomeStatement.totalExpenses)}
                      </span>
                    </div>
                  </div>
                </div>

                {/* Bottom Line: Net Profit */}
                <div className="p-4 bg-[#0B1329] border border-[#1E2D5A] rounded-xl flex items-center justify-between">
                  <div>
                    <h4 className="text-sm font-bold text-white">Net Operational Profit / (Loss)</h4>
                    <p className="text-[11px] text-slate-400">Revenues less Operating Expenses</p>
                  </div>
                  <span
                    className={`text-xl font-bold font-mono ${
                      incomeStatement.netProfit >= 0 ? 'text-emerald-400' : 'text-rose-400'
                    }`}
                  >
                    {formatMoney(incomeStatement.netProfit)}
                  </span>
                </div>
              </div>
            </div>
          )}

          {/* TRIAL BALANCE */}
          {statementType === 'trial_balance' && (
            <div className="bg-[#111C38] border border-[#1E2D5A] rounded-xl overflow-hidden">
              <div className="px-5 py-4 border-b border-[#1E2D5A] flex items-center justify-between">
                <div>
                  <h3 className="text-base font-bold text-white">General Ledger Trial Balance</h3>
                  <p className="text-xs text-slate-400">Verification of Debit &amp; Credit Ledger Equality</p>
                </div>
                <span
                  className={`text-xs font-semibold px-2.5 py-1 rounded-md border ${
                    trialBalance.isBalanced
                      ? 'bg-emerald-950 text-emerald-300 border-emerald-800'
                      : 'bg-rose-950 text-rose-300 border-rose-800'
                  }`}
                >
                  {trialBalance.isBalanced ? 'Balanced' : 'Out of Balance'}
                </span>
              </div>

              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead className="bg-[#0B1329] text-slate-400 uppercase text-[10px] tracking-wider border-b border-[#1E2D5A]">
                    <tr>
                      <th className="px-4 py-3">Code</th>
                      <th className="px-4 py-3">Account Name</th>
                      <th className="px-4 py-3">Type</th>
                      <th className="px-4 py-3 text-right">Debit ($)</th>
                      <th className="px-4 py-3 text-right">Credit ($)</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#1E2D5A]">
                    {trialBalance.rows.map((row) => (
                      <tr key={row.account.id} className="hover:bg-slate-800/40 transition-colors">
                        <td className="px-4 py-2.5 font-mono font-bold text-blue-400">
                          {row.account.code}
                        </td>
                        <td className="px-4 py-2.5 font-medium text-white">{row.account.name}</td>
                        <td className="px-4 py-2.5 text-slate-400">{row.account.type}</td>
                        <td className="px-4 py-2.5 text-right font-mono text-slate-200">
                          {row.debit > 0 ? formatMoney(row.debit, false) : '-'}
                        </td>
                        <td className="px-4 py-2.5 text-right font-mono text-slate-200">
                          {row.credit > 0 ? formatMoney(row.credit, false) : '-'}
                        </td>
                      </tr>
                    ))}
                    {/* Trial Balance Footer */}
                    <tr className="bg-[#0B1329] font-bold text-white border-t-2 border-slate-600">
                      <td colSpan={3} className="px-4 py-3 text-right uppercase text-[11px] tracking-wider">
                        Total Sums:
                      </td>
                      <td className="px-4 py-3 text-right font-mono text-blue-400 text-sm">
                        {formatMoney(trialBalance.sumDebit)}
                      </td>
                      <td className="px-4 py-3 text-right font-mono text-blue-400 text-sm">
                        {formatMoney(trialBalance.sumCredit)}
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      )}

      {/* TAB 2: JOURNAL ENTRIES */}
      {activeTab === 'journal' && (
        <div className="bg-[#111C38] border border-[#1E2D5A] rounded-xl overflow-hidden space-y-4">
          <div className="px-5 py-4 border-b border-[#1E2D5A] flex items-center justify-between">
            <div>
              <h3 className="text-sm font-bold text-white">General Journal Audit Log</h3>
              <p className="text-xs text-slate-400">All posted debits and credits across the ledger</p>
            </div>
          </div>

          <div className="divide-y divide-[#1E2D5A] max-h-[650px] overflow-y-auto px-5 pb-5 space-y-4">
            {journalEntries.map((entry) => (
              <div
                key={entry.id}
                className="bg-[#0B1329] border border-[#1E2D5A] rounded-xl p-4 space-y-3"
              >
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-[#1E2D5A] pb-2 text-xs">
                  <div>
                    <span className="font-mono font-bold text-blue-400">{entry.reference}</span>
                    <span className="text-slate-400 mx-2">•</span>
                    <span className="font-mono text-slate-300">{entry.entryDate}</span>
                    <span className="text-slate-400 mx-2">•</span>
                    <span className="text-white font-medium">{entry.description}</span>
                  </div>
                  <span className="text-[10px] uppercase font-bold tracking-wider px-2 py-0.5 rounded bg-slate-800 text-slate-300">
                    {entry.sourceType}
                  </span>
                </div>

                {/* Lines Table */}
                <table className="w-full text-left text-[11px]">
                  <thead className="text-slate-500 uppercase text-[9px]">
                    <tr>
                      <th className="py-1">Account</th>
                      <th className="py-1">Memo</th>
                      <th className="py-1 text-right">Debit ($)</th>
                      <th className="py-1 text-right">Credit ($)</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800/40 font-mono">
                    {entry.lines.map((line) => {
                      const acc = accounts.find((a) => a.id === line.accountId);
                      return (
                        <tr key={line.id}>
                          <td className="py-1 text-slate-300">
                            {acc?.code} - {acc?.name}
                          </td>
                          <td className="py-1 text-slate-400 font-sans">{line.memo || '-'}</td>
                          <td className="py-1 text-right text-emerald-400 font-semibold">
                            {line.debit > 0 ? formatMoney(line.debit, false) : '-'}
                          </td>
                          <td className="py-1 text-right text-sky-400 font-semibold">
                            {line.credit > 0 ? formatMoney(line.credit, false) : '-'}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* TAB 3: OPERATING EXPENSES */}
      {activeTab === 'expenses' && (
        <div className="bg-[#111C38] border border-[#1E2D5A] rounded-xl overflow-hidden">
          <div className="px-5 py-4 border-b border-[#1E2D5A] flex items-center justify-between">
            <h3 className="text-sm font-bold text-white">Disbursed Operating Expenses Register</h3>
            <span className="text-xs text-rose-400 font-bold">
              Total Expenses: {formatMoney(expenses.reduce((s, e) => s + e.amount, 0))}
            </span>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-[#0B1329] text-slate-400 uppercase text-[10px] tracking-wider border-b border-[#1E2D5A]">
                <tr>
                  <th className="px-4 py-3">Date</th>
                  <th className="px-4 py-3">Category</th>
                  <th className="px-4 py-3">Paid To</th>
                  <th className="px-4 py-3">Description</th>
                  <th className="px-4 py-3">Reference</th>
                  <th className="px-4 py-3 text-right">Amount</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#1E2D5A]">
                {expenses.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="px-4 py-8 text-center text-slate-500 text-xs">
                      No operating expenses recorded yet.
                    </td>
                  </tr>
                ) : (
                  expenses.map((e) => {
                    const cat = expenseCategories.find((c) => c.id === e.categoryId);
                    return (
                      <tr key={e.id} className="hover:bg-slate-800/40 transition-colors">
                        <td className="px-4 py-3 font-mono text-slate-400">{e.expenseDate}</td>
                        <td className="px-4 py-3 font-semibold text-white">
                          {cat?.name || 'General'}
                        </td>
                        <td className="px-4 py-3 text-slate-300">{e.paidTo || '-'}</td>
                        <td className="px-4 py-3 text-slate-400 max-w-xs truncate">
                          {e.description || '-'}
                        </td>
                        <td className="px-4 py-3 font-mono text-slate-400">{e.reference || '-'}</td>
                        <td className="px-4 py-3 text-right font-bold text-rose-400">
                          {formatMoney(e.amount)}
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

      {/* TAB 4: CHART OF ACCOUNTS */}
      {activeTab === 'coa' && (
        <div className="bg-[#111C38] border border-[#1E2D5A] rounded-xl overflow-hidden">
          <div className="px-5 py-4 border-b border-[#1E2D5A]">
            <h3 className="text-sm font-bold text-white">Chart of Accounts Registry</h3>
            <p className="text-xs text-slate-400">
              Standard double-entry microfinance general ledger accounts (1000-5900)
            </p>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-[#0B1329] text-slate-400 uppercase text-[10px] tracking-wider border-b border-[#1E2D5A]">
                <tr>
                  <th className="px-4 py-3">Code</th>
                  <th className="px-4 py-3">Account Name</th>
                  <th className="px-4 py-3">Account Type</th>
                  <th className="px-4 py-3">System Control</th>
                  <th className="px-4 py-3 text-right">Net Balance</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#1E2D5A]">
                {accounts.map((a) => (
                  <tr key={a.id} className="hover:bg-slate-800/40 transition-colors">
                    <td className="px-4 py-3 font-mono font-bold text-blue-400">{a.code}</td>
                    <td className="px-4 py-3 font-semibold text-white">{a.name}</td>
                    <td className="px-4 py-3">
                      <span
                        className={`inline-flex px-2 py-0.5 rounded text-[10px] font-bold ${
                          a.type === 'Asset'
                            ? 'bg-blue-950 text-blue-300 border border-blue-800'
                            : a.type === 'Liability'
                            ? 'bg-amber-950 text-amber-300 border border-amber-800'
                            : a.type === 'Equity'
                            ? 'bg-purple-950 text-purple-300 border border-purple-800'
                            : a.type === 'Income'
                            ? 'bg-emerald-950 text-emerald-300 border border-emerald-800'
                            : 'bg-rose-950 text-rose-300 border border-rose-800'
                        }`}
                      >
                        {a.type}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-slate-400">
                      {a.isControl ? 'Control Account' : 'Standard Sub-ledger'}
                    </td>
                    <td className="px-4 py-3 text-right font-mono font-bold text-slate-200">
                      {formatMoney(accountBalances[a.id]?.net || 0)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Record Expense Modal */}
      <Modal
        isOpen={expenseModalOpen}
        onClose={() => setExpenseModalOpen(false)}
        title="Record Operating Expense"
        maxWidth="md"
      >
        <form onSubmit={handleCreateExpense} className="space-y-4">
          <div>
            <label className="block text-xs font-semibold text-slate-300 mb-1">
              Expense Category *
            </label>
            <select
              value={expenseForm.categoryId}
              onChange={(e) => setExpenseForm({ ...expenseForm, categoryId: Number(e.target.value) })}
              className="w-full px-3 py-2 bg-[#162244] border border-[#1E2D5A] rounded-lg text-xs text-white focus:outline-hidden focus:border-blue-500"
            >
              {expenseCategories.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name} - {c.description}
                </option>
              ))}
            </select>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1">
                Amount Paid ($) *
              </label>
              <input
                type="number"
                step="any"
                required
                value={expenseForm.amount}
                onChange={(e) => setExpenseForm({ ...expenseForm, amount: e.target.value })}
                className="w-full px-3 py-2 bg-[#162244] border border-[#1E2D5A] rounded-lg text-xs text-white font-bold focus:outline-hidden focus:border-blue-500"
              />
            </div>
            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1">Expense Date *</label>
              <input
                type="date"
                required
                value={expenseForm.date}
                onChange={(e) => setExpenseForm({ ...expenseForm, date: e.target.value })}
                className="w-full px-3 py-2 bg-[#162244] border border-[#1E2D5A] rounded-lg text-xs text-white font-mono focus:outline-hidden focus:border-blue-500"
              />
            </div>
          </div>

          <div>
            <label className="block text-xs font-semibold text-slate-300 mb-1">
              Paid To (Vendor / Supplier)
            </label>
            <input
              type="text"
              placeholder="e.g. Commercial Landlord, Power Utility, Office Mart..."
              value={expenseForm.paidTo}
              onChange={(e) => setExpenseForm({ ...expenseForm, paidTo: e.target.value })}
              className="w-full px-3 py-2 bg-[#162244] border border-[#1E2D5A] rounded-lg text-xs text-white focus:outline-hidden focus:border-blue-500"
            />
          </div>

          <div>
            <label className="block text-xs font-semibold text-slate-300 mb-1">
              Description / Business Purpose
            </label>
            <input
              type="text"
              placeholder="e.g. Head office lease, Field fuel tokens..."
              value={expenseForm.description}
              onChange={(e) => setExpenseForm({ ...expenseForm, description: e.target.value })}
              className="w-full px-3 py-2 bg-[#162244] border border-[#1E2D5A] rounded-lg text-xs text-white focus:outline-hidden focus:border-blue-500"
            />
          </div>

          <div>
            <label className="block text-xs font-semibold text-slate-300 mb-1">
              Voucher / Invoice Reference #
            </label>
            <input
              type="text"
              placeholder="e.g. INV-2026-99"
              value={expenseForm.reference}
              onChange={(e) => setExpenseForm({ ...expenseForm, reference: e.target.value })}
              className="w-full px-3 py-2 bg-[#162244] border border-[#1E2D5A] rounded-lg text-xs text-white font-mono focus:outline-hidden focus:border-blue-500"
            />
          </div>

          <div className="flex justify-end gap-2 pt-2 border-t border-[#1E2D5A]">
            <button
              type="button"
              onClick={() => setExpenseModalOpen(false)}
              className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-xs font-semibold transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              className="px-4 py-2 bg-rose-600 hover:bg-rose-500 text-white rounded-lg text-xs font-semibold shadow-xs transition-colors"
            >
              Post Expense &amp; Credit Cash
            </button>
          </div>
        </form>
      </Modal>

      {/* Manual Journal Entry Modal */}
      <Modal
        isOpen={journalModalOpen}
        onClose={() => setJournalModalOpen(false)}
        title="Post Manual Journal Voucher"
        maxWidth="lg"
      >
        <form onSubmit={handleCreateJournal} className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1">Journal Date *</label>
              <input
                type="date"
                required
                value={journalForm.date}
                onChange={(e) => setJournalForm({ ...journalForm, date: e.target.value })}
                className="w-full px-3 py-2 bg-[#162244] border border-[#1E2D5A] rounded-lg text-xs text-white font-mono focus:outline-hidden focus:border-blue-500"
              />
            </div>
            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1">Reference / JV #</label>
              <input
                type="text"
                placeholder="JV-2026-001"
                value={journalForm.reference}
                onChange={(e) => setJournalForm({ ...journalForm, reference: e.target.value })}
                className="w-full px-3 py-2 bg-[#162244] border border-[#1E2D5A] rounded-lg text-xs text-white font-mono focus:outline-hidden focus:border-blue-500"
              />
            </div>
          </div>

          <div>
            <label className="block text-xs font-semibold text-slate-300 mb-1">Description / Memo</label>
            <input
              type="text"
              placeholder="e.g. Month-end depreciation adjustment"
              value={journalForm.description}
              onChange={(e) => setJournalForm({ ...journalForm, description: e.target.value })}
              className="w-full px-3 py-2 bg-[#162244] border border-[#1E2D5A] rounded-lg text-xs text-white focus:outline-hidden focus:border-blue-500"
            />
          </div>

          {/* Debit Row */}
          <div className="p-3 bg-[#0B1329] border border-emerald-900/50 rounded-lg space-y-2">
            <p className="text-[11px] font-bold uppercase text-emerald-400">Debit Line</p>
            <div className="grid grid-cols-3 gap-3">
              <div className="col-span-2">
                <label className="block text-[10px] text-slate-400 mb-1">Debit Account</label>
                <select
                  value={journalForm.debitAccountId}
                  onChange={(e) =>
                    setJournalForm({ ...journalForm, debitAccountId: Number(e.target.value) })
                  }
                  className="w-full px-3 py-1.5 bg-[#162244] border border-[#1E2D5A] rounded-lg text-xs text-white focus:outline-hidden focus:border-blue-500"
                >
                  {accounts.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.code} - {a.name} ({a.type})
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-[10px] text-slate-400 mb-1">Debit Amount ($)</label>
                <input
                  type="number"
                  step="any"
                  required
                  placeholder="0.00"
                  value={journalForm.debitAmount}
                  onChange={(e) => setJournalForm({ ...journalForm, debitAmount: e.target.value })}
                  className="w-full px-3 py-1.5 bg-[#162244] border border-[#1E2D5A] rounded-lg text-xs text-emerald-300 font-bold focus:outline-hidden focus:border-blue-500"
                />
              </div>
            </div>
          </div>

          {/* Credit Row */}
          <div className="p-3 bg-[#0B1329] border border-sky-900/50 rounded-lg space-y-2">
            <p className="text-[11px] font-bold uppercase text-sky-400">Credit Line</p>
            <div className="grid grid-cols-3 gap-3">
              <div className="col-span-2">
                <label className="block text-[10px] text-slate-400 mb-1">Credit Account</label>
                <select
                  value={journalForm.creditAccountId}
                  onChange={(e) =>
                    setJournalForm({ ...journalForm, creditAccountId: Number(e.target.value) })
                  }
                  className="w-full px-3 py-1.5 bg-[#162244] border border-[#1E2D5A] rounded-lg text-xs text-white focus:outline-hidden focus:border-blue-500"
                >
                  {accounts.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.code} - {a.name} ({a.type})
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-[10px] text-slate-400 mb-1">Credit Amount ($)</label>
                <input
                  type="number"
                  step="any"
                  required
                  placeholder="0.00"
                  value={journalForm.creditAmount}
                  onChange={(e) => setJournalForm({ ...journalForm, creditAmount: e.target.value })}
                  className="w-full px-3 py-1.5 bg-[#162244] border border-[#1E2D5A] rounded-lg text-xs text-sky-300 font-bold focus:outline-hidden focus:border-blue-500"
                />
              </div>
            </div>
          </div>

          <div className="flex justify-end gap-2 pt-2 border-t border-[#1E2D5A]">
            <button
              type="button"
              onClick={() => setJournalModalOpen(false)}
              className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-xs font-semibold transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-xs font-semibold shadow-xs transition-colors"
            >
              Post Balanced Entry
            </button>
          </div>
        </form>
      </Modal>
    </div>
  );
};
