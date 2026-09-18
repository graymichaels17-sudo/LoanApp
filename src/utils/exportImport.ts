import * as XLSX from 'xlsx';
import jsPDF from 'jspdf';
import autoTable from 'jspdf-autotable';
import { Client, Loan, RepaymentScheduleItem, SystemSettings } from '../types';
import { formatMoney } from './money';

// ---------------------------------------------------------------------------
// EXCEL EXPORT UTILITIES
// ---------------------------------------------------------------------------

export interface ExcelSheetData {
  name: string;
  data: Record<string, any>[];
  columnWidths?: number[];
}

/**
 * Generates and triggers download of a multi-sheet or single-sheet Excel workbook (.xlsx)
 */
export const downloadExcelWorkbook = (filename: string, sheets: ExcelSheetData[]) => {
  const wb = XLSX.utils.book_new();

  sheets.forEach((sheet) => {
    // If sheet data is empty, put a placeholder row
    const dataToExport = sheet.data.length > 0 ? sheet.data : [{ 'Status': 'No records found' }];
    const ws = XLSX.utils.json_to_sheet(dataToExport);

    // Auto-compute column widths if not explicitly provided
    if (sheet.columnWidths && sheet.columnWidths.length > 0) {
      ws['!cols'] = sheet.columnWidths.map((w) => ({ wch: w }));
    } else if (dataToExport.length > 0) {
      const keys = Object.keys(dataToExport[0]);
      ws['!cols'] = keys.map((k) => {
        let maxLen = k.length;
        dataToExport.slice(0, 100).forEach((row) => {
          const valStr = row[k] != null ? String(row[k]) : '';
          if (valStr.length > maxLen) maxLen = Math.min(valStr.length, 50);
        });
        return { wch: Math.max(maxLen + 3, 10) };
      });
    }

    // Sheet name must not exceed 31 chars in Excel
    const sanitizedSheetName = sheet.name.replace(/[\\/?*[\]:]/g, '').substring(0, 31);
    XLSX.utils.book_append_sheet(wb, ws, sanitizedSheetName);
  });

  const finalFilename = filename.endsWith('.xlsx') ? filename : `${filename}.xlsx`;
  XLSX.writeFile(wb, finalFilename);
};

// ---------------------------------------------------------------------------
// PDF EXPORT UTILITIES
// ---------------------------------------------------------------------------

interface PDFReportOptions {
  title: string;
  subtitle?: string;
  orientation?: 'portrait' | 'landscape';
  companyName: string;
  systemDate: string;
  filename: string;
  columns: string[];
  rows: (string | number)[][];
  summaryCards?: Array<{ label: string; value: string }>;
}

/**
 * Builds and downloads an institutional, branded PDF report using jsPDF + autoTable
 */
