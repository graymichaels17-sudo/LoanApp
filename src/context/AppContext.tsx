import React, { createContext, useContext, useState, useEffect, useRef } from 'react';
import {
  Account,
  BadDebt,
  BadDebtRecovery,
  Client,
  Disbursement,
  Employee,
  Expense,
  ExpenseCategory,
  InterestMethod,
  JournalEntry,
  Loan,
  LoanProduct,
  RatePeriod,
  Repayment,
  RepaymentFrequency,
  RepaymentScheduleItem,
  Rollover,
  SystemSettings,
  User,
} from '../types';
import {
  INITIAL_ACCOUNTS,
  INITIAL_CLIENTS,
  INITIAL_DISBURSEMENTS,
  INITIAL_EMPLOYEES,
  INITIAL_EXPENSE_CATEGORIES,
  INITIAL_EXPENSES,
  INITIAL_JOURNAL_ENTRIES,
  INITIAL_LOAN_PRODUCTS,
  INITIAL_LOANS,
  INITIAL_LOCATIONS,
  INITIAL_REPAYMENTS,
  INITIAL_SCHEDULES,
  INITIAL_USERS,
} from '../utils/seedData';
import { allocateRepaymentWaterfall, calculateSchedule, nextDueDate } from '../utils/amortization';
import { roundMoney } from '../utils/money';

const STORAGE_KEY = 'microfinance_manager_store_v2';

interface AppContextType {
  currentUser: User | null;
  users: User[];
  clients: Client[];
  loans: Loan[];
  schedules: RepaymentScheduleItem[];
  disbursements: Disbursement[];
  repayments: Repayment[];
  rollovers: Rollover[];
  badDebts: BadDebt[];
  badDebtRecoveries: BadDebtRecovery[];
  accounts: Account[];
  journalEntries: JournalEntry[];
  expenseCategories: ExpenseCategory[];
  expenses: Expense[];
  loanProducts: LoanProduct[];
  locations: string[];
  employees: Employee[];
  settings: SystemSettings;
  systemDate: string;

  // Multi-user online cloud synchronization
  cloudSyncStatus: 'synced' | 'syncing' | 'offline' | 'error';
  lastCloudSync: string | null;
  refreshFromCloud: () => Promise<void>;
  isTursoActive: boolean;

  // Actions
  login: (username: string) => boolean;
  logout: () => void;
  addClient: (data: Omit<Client, 'id' | 'clientNo' | 'createdAt'>) => Client;
  updateClient: (id: number, data: Partial<Client>) => void;
  createLoanApplication: (data: {
    clientId: number;
    productId?: number;
    principal: number;
    interestRate: number;
    interestMethod: InterestMethod;
    ratePeriod: RatePeriod;
    termMonths: number;
    repaymentFrequency: RepaymentFrequency;
    applicationDate: string;
    purpose?: string;
    collateral?: string;
  }) => Loan;
  approveLoan: (loanId: number) => void;
  declineLoan: (loanId: number, reason?: string) => void;
  disburseLoan: (
    loanId: number,
    data: {
      disbursementDate: string;
      method: Disbursement['method'];
      reference?: string;
      notes?: string;
    }
  ) => void;
  recordRepayment: (data: {
    loanId: number;
    amount: number;
    paymentDate: string;
    method: Repayment['method'];
    reference?: string;
    notes?: string;
  }) => { success: boolean; message: string; allocation?: any };
  requestRollover: (originalLoanId: number, reason: string) => Rollover;
  approveRollover: (rolloverId: number) => void;
  writeOffBadDebt: (loanId: number, reason: string) => void;
  recordBadDebtRecovery: (badDebtId: number, amount: number, method: string, reference?: string) => void;
  addExpense: (data: {
    categoryId: number;
    expenseDate: string;
    amount: number;
    paidTo?: string;
    description?: string;
    reference?: string;
  }) => void;
  addJournalEntry: (entry: Omit<JournalEntry, 'id' | 'createdAt'>) => boolean;
  addUser: (userData: Omit<User, 'id' | 'createdAt'>) => void;
  bulkImportClients: (newClients: Array<Omit<Client, 'id' | 'clientNo' | 'createdAt'>>) => number;
  bulkImportLoans: (newLoans: any[]) => number;
  addEmployee: (emp: Omit<Employee, 'id'>) => void;
  updateEmployee: (id: number, emp: Partial<Employee>) => void;
  addLocation: (name: string) => void;
  addLoanProduct: (prod: Omit<LoanProduct, 'id'>) => void;
  updateSettings: (settings: SystemSettings) => void;
  resetDatabase: () => void;
  resetToInitialSeed: () => void;
  exportDatabaseJson: () => string;
  exportDatabaseJSON: () => string;
  importDatabaseJson: (json: string) => boolean;
  importDatabaseJSON: (json: string) => boolean;
}

