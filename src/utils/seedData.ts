import {
  Account,
  Client,
  Disbursement,
  Employee,
  Expense,
  ExpenseCategory,
  JournalEntry,
  Loan,
  LoanProduct,
  Repayment,
  RepaymentScheduleItem,
  User,
} from '../types';

export const INITIAL_USERS: User[] = [
  {
    id: 1,
    username: 'admin',
    fullName: 'System Administrator',
    role: 'admin',
    active: true,
    createdAt: '2026-01-01',
    lastLogin: '2026-09-16 08:30',
  },
  {
    id: 2,
    username: 'm_choto',
    fullName: 'Michael Choto',
    role: 'manager',
    active: true,
    createdAt: '2026-01-15',
    lastLogin: '2026-09-15 16:45',
  },
  {
    id: 3,
    username: 's_ndlovu',
    fullName: 'Sarah Ndlovu',
    role: 'loan_officer',
    active: true,
    createdAt: '2026-02-01',
    lastLogin: '2026-09-16 09:12',
  },
  {
    id: 4,
    username: 'd_moyo',
    fullName: 'David Moyo',
    role: 'teller',
    active: true,
    createdAt: '2026-02-10',
    lastLogin: '2026-09-16 10:05',
  },
];

export const INITIAL_ACCOUNTS: Account[] = [
  { id: 1, code: '1000', name: 'Cash and Bank', type: 'Asset', isControl: true },
  { id: 2, code: '1100', name: 'Loans Receivable - Principal', type: 'Asset', isControl: true },
  { id: 3, code: '1150', name: 'Interest Receivable', type: 'Asset', isControl: true },
  { id: 4, code: '2000', name: 'Accounts Payable', type: 'Liability', isControl: false },
  { id: 5, code: '2050', name: 'Client Credit Balances / Unapplied Payments', type: 'Liability', isControl: true },
  { id: 6, code: '2100', name: 'PAYE Payable', type: 'Liability', isControl: true },
  { id: 7, code: '2150', name: 'NSSA Payable', type: 'Liability', isControl: true },
  { id: 8, code: '2160', name: 'AIDS Levy Payable', type: 'Liability', isControl: true },
  { id: 9, code: '3000', name: "Owner's Capital", type: 'Equity', isControl: false },
  { id: 10, code: '3100', name: 'Retained Earnings', type: 'Equity', isControl: false },
  { id: 11, code: '4000', name: 'Interest Income', type: 'Income', isControl: true },
  { id: 12, code: '4100', name: 'Admin Fee Income', type: 'Income', isControl: true },
  { id: 13, code: '4200', name: 'Penalty Fee Income', type: 'Income', isControl: true },
  { id: 14, code: '4300', name: 'Bad Debt Recovery Income', type: 'Income', isControl: true },
  { id: 15, code: '4500', name: 'Rollover Fee Income', type: 'Income', isControl: true },
  { id: 16, code: '5000', name: 'Bad Debts Written Off', type: 'Expense', isControl: true },
  { id: 17, code: '5100', name: 'Salaries and Wages Expense', type: 'Expense', isControl: true },
  { id: 18, code: '5900', name: 'General Operating Expenses', type: 'Expense', isControl: false },
];

export const INITIAL_EXPENSE_CATEGORIES: ExpenseCategory[] = [
  { id: 1, name: 'Rent', description: 'Office branch lease and rentals' },
  { id: 2, name: 'Salaries and Wages', description: 'Staff payroll & commissions' },
  { id: 3, name: 'Utilities', description: 'Electricity, water, solar backup' },
  { id: 4, name: 'Office Supplies', description: 'Stationery, printing, toner' },
  { id: 5, name: 'Transport', description: 'Field visits, client verification fuel' },
  { id: 6, name: 'Communication', description: 'Internet, telephone, SMS alerts' },
  { id: 7, name: 'Bank Charges', description: 'Bank transfer & ledger fees' },
  { id: 8, name: 'Miscellaneous', description: 'Sundry administrative costs' },
];

export const INITIAL_LOCATIONS = [
  'Harare Central',
  'Bulawayo Central',
  'Mutare',
  'Gweru',
  'Chitungwiza',
  'Chinhoyi',
  'Masvingo',
];

export const INITIAL_LOAN_PRODUCTS: LoanProduct[] = [
  {
    id: 1,
    name: 'Standard Monthly Business Loan',
    interestMethod: 'flat',
    interestRate: 10.0,
    ratePeriod: 'month',
    adminFeePct: 2.5,
    penaltyPct: 5.0,
    gracePeriodDays: 3,
    repaymentFrequency: 'monthly',
    termUnitLabel: 'months',
    active: true,
  },
  {
    id: 2,
    name: 'Non-Standard Weekly Micro-Loan (Flat)',
    interestMethod: 'flat',
    interestRate: 15.0,
    ratePeriod: 'loan_term',
    adminFeePct: 2.0,
    penaltyPct: 5.0,
    gracePeriodDays: 2,
    repaymentFrequency: 'weekly',
    termUnitLabel: 'weeks',
    active: true,
  },
  {
    id: 3,
    name: 'Reducing Balance Working Capital',
    interestMethod: 'reducing_balance',
    interestRate: 8.5,
    ratePeriod: 'month',
    adminFeePct: 2.0,
    penaltyPct: 5.0,
    gracePeriodDays: 5,
    repaymentFrequency: 'monthly',
    termUnitLabel: 'months',
    active: true,
  },
  {
    id: 4,
    name: 'Interest-Only Balloon Loan',
    interestMethod: 'interest_only_balloon',
    interestRate: 18.0,
    ratePeriod: 'month',
    adminFeePct: 3.0,
    penaltyPct: 5.0,
    gracePeriodDays: 3,
    repaymentFrequency: 'monthly',
    termUnitLabel: 'months',
    active: true,
  },
];

// Production Clean Slate: Initialized with zero loans, balances, and clients
export const INITIAL_CLIENTS: Client[] = [];
export const INITIAL_LOANS: Loan[] = [];
export const INITIAL_SCHEDULES: RepaymentScheduleItem[] = [];
export const INITIAL_DISBURSEMENTS: Disbursement[] = [];
export const INITIAL_REPAYMENTS: Repayment[] = [];
export const INITIAL_EXPENSES: Expense[] = [];
export const INITIAL_JOURNAL_ENTRIES: JournalEntry[] = [];
export const INITIAL_EMPLOYEES: Employee[] = [];
