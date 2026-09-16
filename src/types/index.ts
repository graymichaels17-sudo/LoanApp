export type UserRole = 'admin' | 'manager' | 'loan_officer' | 'teller' | 'viewer';

export interface User {
  id: number;
  username: string;
  fullName: string;
  role: UserRole;
  active: boolean;
  lastLogin?: string;
  createdAt: string;
}

export type ClientStatus = 'Active' | 'Inactive' | 'Blacklisted';

export interface Client {
  id: number;
  clientNo: string;
  firstName: string;
  lastName: string;
  nationalId: string;
  gender: 'Male' | 'Female' | 'Other';
  location: string;
  phone: string;
  address: string;
  occupation: string;
  averageIncome: number; // in cents or dollars
  guarantor: string;
  guarantorPhone: string;
  dateRegistered: string;
  status: ClientStatus;
  notes?: string;
  createdBy?: number;
  createdAt: string;
}

export type InterestMethod = 'flat' | 'reducing_balance' | 'interest_only_balloon' | 'interest_only_then_flat';
export type RatePeriod = 'month' | 'year' | 'loan_term';
export type RepaymentFrequency = 'weekly' | 'biweekly' | 'monthly';
export type LoanStatus = 'Pending' | 'Active' | 'Closed' | 'RolledOver' | 'BadDebt' | 'Rejected';
export type ApprovalStatus = 'Pending' | 'Approved' | 'Declined';

export interface LoanProduct {
  id: number;
  name: string;
  interestMethod: InterestMethod;
  interestRate: number; // percentage
  ratePeriod: RatePeriod;
  adminFeePct: number;
  penaltyPct: number;
  gracePeriodDays: number;
  repaymentFrequency: RepaymentFrequency;
  termUnitLabel: string;
  active: boolean;
}

export interface RepaymentScheduleItem {
  id: number;
  loanId: number;
  installmentNo: number;
  dueDate: string;
  principalDue: number; // in dollars/cents
  interestDue: number;
  totalDue: number;
  principalPaid: number;
  interestPaid: number;
  penaltyCharged: number;
  penaltyPaid: number;
  status: 'Pending' | 'PartiallyPaid' | 'Paid' | 'Overdue';
}

export interface Loan {
  id: number;
  loanNo: string;
  clientId: number;
  productId?: number;
  principal: number;
  interestRate: number;
  interestMethod: InterestMethod;
  ratePeriod: RatePeriod;
  termMonths: number;
  repaymentFrequency: RepaymentFrequency;
  applicationDate: string;
  disbursementDate?: string;
  firstDueDate?: string;
  maturityDate?: string;
  adminFee: number;
  status: LoanStatus;
  approvalStatus: ApprovalStatus;
  approvedBy?: number;
  approvedAt?: string;
  parentLoanId?: number;
  purpose?: string;
  collateral?: string;
  createdBy?: number;
  createdAt: string;
}

export interface Disbursement {
  id: number;
  loanId: number;
  amount: number;
  disbursementDate: string;
  method: 'Cash' | 'Bank Transfer' | 'Mobile Money' | 'Cheque' | 'Rollover';
  reference?: string;
  disbursedBy?: number;
  notes?: string;
  createdAt: string;
}

export interface Repayment {
  id: number;
  loanId: number;
  paymentDate: string;
  amount: number;
  principalPaid: number;
  interestPaid: number;
  penaltyPaid: number;
  adminFeePaid: number;
  method: 'Cash' | 'Bank Transfer' | 'Mobile Money' | 'Cheque';
  reference?: string;
  receivedBy?: number;
  notes?: string;
  createdAt: string;
}

export interface Rollover {
  id: number;
  originalLoanId: number;
  newLoanId?: number;
  rolloverDate: string;
  outstandingBalance: number;
  reason?: string;
  status: 'Pending' | 'Completed' | 'Rejected';
  rolloverFee: number;
  approvedBy?: number;
  createdAt: string;
}