export const downloadPDFReport = (options: PDFReportOptions) => {
  const orientation = options.orientation || 'portrait';
  const doc = new jsPDF({
    orientation,
    unit: 'pt',
    format: 'a4',
  });

  const pageWidth = doc.internal.pageSize.getWidth();
  const pageHeight = doc.internal.pageSize.getHeight();
  const margin = 36; // 0.5 inch margins

  // Header Banner
  doc.setFillColor(15, 23, 42); // Deep slate #0F172A
  doc.rect(0, 0, pageWidth, 54, 'F');

  // Brand text
  doc.setFont('helvetica', 'bold');
  doc.setFontSize(14);
  doc.setTextColor(255, 255, 255);
  doc.text(options.companyName || 'Microfinance Manager', margin, 32);

  doc.setFont('helvetica', 'normal');
  doc.setFontSize(9);
  doc.setTextColor(148, 163, 184); // slate-400
  const headerRightText = `System Date: ${options.systemDate} | Generated: ${new Date().toLocaleTimeString()}`;
  doc.text(headerRightText, pageWidth - margin, 32, { align: 'right' });

  // Report Title & Subtitle
  let currentY = 78;
  doc.setFont('helvetica', 'bold');
  doc.setFontSize(16);
  doc.setTextColor(15, 23, 42);
  doc.text(options.title, margin, currentY);

  if (options.subtitle) {
    currentY += 15;
    doc.setFont('helvetica', 'normal');
    doc.setFontSize(10);
    doc.setTextColor(100, 116, 139);
    doc.text(options.subtitle, margin, currentY);
  }

  // Optional KPI summary cards row
  if (options.summaryCards && options.summaryCards.length > 0) {
    currentY += 16;
    const cardGap = 10;
    const totalWidth = pageWidth - margin * 2;
    const cardWidth = (totalWidth - cardGap * (options.summaryCards.length - 1)) / options.summaryCards.length;
    const cardHeight = 40;

    options.summaryCards.forEach((card, idx) => {
      const cardX = margin + idx * (cardWidth + cardGap);
      doc.setFillColor(248, 250, 252); // slate-50
      doc.setDrawColor(226, 232, 240); // slate-200
      doc.roundedRect(cardX, currentY, cardWidth, cardHeight, 4, 4, 'FD');

      doc.setFont('helvetica', 'normal');
      doc.setFontSize(8);
      doc.setTextColor(100, 116, 139);
      doc.text(card.label.toUpperCase(), cardX + 8, currentY + 14);

      doc.setFont('helvetica', 'bold');
      doc.setFontSize(11);
      doc.setTextColor(15, 23, 42);
      doc.text(card.value, cardX + 8, currentY + 30);
    });

    currentY += cardHeight + 8;
  }

  // Draw table
  autoTable(doc, {
    startY: currentY + 12,
    head: [options.columns],
    body: options.rows,
    theme: 'grid',
    margin: { left: margin, right: margin, bottom: 40 },
    styles: {
      font: 'helvetica',
      fontSize: 8.5,
      cellPadding: 5,
      textColor: [30, 41, 59],
      lineColor: [226, 232, 240],
      lineWidth: 0.5,
    },
    headStyles: {
      fillColor: [30, 58, 138], // Brand Navy Blue
      textColor: [255, 255, 255],
      fontStyle: 'bold',
      fontSize: 8.5,
      halign: 'left',
    },
    alternateRowStyles: {
      fillColor: [248, 250, 252],
    },
    didDrawPage: (data) => {
      // Footer page numbering
      const str = `Page ${data.pageNumber} of ${doc.getNumberOfPages()}`;
      doc.setFont('helvetica', 'normal');
      doc.setFontSize(8);
      doc.setTextColor(148, 163, 184);
      doc.text(str, pageWidth / 2, pageHeight - 16, { align: 'center' });
      doc.text('CONFIDENTIAL • OFFICIAL INSTITUTIONAL RECORD', margin, pageHeight - 16);
    },
  });

  const finalFilename = options.filename.endsWith('.pdf') ? options.filename : `${options.filename}.pdf`;
  doc.save(finalFilename);
};

// ---------------------------------------------------------------------------
// SPECIFIC EXCEL / PDF CONVERTERS
// ---------------------------------------------------------------------------

export const exportClientsToExcel = (clients: Client[], loans: Loan[]) => {
  const data = clients.map((c) => {
    const clientLoans = loans.filter((l) => l.clientId === c.id);
    const activeLoan = clientLoans.find((l) => l.status === 'Active');
    return {
      'Client No': c.clientNo,
      'First Name': c.firstName,
      'Last Name': c.lastName,
      'National ID': c.nationalId,
      'Phone': c.phone,
      'Gender': c.gender,
      'Location / Branch': c.location,
      'Occupation': c.occupation || '-',
      'Avg Monthly Income': c.averageIncome || 0,
      'Guarantor Name': c.guarantor || '-',
      'Guarantor Phone': c.guarantorPhone || '-',
      'Registration Date': c.dateRegistered,
      'Status': c.status,
      'Total Loans Taken': clientLoans.length,
      'Active Loan #': activeLoan ? activeLoan.loanNo : 'None',
      'Active Principal': activeLoan ? activeLoan.principal : 0,
      'Address': c.address || '-',
    };
  });

  downloadExcelWorkbook(`microfinance_clients_${new Date().toISOString().slice(0, 10)}`, [
    { name: 'Clients Registry', data },
  ]);
};