export const DEFAULT_SETTINGS: SystemSettings = {
  companyName: 'Microfinance Manager (Pvt) Ltd',
  currency: 'USD ($)',
  defaultInterestRate: 15,
  defaultPenaltyRate: 5,
  gracePeriodDays: 5,
  loanProcessingFeeRate: 3,
};

const AppContext = createContext<AppContextType | undefined>(undefined);

export const AppProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const loadInitial = () => {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved) {
      try {
        const parsed = JSON.parse(saved);
        if (!parsed.settings) parsed.settings = DEFAULT_SETTINGS;
        return parsed;
      } catch (e) {
        console.error('Error loading saved state:', e);
      }
    }
    return {
      users: INITIAL_USERS,
      clients: INITIAL_CLIENTS,
      loans: INITIAL_LOANS,
      schedules: INITIAL_SCHEDULES,
      disbursements: INITIAL_DISBURSEMENTS,
      repayments: INITIAL_REPAYMENTS,
      rollovers: [],
      badDebts: [],
      badDebtRecoveries: [],
      accounts: INITIAL_ACCOUNTS,
      journalEntries: INITIAL_JOURNAL_ENTRIES,
      expenseCategories: INITIAL_EXPENSE_CATEGORIES,
      expenses: INITIAL_EXPENSES,
      loanProducts: INITIAL_LOAN_PRODUCTS,
      locations: INITIAL_LOCATIONS,
      employees: INITIAL_EMPLOYEES,
      currentUser: INITIAL_USERS[0],
      settings: DEFAULT_SETTINGS,
    };
  };

  const [state, setState] = useState(loadInitial);
  const systemDate = '2026-09-16';

  // Multi-user online cloud synchronization state
  const [cloudSyncStatus, setCloudSyncStatus] = useState<'synced' | 'syncing' | 'offline' | 'error'>('syncing');
  const [lastCloudSync, setLastCloudSync] = useState<string | null>(null);
  const [isTursoActive, setIsTursoActive] = useState<boolean>(false);
  const isHydratingFromCloud = useRef(false);
  const saveTimeoutRef = useRef<any>(null);

  // Fetch central synchronized state from Turso Cloud / Backend
  const fetchCloudState = async (silently = false) => {
    try {
      if (!silently) setCloudSyncStatus('syncing');
      const res = await fetch('/api/state');
      if (res.ok) {
        const result = await res.json();
        setIsTursoActive(!!result.tursoConnected);
        if (result.success && result.data && Array.isArray(result.data.loans) && Array.isArray(result.data.users)) {
          isHydratingFromCloud.current = true;
          setState((prev: any) => ({
            ...result.data,
            // Retain active local user login session
            currentUser: prev.currentUser || result.data.currentUser || INITIAL_USERS[0],
          }));
          setLastCloudSync(new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }));
          setCloudSyncStatus('synced');
        } else {
          // Cloud database empty or unseeded - initialize it with initial full state
          await pushStateToCloud(state);
          setCloudSyncStatus('synced');
        }
      } else {
        setCloudSyncStatus('offline');
      }
    } catch {
      setCloudSyncStatus('offline');
    }
  };

  const pushStateToCloud = async (stateToSave: any) => {
    try {
      setCloudSyncStatus('syncing');
      const res = await fetch('/api/state', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ state: stateToSave }),
      });
      if (res.ok) {
        const data = await res.json();
        setIsTursoActive(!!data.tursoConnected);
        setLastCloudSync(new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }));
        setCloudSyncStatus('synced');
      } else {
        setCloudSyncStatus('error');
      }
    } catch {
      setCloudSyncStatus('offline');
    }
  };

  // Initial load and background polling for multi-user real-time changes
  useEffect(() => {
    fetchCloudState();

    // Poll every 12 seconds so if other officers add loans/repayments, all screens sync
    const pollInterval = setInterval(() => {
      fetchCloudState(true);
    }, 12000);

    return () => clearInterval(pollInterval);
  }, []);

  // Save changes locally and automatically push to Turso Cloud
  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));

    if (isHydratingFromCloud.current) {
      isHydratingFromCloud.current = false;
      return;
    }

    if (saveTimeoutRef.current) clearTimeout(saveTimeoutRef.current);
    saveTimeoutRef.current = setTimeout(() => {
      pushStateToCloud(state);
    }, 600);

    return () => {
      if (saveTimeoutRef.current) clearTimeout(saveTimeoutRef.current);
    };
  }, [state]);

  const login = (username: string): boolean => {
    const user = state.users.find((u: User) => u.username.toLowerCase() === username.trim().toLowerCase() && u.active);
    if (user) {
      const updatedUsers = state.users.map((u: User) =>
        u.id === user.id ? { ...u, lastLogin: new Date().toISOString().replace('T', ' ').slice(0, 16) } : u
      );
      setState((prev: any) => ({ ...prev, users: updatedUsers, currentUser: user }));
      return true;
    }
    return false;
  };

  const logout = () => {
    setState((prev: any) => ({ ...prev, currentUser: null }));
  };

  const addClient = (data: Omit<Client, 'id' | 'clientNo' | 'createdAt'>): Client => {
    const nextId = state.clients.length > 0 ? Math.max(...state.clients.map((c: Client) => c.id)) + 1 : 1;
    const clientNo = `CL-${String(nextId).padStart(5, '0')}`;
    const newClient: Client = {
      ...data,
      id: nextId,
      clientNo,
      createdAt: systemDate,
    };
    setState((prev: any) => ({
      ...prev,
      clients: [newClient, ...prev.clients],
    }));
    return newClient;
  };

  const updateClient = (id: number, data: Partial<Client>) => {
    setState((prev: any) => ({
      ...prev,
      clients: prev.clients.map((c: Client) => (c.id === id ? { ...c, ...data } : c)),
    }));
  };

  const createLoanApplication = (data: {
    clientId: number;
    productId?: number;
    principal: number;
    interestRate: number;
    interestMethod: InterestMethod;
    ratePeriod: RatePeriod;
    termMonths: number;
    repaymentFrequency: RepaymentFrequency;
    applicationDate: string;
    purpose?: string;
    collateral?: string;
  }): Loan => {
    const nextId = state.loans.length > 0 ? Math.max(...state.loans.map((l: Loan) => l.id)) + 1 : 1;
    const loanNo = `LN-${String(nextId).padStart(5, '0')}`;
    const product = state.loanProducts.find((p: LoanProduct) => p.id === data.productId);
    const adminFeePct = product ? product.adminFeePct : 2.5;
    const adminFee = roundMoney(data.principal * (adminFeePct / 100));

    const newLoan: Loan = {
      id: nextId,
      loanNo,
      clientId: data.clientId,
      productId: data.productId,
      principal: data.principal,
      interestRate: data.interestRate,
      interestMethod: data.interestMethod,
      ratePeriod: data.ratePeriod,
      termMonths: data.termMonths,
      repaymentFrequency: data.repaymentFrequency,
      applicationDate: data.applicationDate || systemDate,
      adminFee,
      status: 'Pending',
      approvalStatus: 'Pending',
      purpose: data.purpose,
      collateral: data.collateral,
      createdBy: state.currentUser?.id,
      createdAt: systemDate,
    };

    setState((prev: any) => ({
      ...prev,
      loans: [newLoan, ...prev.loans],
    }));
    return newLoan;
  };

  const approveLoan = (loanId: number) => {
    setState((prev: any) => ({
      ...prev,
      loans: prev.loans.map((l: Loan) =>
        l.id === loanId
          ? {
              ...l,
              approvalStatus: 'Approved',
              approvedBy: state.currentUser?.id,
              approvedAt: systemDate,
            }
          : l
      ),
    }));
  };

  const declineLoan = (loanId: number, _reason?: string) => {
    setState((prev: any) => ({
      ...prev,
      loans: prev.loans.map((l: Loan) =>
        l.id === loanId
          ? {
              ...l,
              status: 'Rejected',
              approvalStatus: 'Declined',
            }
          : l
      ),
    }));
  };

  const disburseLoan = (
    loanId: number,
    data: {
      disbursementDate: string;
      method: Disbursement['method'];
      reference?: string;
      notes?: string;
    }
  ) => {
    const loan = state.loans.find((l: Loan) => l.id === loanId);
    if (!loan) return;

    const firstDueDate = nextDueDate(data.disbursementDate, loan.repaymentFrequency);
    const generatedSchedule = calculateSchedule(
      loan.principal,
      loan.interestRate,
      loan.interestMethod,
      loan.ratePeriod,
      loan.termMonths,
      firstDueDate,
      loan.repaymentFrequency,
      loan.id
    );

    const nextScheduleIdBase =
      state.schedules.length > 0 ? Math.max(...state.schedules.map((s: RepaymentScheduleItem) => s.id)) + 1 : 1;
    const scheduleItemsWithIds = generatedSchedule.map((item, idx) => ({
      ...item,
      id: nextScheduleIdBase + idx,
    }));

    const maturityDate = scheduleItemsWithIds[scheduleItemsWithIds.length - 1]?.dueDate || firstDueDate;

    const nextDisbId =
      state.disbursements.length > 0 ? Math.max(...state.disbursements.map((d: Disbursement) => d.id)) + 1 : 1;
    const newDisbursement: Disbursement = {
      id: nextDisbId,
      loanId: loan.id,
      amount: loan.principal,
      disbursementDate: data.disbursementDate,
      method: data.method,
      reference: data.reference || `DISB-${loan.loanNo}`,
      disbursedBy: state.currentUser?.id,
      notes: data.notes,
      createdAt: systemDate,
    };

    // Double-entry accounting:
    // 1. Principal: Debit: Loans Receivable (1100), Credit: Cash and Bank (1000)
    // 2. Admin Fee: Debit: Cash and Bank (1000), Credit: Admin Fee Income (4100)
    const nextJId =
      state.journalEntries.length > 0 ? Math.max(...state.journalEntries.map((j: JournalEntry) => j.id)) + 1 : 1;

    const disbJournal: JournalEntry = {
      id: nextJId,
      entryDate: data.disbursementDate,
      reference: `DISB-${loan.loanNo}`,
      sourceType: 'disbursement',
      sourceId: loan.id,
      description: `Disbursement of ${loan.loanNo} - principal payout`,
      createdBy: state.currentUser?.id,
      createdAt: systemDate,
      lines: [
        {
          id: nextJId * 10 + 1,
          journalEntryId: nextJId,
          accountId: 2, // Loans Receivable
          debit: loan.principal,
          credit: 0,
          memo: `Principal booked for ${loan.loanNo}`,
        },
        {
          id: nextJId * 10 + 2,
          journalEntryId: nextJId,
          accountId: 1, // Cash and Bank
          debit: 0,
          credit: loan.principal,
          memo: `Funds paid out via ${data.method}`,
        },
      ],
    };

    const newJournals = [disbJournal];

    if (loan.adminFee > 0) {
      const feeJId = nextJId + 1;
      newJournals.push({
        id: feeJId,
        entryDate: data.disbursementDate,
        reference: `FEE-${loan.loanNo}`,
        sourceType: 'fee',
        sourceId: loan.id,
        description: `Admin fee earned on disbursement of ${loan.loanNo}`,
        createdBy: state.currentUser?.id,
        createdAt: systemDate,
        lines: [
          {
            id: feeJId * 10 + 1,
            journalEntryId: feeJId,
            accountId: 1, // Cash
            debit: loan.adminFee,
            credit: 0,
            memo: `Admin fee collected`,
          },
          {
            id: feeJId * 10 + 2,
            journalEntryId: feeJId,
            accountId: 12, // Admin Fee Income
            debit: 0,
            credit: loan.adminFee,
            memo: `Admin fee recognized`,
          },
        ],
      });
    }

    setState((prev: any) => ({
      ...prev,
      loans: prev.loans.map((l: Loan) =>
        l.id === loanId
          ? {
              ...l,
              status: 'Active',
              disbursementDate: data.disbursementDate,
              firstDueDate,
              maturityDate,
            }
          : l
      ),
      disbursements: [newDisbursement, ...prev.disbursements],
      schedules: [...prev.schedules.filter((s: RepaymentScheduleItem) => s.loanId !== loanId), ...scheduleItemsWithIds],
      journalEntries: [...newJournals, ...prev.journalEntries],
    }));
  };

  const recordRepayment = (data: {
    loanId: number;
    amount: number;
    paymentDate: string;
    method: Repayment['method'];
    reference?: string;
    notes?: string;
  }) => {
    const loan = state.loans.find((l: Loan) => l.id === data.loanId);
    if (!loan) return { success: false, message: 'Loan not found' };

    const loanSchedule = state.schedules.filter((s: RepaymentScheduleItem) => s.loanId === data.loanId);
    if (!loanSchedule.length) return { success: false, message: 'No schedule found for loan' };

    const allocation = allocateRepaymentWaterfall(loanSchedule, data.amount);

    const nextRepayId =
      state.repayments.length > 0 ? Math.max(...state.repayments.map((r: Repayment) => r.id)) + 1 : 1;

    const newRepayment: Repayment = {
      id: nextRepayId,
      loanId: loan.id,
      paymentDate: data.paymentDate,
      amount: data.amount,
      principalPaid: allocation.principalPaid,
      interestPaid: allocation.interestPaid,
      penaltyPaid: allocation.penaltyPaid,
      adminFeePaid: 0,
      method: data.method,
      reference: data.reference || `RPY-${loan.loanNo}-${nextRepayId}`,
      receivedBy: state.currentUser?.id,
      notes: data.notes,
      createdAt: systemDate,
    };

    // Check if entire schedule is now Paid
    const allPaid = allocation.updatedSchedule.every((item) => item.status === 'Paid');

    // Double-entry accounting for Repayment:
    // Debit: Cash (1000) for total amount
    // Credit: Loans Receivable (1100) for principalPaid
    // Credit: Interest Income (4000) for interestPaid
    // Credit: Penalty Fee Income (4200) for penaltyPaid
    const nextJId =
      state.journalEntries.length > 0 ? Math.max(...state.journalEntries.map((j: JournalEntry) => j.id)) + 1 : 1;

    const lines = [
      {
        id: nextJId * 10 + 1,
        journalEntryId: nextJId,
        accountId: 1, // Cash
        debit: data.amount,
        credit: 0,
        memo: `Cash received from ${loan.loanNo}`,
      },
    ];

    if (allocation.principalPaid > 0) {
      lines.push({
        id: nextJId * 10 + 2,
        journalEntryId: nextJId,
        accountId: 2, // Loans Receivable - Principal
        debit: 0,
        credit: allocation.principalPaid,
        memo: `Principal credit on ${loan.loanNo}`,
      });
    }

    if (allocation.interestPaid > 0) {
      lines.push({
        id: nextJId * 10 + 3,
        journalEntryId: nextJId,
        accountId: 11, // Interest Income
        debit: 0,
        credit: allocation.interestPaid,
        memo: `Interest income on ${loan.loanNo}`,
      });
    }

    if (allocation.penaltyPaid > 0) {
      lines.push({
        id: nextJId * 10 + 4,
        journalEntryId: nextJId,
        accountId: 13, // Penalty Fee Income
        debit: 0,
        credit: allocation.penaltyPaid,
        memo: `Penalty fee on ${loan.loanNo}`,
      });
    }

    const repayJournal: JournalEntry = {
      id: nextJId,
      entryDate: data.paymentDate,
      reference: newRepayment.reference || `RPY-${loan.loanNo}`,
      sourceType: 'repayment',
      sourceId: loan.id,
      description: `Repayment received on ${loan.loanNo}`,
      createdBy: state.currentUser?.id,
      createdAt: systemDate,
      lines,
    };

    setState((prev: any) => ({
      ...prev,
      schedules: prev.schedules.map((item: RepaymentScheduleItem) => {
        const updated = allocation.updatedSchedule.find((u) => u.id === item.id);
        return updated || item;
      }),
      loans: prev.loans.map((l: Loan) =>
        l.id === data.loanId
          ? {
              ...l,
              status: allPaid ? 'Closed' : l.status,
            }
          : l
      ),
      repayments: [newRepayment, ...prev.repayments],
      journalEntries: [repayJournal, ...prev.journalEntries],
    }));

    return {
      success: true,
      message: `Repayment of $${data.amount.toFixed(2)} recorded successfully!`,
      allocation,
    };
  };

  const requestRollover = (originalLoanId: number, reason: string): Rollover => {
    const loan = state.loans.find((l: Loan) => l.id === originalLoanId);
    if (!loan) throw new Error('Loan not found');

    const schedule = state.schedules.filter((s: RepaymentScheduleItem) => s.loanId === originalLoanId);
    const unpaidPrincipal = schedule.reduce((sum: number, item: RepaymentScheduleItem) => sum + (item.principalDue - item.principalPaid), 0);

    const nextId = state.rollovers.length > 0 ? Math.max(...state.rollovers.map((r: Rollover) => r.id)) + 1 : 1;
    const newRollover: Rollover = {
      id: nextId,
      originalLoanId,
      rolloverDate: systemDate,
      outstandingBalance: roundMoney(unpaidPrincipal),
      reason,
      status: 'Pending',
      rolloverFee: roundMoney(unpaidPrincipal * 0.03), // 3% rollover fee
      createdAt: systemDate,
    };

    setState((prev: any) => ({
      ...prev,
      rollovers: [newRollover, ...prev.rollovers],
    }));

    return newRollover;
  };

  const approveRollover = (rolloverId: number) => {
    const rollover = state.rollovers.find((r: Rollover) => r.id === rolloverId);
    if (!rollover) return;

    const originalLoan = state.loans.find((l: Loan) => l.id === rollover.originalLoanId);
    if (!originalLoan) return;

    // Create new loan with RN- prefix
    const nextLoanId = state.loans.length > 0 ? Math.max(...state.loans.map((l: Loan) => l.id)) + 1 : 1;
    const rolloverCount = state.loans.filter((l: Loan) => l.loanNo.startsWith('RN-')).length + 1;
    const loanNo = `RN-${String(rolloverCount).padStart(5, '0')}`;

    const newLoan: Loan = {
      id: nextLoanId,
      loanNo,
      clientId: originalLoan.clientId,
      productId: originalLoan.productId,
      principal: rollover.outstandingBalance,
      interestRate: originalLoan.interestRate,
      interestMethod: originalLoan.interestMethod,
      ratePeriod: originalLoan.ratePeriod,
      termMonths: originalLoan.termMonths,
      repaymentFrequency: originalLoan.repaymentFrequency,
      applicationDate: systemDate,
      disbursementDate: systemDate,
      firstDueDate: nextDueDate(systemDate, originalLoan.repaymentFrequency),
      adminFee: rollover.rolloverFee,
      status: 'Active',
      approvalStatus: 'Approved',
      approvedBy: state.currentUser?.id,
      approvedAt: systemDate,
      parentLoanId: originalLoan.id,
      purpose: `Rollover of ${originalLoan.loanNo}: ${rollover.reason || 'Restructuring'}`,
      collateral: originalLoan.collateral,
      createdAt: systemDate,
    };

    // Calculate schedule for new loan
    const newSchedule = calculateSchedule(
      newLoan.principal,
      newLoan.interestRate,
      newLoan.interestMethod,
      newLoan.ratePeriod,
      newLoan.termMonths,
      newLoan.firstDueDate!,
      newLoan.repaymentFrequency,
      newLoan.id
    );
    const nextSchedId =
      state.schedules.length > 0 ? Math.max(...state.schedules.map((s: RepaymentScheduleItem) => s.id)) + 1 : 1;
    const scheduleItems = newSchedule.map((item, idx) => ({ ...item, id: nextSchedId + idx }));

    // Update original loan to RolledOver
    setState((prev: any) => ({
      ...prev,
      rollovers: prev.rollovers.map((r: Rollover) =>
        r.id === rolloverId ? { ...r, status: 'Completed', newLoanId: newLoan.id, approvedBy: state.currentUser?.id } : r
      ),
      loans: [
        newLoan,
        ...prev.loans.map((l: Loan) => (l.id === originalLoan.id ? { ...l, status: 'RolledOver' } : l)),
      ],
      schedules: [...prev.schedules, ...scheduleItems],
    }));
  };

  const writeOffBadDebt = (loanId: number, reason: string) => {
    const loan = state.loans.find((l: Loan) => l.id === loanId);
    if (!loan) return;

    const schedule = state.schedules.filter((s: RepaymentScheduleItem) => s.loanId === loanId);
    const unpPrincipal = schedule.reduce((sum: number, item: RepaymentScheduleItem) => sum + (item.principalDue - item.principalPaid), 0);
    const unpInterest = schedule.reduce((sum: number, item: RepaymentScheduleItem) => sum + (item.interestDue - item.interestPaid), 0);
    const totalWrittenOff = roundMoney(unpPrincipal + unpInterest);

    const nextId = state.badDebts.length > 0 ? Math.max(...state.badDebts.map((b: BadDebt) => b.id)) + 1 : 1;
    const newBadDebt: BadDebt = {
      id: nextId,
      loanId,
      dateWrittenOff: systemDate,
      principalWrittenOff: roundMoney(unpPrincipal),
      interestWrittenOff: roundMoney(unpInterest),
      amountWrittenOff: totalWrittenOff,
      reason,
      approvedBy: state.currentUser?.id,
      status: 'WrittenOff',
      createdAt: systemDate,
    };

    // Accounting entry: Debit: Bad Debts Written Off (5000), Credit: Loans Receivable (1100)
    const nextJId =
      state.journalEntries.length > 0 ? Math.max(...state.journalEntries.map((j: JournalEntry) => j.id)) + 1 : 1;
    const bdJournal: JournalEntry = {
      id: nextJId,
      entryDate: systemDate,
      reference: `WO-${loan.loanNo}`,
      sourceType: 'bad_debt',
      sourceId: loan.id,
      description: `Write-off of delinquent loan ${loan.loanNo}`,
      createdBy: state.currentUser?.id,
      createdAt: systemDate,
      lines: [
        {
          id: nextJId * 10 + 1,
          journalEntryId: nextJId,
          accountId: 16, // Bad Debts Written Off Expense
          debit: totalWrittenOff,
          credit: 0,
          memo: `Write-off loss for ${loan.loanNo}`,
        },
        {
          id: nextJId * 10 + 2,
          journalEntryId: nextJId,
          accountId: 2, // Loans Receivable
          debit: 0,
          credit: roundMoney(unpPrincipal),
          memo: `Principal removed from asset ledger`,
        },
      ],
    };

    setState((prev: any) => ({
      ...prev,
      badDebts: [newBadDebt, ...prev.badDebts],
      loans: prev.loans.map((l: Loan) => (l.id === loanId ? { ...l, status: 'BadDebt' } : l)),
      journalEntries: [bdJournal, ...prev.journalEntries],
    }));
  };

  const recordBadDebtRecovery = (badDebtId: number, amount: number, method: string, reference?: string) => {
    const bd = state.badDebts.find((b: BadDebt) => b.id === badDebtId);
    if (!bd) return;

    const nextId =
      state.badDebtRecoveries.length > 0 ? Math.max(...state.badDebtRecoveries.map((r: BadDebtRecovery) => r.id)) + 1 : 1;
    const newRecovery: BadDebtRecovery = {
      id: nextId,
      badDebtId,
      recoveryDate: systemDate,
      amount,
      method,
      reference: reference || `REC-${bd.id}-${nextId}`,
      receivedBy: state.currentUser?.id,
      createdAt: systemDate,
    };

    // Accounting: Debit: Cash (1000), Credit: Bad Debt Recovery Income (4300)
    const nextJId =
      state.journalEntries.length > 0 ? Math.max(...state.journalEntries.map((j: JournalEntry) => j.id)) + 1 : 1;
    const recJournal: JournalEntry = {
      id: nextJId,
      entryDate: systemDate,
      reference: newRecovery.reference || `REC-${bd.id}`,
      sourceType: 'recovery',
      sourceId: bd.id,
      description: `Recovery on written-off debt #${bd.id}`,
      createdBy: state.currentUser?.id,
      createdAt: systemDate,
      lines: [
        {
          id: nextJId * 10 + 1,
          journalEntryId: nextJId,
          accountId: 1, // Cash
          debit: amount,
          credit: 0,
          memo: `Recovery proceeds collected`,
        },
        {
          id: nextJId * 10 + 2,
          journalEntryId: nextJId,
          accountId: 14, // Bad Debt Recovery Income
          debit: 0,
          credit: amount,
          memo: `Bad debt recovery income recognized`,
        },
      ],
    };

    setState((prev: any) => ({
      ...prev,
      badDebtRecoveries: [newRecovery, ...prev.badDebtRecoveries],
      journalEntries: [recJournal, ...prev.journalEntries],
    }));
  };

  const addExpense = (data: {
    categoryId: number;
    expenseDate: string;
    amount: number;
    paidTo?: string;
    description?: string;
    reference?: string;
  }) => {
    const nextId = state.expenses.length > 0 ? Math.max(...state.expenses.map((e: Expense) => e.id)) + 1 : 1;
    const newExpense: Expense = {
      ...data,
      id: nextId,
      recordedBy: state.currentUser?.id,
      createdAt: systemDate,
    };

    // Accounting: Debit: General Operating Expenses (5900), Credit: Cash (1000)
    const nextJId =
      state.journalEntries.length > 0 ? Math.max(...state.journalEntries.map((j: JournalEntry) => j.id)) + 1 : 1;
    const expJournal: JournalEntry = {
      id: nextJId,
      entryDate: data.expenseDate,
      reference: data.reference || `EXP-${nextId}`,
      sourceType: 'expense',
      sourceId: nextId,
      description: data.description || 'Operating expense disbursement',
      createdBy: state.currentUser?.id,
      createdAt: systemDate,
      lines: [
        {
          id: nextJId * 10 + 1,
          journalEntryId: nextJId,
          accountId: 18, // General Operating Expenses
          debit: data.amount,
          credit: 0,
          memo: data.description || 'Expense paid',
        },
        {
          id: nextJId * 10 + 2,
          journalEntryId: nextJId,
          accountId: 1, // Cash
          debit: 0,
          credit: data.amount,
          memo: `Disbursement to ${data.paidTo || 'vendor'}`,
        },
      ],
    };

    setState((prev: any) => ({
      ...prev,
      expenses: [newExpense, ...prev.expenses],
      journalEntries: [expJournal, ...prev.journalEntries],
    }));
  };

  const addJournalEntry = (entry: Omit<JournalEntry, 'id' | 'createdAt'>): boolean => {
    const totalDebit = entry.lines.reduce((s, l) => s + (l.debit || 0), 0);
    const totalCredit = entry.lines.reduce((s, l) => s + (l.credit || 0), 0);

    if (Math.abs(roundMoney(totalDebit) - roundMoney(totalCredit)) > 0.01) {
      return false; // must be balanced
    }

    const nextId =
      state.journalEntries.length > 0 ? Math.max(...state.journalEntries.map((j: JournalEntry) => j.id)) + 1 : 1;
    const newEntry: JournalEntry = {
      ...entry,
      id: nextId,
      createdAt: systemDate,
      lines: entry.lines.map((l, i) => ({ ...l, id: nextId * 10 + i + 1, journalEntryId: nextId })),
    };

    setState((prev: any) => ({
      ...prev,
      journalEntries: [newEntry, ...prev.journalEntries],
    }));
    return true;
  };

  const addUser = (userData: Omit<User, 'id' | 'createdAt'>) => {
    const nextId = state.users.length > 0 ? Math.max(...state.users.map((u: User) => u.id)) + 1 : 1;
    const newUser: User = { ...userData, id: nextId, createdAt: systemDate };
    setState((prev: any) => ({ ...prev, users: [...prev.users, newUser] }));
  };

  const bulkImportClients = (newClientsData: Array<Omit<Client, 'id' | 'clientNo' | 'createdAt'>>): number => {
    if (!newClientsData || newClientsData.length === 0) return 0;

    let highestId = state.clients.length > 0 ? Math.max(...state.clients.map((c: Client) => c.id)) : 0;
    const addedClients: Client[] = newClientsData.map((data) => {
      highestId += 1;
      return {
        ...data,
        id: highestId,
        clientNo: `CL-${String(highestId).padStart(5, '0')}`,
        createdAt: systemDate,
      };
    });

    setState((prev: any) => ({
      ...prev,
      clients: [...addedClients, ...prev.clients],
    }));

    return addedClients.length;
  };

  const bulkImportLoans = (newLoansData: any[]): number => {
    if (!newLoansData || newLoansData.length === 0) return 0;

    let highestId = state.loans.length > 0 ? Math.max(...state.loans.map((l: Loan) => l.id)) : 0;
    const addedLoans: Loan[] = newLoansData.map((data) => {
      highestId += 1;
      const product = state.loanProducts.find((p: LoanProduct) => p.id === data.productId);
      const adminFeePct = product ? product.adminFeePct : 2.5;
      const adminFee = roundMoney(data.principal * (adminFeePct / 100));

      return {
        id: highestId,
        loanNo: `LN-${String(highestId).padStart(5, '0')}`,
        clientId: data.clientId,
        productId: data.productId,
        principal: data.principal,
        interestRate: data.interestRate,
        interestMethod: data.interestMethod || 'flat',
        ratePeriod: data.ratePeriod || 'month',
        termMonths: data.termMonths || 3,
        repaymentFrequency: data.repaymentFrequency || 'monthly',
        applicationDate: data.applicationDate || systemDate,
        adminFee,
        status: 'Pending',
        approvalStatus: 'Pending',
        purpose: data.purpose || 'Working Capital',
        collateral: data.collateral,
        createdBy: state.currentUser?.id,
        createdAt: systemDate,
      };
    });

    setState((prev: any) => ({
      ...prev,
      loans: [...addedLoans, ...prev.loans],
    }));

    return addedLoans.length;
  };

  const addEmployee = (emp: Omit<Employee, 'id'>) => {
    const nextId = state.employees.length > 0 ? Math.max(...state.employees.map((e: Employee) => e.id)) + 1 : 1;
    const newEmp: Employee = { ...emp, id: nextId };
    setState((prev: any) => ({ ...prev, employees: [...prev.employees, newEmp] }));
  };

  const updateEmployee = (id: number, emp: Partial<Employee>) => {
    setState((prev: any) => ({
      ...prev,
      employees: prev.employees.map((e: Employee) => (e.id === id ? { ...e, ...emp } : e)),
    }));
  };

  const addLocation = (name: string) => {
    if (!state.locations.includes(name.trim())) {
      setState((prev: any) => ({ ...prev, locations: [...prev.locations, name.trim()] }));
    }
  };

  const addLoanProduct = (prod: Omit<LoanProduct, 'id'>) => {
    const nextId = state.loanProducts.length > 0 ? Math.max(...state.loanProducts.map((p: LoanProduct) => p.id)) + 1 : 1;
    const newProd: LoanProduct = { ...prod, id: nextId };
    setState((prev: any) => ({ ...prev, loanProducts: [...prev.loanProducts, newProd] }));
  };

  const updateSettings = (newSettings: SystemSettings) => {
    setState((prev: any) => ({ ...prev, settings: newSettings }));
  };

  const resetDatabase = () => {
    localStorage.removeItem(STORAGE_KEY);
    setState({
      users: INITIAL_USERS,
      clients: INITIAL_CLIENTS,
      loans: INITIAL_LOANS,
      schedules: INITIAL_SCHEDULES,
      disbursements: INITIAL_DISBURSEMENTS,
      repayments: INITIAL_REPAYMENTS,
      rollovers: [],
      badDebts: [],
      badDebtRecoveries: [],
      accounts: INITIAL_ACCOUNTS,
      journalEntries: INITIAL_JOURNAL_ENTRIES,
      expenseCategories: INITIAL_EXPENSE_CATEGORIES,
      expenses: INITIAL_EXPENSES,
      loanProducts: INITIAL_LOAN_PRODUCTS,
      locations: INITIAL_LOCATIONS,
      employees: INITIAL_EMPLOYEES,
      currentUser: INITIAL_USERS[0],
      settings: DEFAULT_SETTINGS,
    });
  };

  const exportDatabaseJson = () => {
    return JSON.stringify(state, null, 2);
  };

  const importDatabaseJson = (json: string): boolean => {
    try {
      const parsed = JSON.parse(json);
      if (parsed.clients && parsed.loans && parsed.accounts) {
        if (!parsed.settings) parsed.settings = DEFAULT_SETTINGS;
        setState(parsed);
        return true;
      }
      return false;
    } catch (e) {
      console.error('Import error:', e);
      return false;
    }
  };

  return (
    <AppContext.Provider
      value={{
        ...state,
        systemDate,
        cloudSyncStatus,
        lastCloudSync,
        refreshFromCloud: () => fetchCloudState(false),
        isTursoActive,
        login,
        logout,
        addClient,
        updateClient,
        createLoanApplication,
        approveLoan,
        declineLoan,
        disburseLoan,
        recordRepayment,
        requestRollover,
        approveRollover,
        writeOffBadDebt,
        recordBadDebtRecovery,
        addExpense,
        addJournalEntry,
        addUser,
        bulkImportClients,
        bulkImportLoans,
        addEmployee,
        updateEmployee,
        addLocation,
        addLoanProduct,
        updateSettings,
        resetDatabase,
        resetToInitialSeed: resetDatabase,
        exportDatabaseJson,
        exportDatabaseJSON: exportDatabaseJson,
        importDatabaseJson,
        importDatabaseJSON: importDatabaseJson,
      }}
    >
      {children}
    </AppContext.Provider>
  );
};

export const useApp = () => {
  const context = useContext(AppContext);
  if (!context) {
    throw new Error('useApp must be used within an AppProvider');
  }
  return context;
};