export interface BadDebt {
  id: number;
  loanId: number;
  dateWrittenOff: string;
  principalWrittenOff: number;
  interestWrittenOff: number;
  amountWrittenOff: number;
  reason?: string;
  approvedBy?: number;
  status: 'WrittenOff' | 'PartiallyRecovered' | 'FullyRecovered';
  createdAt: string;
}

export interface BadDebtRecovery {
  id: number;
  badDebtId: number;
  recoveryDate: string;
  amount: number;
  method: string;
  reference?: string;
  receivedBy?: number;
  createdAt: string;
}

export type AccountType = 'Asset' | 'Liability' | 'Equity' | 'Income' | 'Expense';

export interface Account {
  id: number;
  code: string;
  name: string;
  type: AccountType;
  isControl: boolean;
}

export interface JournalLine {
  id: number;
  journalEntryId: number;
  accountId: number;
  debit: number;
  credit: number;
  memo?: string;
}

export interface JournalEntry {
  id: number;
  entryDate: string;
  reference: string;
  sourceType: 'disbursement' | 'repayment' | 'fee' | 'expense' | 'bad_debt' | 'recovery' | 'payroll' | 'manual';
  sourceId?: number;
  description: string;
  location?: string;
  createdBy?: number;
  createdAt: string;
  lines: JournalLine[];
}

export interface ExpenseCategory {
  id: number;
  name: string;
  description?: string;
}

export interface Expense {
  id: number;
  categoryId: number;
  expenseDate: string;
  amount: number;
  paidTo?: string;
  description?: string;
  reference?: string;
  recordedBy?: number;
  createdAt: string;
}

export interface Employee {
  id: number;
  employeeNo: string;
  firstName: string;
  lastName: string;
  nationalId?: string;
  jobTitle?: string;
  department?: string;
  dateHired: string;
  basicSalary: number;
  bankName?: string;
  bankAccountNo?: string;
  nssaNumber?: string;
  taxNumber?: string;
  isNssaExempt?: boolean;
  isElderlyOrDisabled?: boolean;
  active: boolean;
}

export interface PayrollPeriod {
  id: number;
  periodLabel: string;
  periodStart: string;
  periodEnd: string;
  payDate: string;
  status: 'Draft' | 'Posted';
  journalEntryId?: number;
  createdBy?: number;
}

export interface Payslip {
  id: number;
  payrollPeriodId?: number;
  employeeId: number;
  periodMonth?: string;
  basicSalary: number;
  allowances?: number;
  grossPay: number;
  grossSalary?: number;
  taxableIncome?: number;
  nssaInsurable?: number;
  paye: number;
  payeTax?: number;
  aidsLevy: number;
  nssaEmployee?: number;
  nssaDeduction?: number;
  nssaEmployer?: number;
  zimdefEmployer?: number;
  otherDeductions: number;
  totalDeductions?: number;
  netPay: number;
  netSalary?: number;
  generatedDate?: string;
}

export interface SystemSettings {
  companyName: string;
  currency: string;
  defaultInterestRate: number;
  defaultPenaltyRate: number;
  gracePeriodDays: number;
  loanProcessingFeeRate: number;
}

export interface SqliteTableColumn {
  name: string;
  type: string;
  notnull: number;
  pk: number;
}

export interface SqliteTableInfo {
  name: string;
  rowCount: number;
  columnCount: number;
  columns: SqliteTableColumn[];
}

export interface SqliteStats {
  engine: string;
  mode?: 'turso' | 'local_sqlite';
  tursoConnected?: boolean;
  tursoUrl?: string;
  dbPath?: string;
  fileSizeBytes?: number;
  fileSizeKb?: number;
  tablesCount: number;
  totalRows: number;
  tables?: SqliteTableInfo[];
  tableDetails?: { name: string; rowCount: number }[];
}

export interface SqlQueryResult {
  success: boolean;
  columns?: string[];
  rows?: any[];
  rowCount?: number;
  changes?: number;
  lastInsertRowid?: number;
  durationMs: number;
  error?: string;
}