export const exportClientsToPDF = (clients: Client[], settings: SystemSettings, systemDate: string) => {
  const columns = ['Client #', 'Full Name', 'National ID', 'Phone', 'Location', 'Status', 'Registered'];
  const rows = clients.map((c) => [
    c.clientNo,
    `${c.firstName} ${c.lastName}`,
    c.nationalId,
    c.phone,
    c.location,
    c.status,
    c.dateRegistered,
  ]);

  downloadPDFReport({
    title: 'Borrower KYC & Client Registry',
    subtitle: `Complete listing of ${clients.length} registered microfinance borrowers`,
    companyName: settings.companyName,
    systemDate,
    filename: `clients_registry_${systemDate}.pdf`,
    columns,
    rows,
    summaryCards: [
      { label: 'Total Borrowers', value: clients.length.toString() },
      { label: 'Active Borrowers', value: clients.filter((c) => c.status === 'Active').length.toString() },
      { label: 'Blacklisted', value: clients.filter((c) => c.status === 'Blacklisted').length.toString() },
    ],
  });
};

export const exportLoansToExcel = (loans: Loan[], clients: Client[]) => {
  const data = loans.map((l) => {
    const c = clients.find((client) => client.id === l.clientId);
    const totalPayable = (l as any).totalPayable || l.principal;
    const totalRepaid = (l as any).totalRepaid || 0;
    return {
      'Loan #': l.loanNo,
      'Borrower': c ? `${c.firstName} ${c.lastName}` : `Client #${l.clientId}`,
      'National ID': c?.nationalId || '-',
      'Phone': c?.phone || '-',
      'Branch': c?.location || '-',
      'Status': l.status,
      'Principal': l.principal,
      'Interest Rate (%)': l.interestRate,
      'Rate Period': l.ratePeriod,
      'Interest Method': l.interestMethod,
      'Term': `${l.termMonths} ${l.repaymentFrequency}`,
      'Total Payable': totalPayable,
      'Total Repaid': totalRepaid,
      'Application Date': l.applicationDate,
      'Disbursed Date': l.disbursementDate || '-',
      'Maturity Date': l.maturityDate || '-',
      'Purpose': l.purpose || '-',
      'Collateral': l.collateral || '-',
    };
  });

  downloadExcelWorkbook(`microfinance_loans_${new Date().toISOString().slice(0, 10)}`, [
    { name: 'Loan Portfolio', data },
  ]);
};

export const exportLoansToPDF = (loans: Loan[], clients: Client[], settings: SystemSettings, systemDate: string) => {
  const columns = ['Loan #', 'Borrower', 'Principal', 'Rate', 'Method', 'Term', 'Payable', 'Status'];
  const rows = loans.map((l) => {
    const c = clients.find((client) => client.id === l.clientId);
    const totalPayable = (l as any).totalPayable || l.principal;
    return [
      l.loanNo,
      c ? `${c.firstName} ${c.lastName}` : `Client #${l.clientId}`,
      formatMoney(l.principal),
      `${l.interestRate}% / ${l.ratePeriod}`,
      l.interestMethod.replace('_', ' '),
      `${l.termMonths} ${l.repaymentFrequency}`,
      formatMoney(totalPayable),
      l.status,
    ];
  });

  const totalPrincipal = loans.reduce((s, l) => s + l.principal, 0);
  const totalActive = loans.filter((l) => l.status === 'Active').reduce((s, l) => s + l.principal, 0);

  downloadPDFReport({
    title: 'Loan Portfolio & Workflow Register',
    subtitle: `Comprehensive register of ${loans.length} institutional loan applications and accounts`,
    orientation: 'landscape',
    companyName: settings.companyName,
    systemDate,
    filename: `loan_portfolio_${systemDate}.pdf`,
    columns,
    rows,
    summaryCards: [
      { label: 'Total Loans', value: loans.length.toString() },
      { label: 'Total Disbursed Volume', value: formatMoney(totalPrincipal) },
      { label: 'Active Outstanding Principal', value: formatMoney(totalActive) },
      { label: 'Pending Approvals', value: loans.filter((l) => l.status === 'Pending').length.toString() },
    ],
  });
};

export const exportScheduleToPDF = (
  loan: Loan,
  client: Client | undefined,
  schedule: RepaymentScheduleItem[],
  settings: SystemSettings,
  systemDate: string
) => {
  const columns = ['#', 'Due Date', 'Principal Due', 'Interest Due', 'Total Due', 'Paid', 'Balance', 'Status'];
  const rows = schedule.map((s) => {
    const paid = s.principalPaid + s.interestPaid + s.penaltyPaid;
    const remaining = Math.max(0, s.totalDue - paid);
    return [
      s.installmentNo.toString(),
      s.dueDate,
      formatMoney(s.principalDue),
      formatMoney(s.interestDue),
      formatMoney(s.totalDue),
      formatMoney(paid),
      formatMoney(remaining),
      s.status,
    ];
  });

  const clientName = client ? `${client.firstName} ${client.lastName}` : `Client #${loan.clientId}`;
  const totalPayable = (loan as any).totalPayable || loan.principal;

  downloadPDFReport({
    title: `Amortization Schedule: Loan #${loan.loanNo}`,
    subtitle: `Borrower: ${clientName} (${client?.nationalId || '-'}) | Phone: ${client?.phone || '-'}`,
    companyName: settings.companyName,
    systemDate,
    filename: `loan_schedule_${loan.loanNo}.pdf`,
    columns,
    rows,
    summaryCards: [
      { label: 'Loan Principal', value: formatMoney(loan.principal) },
      { label: 'Interest Rate', value: `${loan.interestRate}% (${loan.interestMethod.replace('_', ' ')})` },
      { label: 'Total Repayable', value: formatMoney(totalPayable) },
      { label: 'Disbursement Date', value: loan.disbursementDate || 'Pending' },
    ],
  });
};

export const exportScheduleToExcel = (
  loan: Loan,
  client: Client | undefined,
  schedule: RepaymentScheduleItem[]
) => {
  const clientName = client ? `${client.firstName} ${client.lastName}` : `Client #${loan.clientId}`;

  const metaData = [
    { 'Parameter': 'Loan Number', 'Value': loan.loanNo },
    { 'Parameter': 'Borrower Name', 'Value': clientName },
    { 'Parameter': 'Borrower National ID', 'Value': client?.nationalId || '-' },
    { 'Parameter': 'Borrower Phone', 'Value': client?.phone || '-' },
    { 'Parameter': 'Loan Status', 'Value': loan.status },
    { 'Parameter': 'Disbursed Principal', 'Value': loan.principal },
    { 'Parameter': 'Interest Rate', 'Value': `${loan.interestRate}%` },
    { 'Parameter': 'Interest Calculation Method', 'Value': loan.interestMethod },
    { 'Parameter': 'Repayment Term', 'Value': `${loan.termMonths} ${loan.repaymentFrequency}` },
    { 'Parameter': 'Disbursement Date', 'Value': loan.disbursementDate || '-' },
    { 'Parameter': 'Maturity Date', 'Value': loan.maturityDate || '-' },
  ];

  const scheduleData = schedule.map((s) => {
    const paid = s.principalPaid + s.interestPaid + s.penaltyPaid;
    const remaining = Math.max(0, s.totalDue - paid);
    return {
      'Installment #': s.installmentNo,
      'Due Date': s.dueDate,
      'Principal Due': s.principalDue,
      'Interest Due': s.interestDue,
      'Total Due': s.totalDue,
      'Principal Paid': s.principalPaid,
      'Interest Paid': s.interestPaid,
      'Penalty Charged': s.penaltyCharged || 0,
      'Penalty Paid': s.penaltyPaid || 0,
      'Remaining Balance': remaining,
      'Status': s.status,
    };
  });

  downloadExcelWorkbook(`amortization_schedule_${loan.loanNo}`, [
    { name: 'Amortization Schedule', data: scheduleData },
    { name: 'Loan Information', data: metaData },
  ]);
};

/**
 * Full Institutional Multi-Sheet Excel Backup & Export
 */
export const exportFullDatabaseToExcel = (state: any) => {
  const sheets: ExcelSheetData[] = [];

  // Clients
  if (state.clients && state.clients.length > 0) {
    sheets.push({
      name: 'Clients',
      data: state.clients.map((c: Client) => ({
        'Client ID': c.id,
        'Client No': c.clientNo,
        'First Name': c.firstName,
        'Last Name': c.lastName,
        'National ID': c.nationalId,
        'Gender': c.gender,
        'Location': c.location,
        'Phone': c.phone,
        'Address': c.address || '',
        'Occupation': c.occupation || '',
        'Income': c.averageIncome || 0,
        'Guarantor': c.guarantor || '',
        'Guarantor Phone': c.guarantorPhone || '',
        'Status': c.status,
        'Registered': c.dateRegistered,
      })),
    });
  }

  // Loans
  if (state.loans && state.loans.length > 0) {
    sheets.push({
      name: 'Loans',
      data: state.loans.map((l: Loan) => {
        const c = state.clients?.find((cl: Client) => cl.id === l.clientId);
        return {
          'Loan ID': l.id,
          'Loan No': l.loanNo,
          'Client ID': l.clientId,
          'Borrower': c ? `${c.firstName} ${c.lastName}` : `Client #${l.clientId}`,
          'Principal': l.principal,
          'Interest Rate': l.interestRate,
          'Rate Period': l.ratePeriod,
          'Method': l.interestMethod,
          'Term': l.termMonths,
          'Frequency': l.repaymentFrequency,
          'Status': l.status,
          'Application Date': l.applicationDate,
          'Disbursement Date': l.disbursementDate || '',
          'Maturity Date': l.maturityDate || '',
          'Total Payable': (l as any).totalPayable || l.principal,
          'Total Repaid': (l as any).totalRepaid || 0,
        };
      }),
    });
  }

  // Repayments
  if (state.repayments && state.repayments.length > 0) {
    sheets.push({
      name: 'Repayments',
      data: state.repayments.map((r: any) => ({
        'ID': r.id,
        'Loan ID': r.loanId,
        'Date': r.paymentDate,
        'Total Amount': r.amount,
        'Principal Paid': r.principalPaid,
        'Interest Paid': r.interestPaid,
        'Penalty Paid': r.penaltyPaid,
        'Method': r.method,
        'Reference': r.reference || '',
        'Notes': r.notes || '',
      })),
    });
  }

  // Disbursements
  if (state.disbursements && state.disbursements.length > 0) {
    sheets.push({
      name: 'Disbursements',
      data: state.disbursements.map((d: any) => ({
        'ID': d.id,
        'Loan ID': d.loanId,
        'Date': d.disbursementDate,
        'Amount': d.amount,
        'Method': d.method,
        'Reference': d.reference || '',
        'Notes': d.notes || '',
      })),
    });
  }

  // Accounts
  if (state.accounts && state.accounts.length > 0) {
    sheets.push({
      name: 'Chart of Accounts',
      data: state.accounts.map((a: any) => ({
        'Code': a.code,
        'Account Name': a.name,
        'Type': a.type,
        'Control Account': a.isControl ? 'Yes' : 'No',
      })),
    });
  }

  // Journal Entries
  if (state.journalEntries && state.journalEntries.length > 0) {
    sheets.push({
      name: 'General Ledger',
      data: state.journalEntries.map((j: any) => ({
        'Entry ID': j.id,
        'Date': j.date,
        'Reference': j.reference,
        'Description': j.description,
        'Debit Account': j.debitAccountCode,
        'Credit Account': j.creditAccountCode,
        'Amount': j.amount,
      })),
    });
  }

  // Employees
  if (state.employees && state.employees.length > 0) {
    sheets.push({
      name: 'Employees',
      data: state.employees.map((e: any) => ({
        'Code': e.employeeCode,
        'Name': e.fullName,
        'National ID': e.nationalId,
        'Designation': e.designation,
        'Branch': e.branch,
        'Basic Salary': e.basicSalary,
        'Active': e.active ? 'Yes' : 'No',
      })),
    });
  }

  downloadExcelWorkbook(`microfinance_full_backup_${new Date().toISOString().slice(0, 10)}`, sheets);
};

// ---------------------------------------------------------------------------
// EXCEL IMPORT & PARSING UTILITIES
// ---------------------------------------------------------------------------

/**
 * Reads an uploaded Excel / CSV file and returns JSON data per sheet
 */
export const readExcelFile = async (file: File): Promise<Record<string, any[]>> => {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();

    reader.onload = (e) => {
      try {
        const data = new Uint8Array(e.target?.result as ArrayBuffer);
        const workbook = XLSX.read(data, { type: 'array' });
        const result: Record<string, any[]> = {};

        workbook.SheetNames.forEach((sheetName) => {
          const worksheet = workbook.Sheets[sheetName];
          const json = XLSX.utils.sheet_to_json(worksheet, { defval: '' });
          result[sheetName] = json as any[];
        });

        resolve(result);
      } catch (err) {
        reject(err);
      }
    };

    reader.onerror = (err) => reject(err);
    reader.readAsArrayBuffer(file);
  });
};

/**
 * Normalizes keys to handle loose header names (e.g., "First Name", "firstName", "First_Name")
 */
const findValueByKeys = (row: Record<string, any>, candidateKeys: string[]): any => {
  const rowKeys = Object.keys(row);
  for (const candidate of candidateKeys) {
    const matchedKey = rowKeys.find(
      (k) => k.trim().toLowerCase().replace(/[^a-z0-9]/g, '') === candidate.toLowerCase().replace(/[^a-z0-9]/g, '')
    );
    if (matchedKey && row[matchedKey] !== undefined && row[matchedKey] !== '') {
      return row[matchedKey];
    }
  }
  return undefined;
};

export interface ParsedClientsResult {
  valid: Array<Omit<Client, 'id' | 'clientNo' | 'createdAt'>>;
  errors: Array<{ row: number; reason: string }>;
  warnings: Array<{ row: number; warning: string }>;
}

export const parseClientsFromExcel = (rows: Record<string, any>[], defaultLocation = 'Harare Central'): ParsedClientsResult => {
  const valid: Array<Omit<Client, 'id' | 'clientNo' | 'createdAt'>> = [];
  const errors: Array<{ row: number; reason: string }> = [];
  const warnings: Array<{ row: number; warning: string }> = [];

  rows.forEach((row, index) => {
    const rowNum = index + 2; // account for header row in Excel

    const firstName = findValueByKeys(row, ['firstName', 'first_name', 'first name', 'fname', 'name']);
    const lastName = findValueByKeys(row, ['lastName', 'last_name', 'last name', 'surname', 'lname']);
    const nationalId = findValueByKeys(row, ['nationalId', 'national_id', 'national id', 'id number', 'idno', 'id']);
    const phone = findValueByKeys(row, ['phone', 'phonenumber', 'phone number', 'mobile', 'cell', 'telephone']);
    const genderRaw = findValueByKeys(row, ['gender', 'sex']);
    const locationRaw = findValueByKeys(row, ['location', 'branch', 'city', 'town']);
    const occupation = findValueByKeys(row, ['occupation', 'job', 'business', 'profession']);
    const incomeRaw = findValueByKeys(row, ['averageIncome', 'income', 'monthly income', 'avg income', 'salary']);
    const address = findValueByKeys(row, ['address', 'physical address', 'residence']);
    const guarantor = findValueByKeys(row, ['guarantor', 'guarantor name', 'next of kin']);
    const guarantorPhone = findValueByKeys(row, ['guarantorPhone', 'guarantor phone', 'kin phone']);
    const statusRaw = findValueByKeys(row, ['status']);

    if (!firstName && !lastName && !nationalId) {
      // Empty row or blank line
      return;
    }

    if (!firstName) {
      errors.push({ row: rowNum, reason: 'Missing First Name' });
      return;
    }
    if (!lastName) {
      errors.push({ row: rowNum, reason: 'Missing Last Name' });
      return;
    }
    if (!nationalId) {
      errors.push({ row: rowNum, reason: 'Missing National ID' });
      return;
    }

    const gender = String(genderRaw || '').toLowerCase().startsWith('f') ? 'Female' : 'Male';
    const status: Client['status'] =
      String(statusRaw || '').toLowerCase().includes('black')
        ? 'Blacklisted'
        : String(statusRaw || '').toLowerCase().includes('inact')
        ? 'Inactive'
        : 'Active';

    const income = typeof incomeRaw === 'number' ? incomeRaw : parseFloat(String(incomeRaw || '0').replace(/[^0-9.]/g, '')) || 0;

    if (!phone) {
      warnings.push({ row: rowNum, warning: 'Phone number is empty' });
    }

    valid.push({
      firstName: String(firstName).trim(),
      lastName: String(lastName).trim(),
      nationalId: String(nationalId).trim(),
      gender,
      location: locationRaw ? String(locationRaw).trim() : defaultLocation,
      phone: phone ? String(phone).trim() : 'N/A',
      address: address ? String(address).trim() : '',
      occupation: occupation ? String(occupation).trim() : 'Trader',
      averageIncome: income,
      guarantor: guarantor ? String(guarantor).trim() : '',
      guarantorPhone: guarantorPhone ? String(guarantorPhone).trim() : '',
      dateRegistered: new Date().toISOString().slice(0, 10),
      status,
      notes: `Imported via Excel on ${new Date().toLocaleDateString()}`,
    });
  });

  return { valid, errors, warnings };
};

export interface ParsedLoansResult {
  valid: Array<{
    clientId: number;
    principal: number;
    interestRate: number;
    interestMethod: any;
    ratePeriod: any;
    termMonths: number;
    repaymentFrequency: any;
    applicationDate: string;
    purpose?: string;
    collateral?: string;
  }>;
  errors: Array<{ row: number; reason: string }>;
  warnings: Array<{ row: number; warning: string }>;
}

export const parseLoansFromExcel = (
  rows: Record<string, any>[],
  existingClients: Client[]
): ParsedLoansResult => {
  const valid: ParsedLoansResult['valid'] = [];
  const errors: ParsedLoansResult['errors'] = [];
  const warnings: ParsedLoansResult['warnings'] = [];

  rows.forEach((row, index) => {
    const rowNum = index + 2;

    const clientIdentifier = findValueByKeys(row, ['clientNo', 'client id', 'national id', 'client', 'borrower']);
    const principalRaw = findValueByKeys(row, ['principal', 'amount', 'loan amount']);
    const interestRateRaw = findValueByKeys(row, ['interestRate', 'rate', 'interest %', 'interest']);
    const termRaw = findValueByKeys(row, ['termMonths', 'term', 'duration', 'months', 'weeks']);
    const methodRaw = findValueByKeys(row, ['interestMethod', 'method', 'type']);
    const purpose = findValueByKeys(row, ['purpose', 'reason', 'use']);

    if (!clientIdentifier && !principalRaw) return;

    // Resolve client
    let matchedClient = existingClients.find(
      (c) =>
        c.clientNo?.toLowerCase() === String(clientIdentifier).toLowerCase() ||
        c.nationalId?.toLowerCase() === String(clientIdentifier).toLowerCase() ||
        `${c.firstName} ${c.lastName}`.toLowerCase() === String(clientIdentifier).toLowerCase() ||
        c.id === Number(clientIdentifier)
    );

    if (!matchedClient) {
      errors.push({
        row: rowNum,
        reason: `Could not match borrower '${clientIdentifier}' to any registered client. Please register client first.`,
      });
      return;
    }

    const principal = parseFloat(String(principalRaw || '0').replace(/[^0-9.]/g, ''));
    if (!principal || principal <= 0) {
      errors.push({ row: rowNum, reason: 'Invalid or missing loan principal amount' });
      return;
    }

    const interestRate = parseFloat(String(interestRateRaw || '10').replace(/[^0-9.]/g, '')) || 10;
    const termMonths = parseInt(String(termRaw || '3'), 10) || 3;

    let interestMethod: any = 'flat';
    if (String(methodRaw || '').toLowerCase().includes('reduc')) {
      interestMethod = 'reducing_balance';
    } else if (String(methodRaw || '').toLowerCase().includes('balloon')) {
      interestMethod = 'interest_only_balloon';
    }

    valid.push({
      clientId: matchedClient.id,
      principal,
      interestRate,
      interestMethod,
      ratePeriod: 'month',
      termMonths,
      repaymentFrequency: 'monthly',
      applicationDate: new Date().toISOString().slice(0, 10),
      purpose: purpose ? String(purpose) : 'Working Capital',
    });
  });

  return { valid, errors, warnings };
};

/**
 * Downloads standard Excel templates for users to populate
 */
export const downloadClientsExcelTemplate = () => {
  const sampleData = [
    {
      'First Name': 'Tinashe',
      'Last Name': 'Moyo',
      'National ID': '63-123456-A-78',
      'Phone': '+263 77 123 4567',
      'Gender': 'Male',
      'Location': 'Harare Central',
      'Occupation': 'Grocery Retailer',
      'Monthly Income': 850,
      'Guarantor Name': 'Grace Moyo',
      'Guarantor Phone': '+263 71 987 6543',
      'Address': 'Shop 12, Gulf Complex, Harare',
      'Status': 'Active',
    },
    {
      'First Name': 'Chipo',
      'Last Name': 'Sibanda',
      'National ID': '08-987654-B-12',
      'Phone': '+263 78 555 4321',
      'Gender': 'Female',
      'Location': 'Bulawayo Central',
      'Occupation': 'Poultry Farmer',
      'Monthly Income': 1200,
      'Guarantor Name': 'John Sibanda',
      'Guarantor Phone': '+263 77 222 3344',
      'Address': 'Plot 4, Umguza, Bulawayo',
      'Status': 'Active',
    },
  ];

  downloadExcelWorkbook('clients_import_template.xlsx', [{ name: 'Clients Template', data: sampleData }]);
};

export const downloadLoansExcelTemplate = (existingClients: Client[]) => {
  const sampleClient = existingClients[0] || { clientNo: 'CL-0001', nationalId: '63-123456-A-78' };

  const sampleData = [
    {
      'Borrower ID or National ID': sampleClient.clientNo,
      'Principal Amount': 1500,
      'Interest Rate (%)': 10,
      'Term (Months)': 3,
      'Method (flat / reducing_balance / balloon)': 'flat',
      'Purpose': 'Inventory expansion',
    },
  ];

  downloadExcelWorkbook('loans_import_template.xlsx', [{ name: 'Loans Template', data: sampleData }]);
};
