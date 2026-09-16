import React, { useState, useEffect, useRef } from 'react';
import {
  Search,
  Users,
  Coins,
  LayoutDashboard,
  FileSpreadsheet,
  Scale,
  Receipt,
  Settings,
  Database,
  ArrowRight,
  PlusCircle,
  UserPlus,
  ArrowDownLeft,
  X,
} from 'lucide-react';
import { useApp } from '../../context/AppContext';
import { ActiveTab } from '../layout/Sidebar';
import { formatMoney } from '../../utils/money';

interface CommandPaletteProps {
  isOpen: boolean;
  onClose: () => void;
  onNavigate: (tab: ActiveTab, subTab?: string) => void;
  onOpenQuickRepayment: () => void;
  onOpenNewClient: () => void;
  onOpenNewLoan: () => void;
}

export const CommandPalette: React.FC<CommandPaletteProps> = ({
  isOpen,
  onClose,
  onNavigate,
  onOpenQuickRepayment,
  onOpenNewClient,
  onOpenNewLoan,
}) => {
  const { clients, loans } = useApp();
  const [query, setQuery] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (isOpen) {
      setQuery('');
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [isOpen]);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault();
        if (isOpen) onClose();
        else {
          // Open
        }
      } else if (e.key === 'Escape' && isOpen) {
        onClose();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  const cleanQuery = query.trim().toLowerCase();

  interface NavItem {
    id: string;
    label: string;
    tab: ActiveTab;
    icon: any;
    category: string;
  }

  const NAV_ITEMS: NavItem[] = [
    { id: 'nav-dash', label: 'Portfolio Dashboard', tab: 'dashboard', icon: LayoutDashboard, category: 'Navigation' },
    { id: 'nav-clients', label: 'Client Registry & Profiles', tab: 'clients', icon: Users, category: 'Navigation' },
    { id: 'nav-loans', label: 'Loans & Disbursal Workflows', tab: 'loans', icon: Coins, category: 'Navigation' },
    { id: 'nav-reports', label: 'Portfolio Reports & PAR Aging', tab: 'reports', icon: FileSpreadsheet, category: 'Navigation' },
    { id: 'nav-acc', label: 'General Ledger & Financial Statements', tab: 'accounting', icon: Scale, category: 'Navigation' },
    { id: 'nav-pay', label: 'Statutory Payroll & Payslips', tab: 'payroll', icon: Receipt, category: 'Navigation' },
    { id: 'nav-sql', label: 'SQLite 3 Database Studio', tab: 'sqlite', icon: Database, category: 'Navigation' },
    { id: 'nav-set', label: 'System Settings & Backups', tab: 'settings', icon: Settings, category: 'Navigation' },
  ];

  const matchingNav = NAV_ITEMS.filter((item) => item.label.toLowerCase().includes(cleanQuery));

  const matchingActions = [
    {
      id: 'act-repay',
      label: 'Record Loan Repayment',
      icon: ArrowDownLeft,
      action: () => {
        onClose();
        onOpenQuickRepayment();
      },
      category: 'Actions',
    },
    {
      id: 'act-new-client',
      label: 'Register New Client',
      icon: UserPlus,
      action: () => {
        onClose();
        onOpenNewClient();
      },
      category: 'Actions',
    },
    {
      id: 'act-new-loan',
      label: 'Create Loan Application',
      icon: PlusCircle,
      action: () => {
        onClose();
        onOpenNewLoan();
      },
      category: 'Actions',
    },
    {
      id: 'act-sql-integrity',
      label: 'Run SQLite PRAGMA Integrity Check',
      icon: Database,
      action: () => {
        onClose();
        onNavigate('sqlite');
      },
      category: 'Actions',
    },
  ].filter((item) => item.label.toLowerCase().includes(cleanQuery));

  const matchingClients = clients
    .filter(
      (c) =>
        c.firstName.toLowerCase().includes(cleanQuery) ||
        c.lastName.toLowerCase().includes(cleanQuery) ||
        c.clientNo.toLowerCase().includes(cleanQuery) ||
        (c.nationalId && c.nationalId.toLowerCase().includes(cleanQuery)) ||
        (c.phone && c.phone.toLowerCase().includes(cleanQuery)) ||
        c.location.toLowerCase().includes(cleanQuery)
    )
    .slice(0, 5);

  const matchingLoans = loans
    .filter((l) => {
      const client = clients.find((c) => c.id === l.clientId);
      const clientName = client ? `${client.firstName} ${client.lastName}`.toLowerCase() : '';
      return (
        l.loanNo.toLowerCase().includes(cleanQuery) ||
        l.status.toLowerCase().includes(cleanQuery) ||
        clientName.includes(cleanQuery)
      );
    })
    .slice(0, 5);

  const allItemsCount =
    matchingNav.length + matchingActions.length + matchingClients.length + matchingLoans.length;

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto bg-slate-900/60 dark:bg-black/80 backdrop-blur-xs flex items-start justify-center pt-16 sm:pt-24 px-4">
      <div className="relative w-full max-w-xl bg-white dark:bg-[#0F172A] border border-slate-200 dark:border-slate-800 rounded-2xl shadow-2xl overflow-hidden flex flex-col transition-all">
        {/* Search Input Bar */}
        <div className="flex items-center px-4 py-3.5 border-b border-slate-100 dark:border-slate-800/80 gap-3">
          <Search className="w-5 h-5 text-slate-400 dark:text-slate-500 shrink-0" />
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Type a command, search client, loan #, or accounts..."
            className="w-full bg-transparent text-sm font-medium text-slate-800 dark:text-slate-100 placeholder-slate-400 dark:placeholder-slate-500 focus:outline-none"
          />
          {query ? (
            <button
              onClick={() => setQuery('')}
              className="p-1 rounded-md text-slate-400 hover:text-slate-600 dark:hover:text-slate-200"
            >
              <X className="w-4 h-4" />
            </button>
          ) : (
            <kbd className="hidden sm:inline-block font-mono text-[10px] bg-slate-100 dark:bg-slate-800 text-slate-500 px-1.5 py-0.5 rounded border border-slate-200 dark:border-slate-700">
              ESC
            </kbd>
          )}
        </div>

        {/* Results List */}
        <div className="max-h-[60vh] overflow-y-auto p-2 space-y-4">
          {allItemsCount === 0 && (
            <div className="py-12 text-center text-slate-400 dark:text-slate-500 text-xs">
              No matching clients, loans, or commands found for "{query}".
            </div>
          )}

          {/* Quick Actions */}
          {matchingActions.length > 0 && (
            <div>
              <p className="px-3 py-1 text-[10px] font-bold uppercase tracking-wider text-slate-400 dark:text-slate-500">
                Quick Actions
              </p>
              <div className="space-y-0.5">
                {matchingActions.map((item) => {
                  const Icon = item.icon;
                  return (
                    <button
                      key={item.id}
                      onClick={item.action}
                      className="w-full flex items-center justify-between px-3 py-2 rounded-xl text-left text-xs font-semibold text-slate-700 dark:text-slate-200 hover:bg-blue-50 dark:hover:bg-blue-950/40 hover:text-blue-600 dark:hover:text-blue-400 transition-colors group"
                    >
                      <div className="flex items-center gap-2.5">
                        <div className="w-6 h-6 rounded-lg bg-blue-100 dark:bg-blue-900/40 text-blue-600 dark:text-blue-400 flex items-center justify-center">
                          <Icon className="w-3.5 h-3.5" />
                        </div>
                        <span>{item.label}</span>
                      </div>
                      <ArrowRight className="w-3.5 h-3.5 opacity-0 group-hover:opacity-100 transition-opacity text-blue-500" />
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          {/* Matching Clients */}
          {matchingClients.length > 0 && (
            <div>
              <p className="px-3 py-1 text-[10px] font-bold uppercase tracking-wider text-slate-400 dark:text-slate-500">
                Clients
              </p>
              <div className="space-y-0.5">
                {matchingClients.map((client) => (
                  <button
                    key={client.id}
                    onClick={() => {
                      onClose();
                      onNavigate('clients');
                    }}
                    className="w-full flex items-center justify-between px-3 py-2 rounded-xl text-left text-xs text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800/60 transition-colors"
                  >
                    <div className="flex items-center gap-2.5">
                      <div className="w-6 h-6 rounded-lg bg-emerald-100 dark:bg-emerald-900/40 text-emerald-600 dark:text-emerald-400 flex items-center justify-center font-bold text-[10px]">
                        {client.firstName[0]}
                        {client.lastName[0]}
                      </div>
                      <div>
                        <span className="font-semibold text-slate-800 dark:text-white">
                          {client.firstName} {client.lastName}
                        </span>
                        <span className="text-[11px] font-mono text-slate-400 ml-2">
                          {client.clientNo} • {client.location}
                        </span>
                      </div>
                    </div>
                    <span className="text-[10px] px-2 py-0.5 rounded bg-emerald-50 dark:bg-emerald-950/60 text-emerald-700 dark:text-emerald-400 border border-emerald-200 dark:border-emerald-800">
                      {client.status}
                    </span>
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Matching Loans */}
          {matchingLoans.length > 0 && (
            <div>
              <p className="px-3 py-1 text-[10px] font-bold uppercase tracking-wider text-slate-400 dark:text-slate-500">
                Loans
              </p>
              <div className="space-y-0.5">
                {matchingLoans.map((loan) => {
                  const client = clients.find((c) => c.id === loan.clientId);
                  return (
                    <button
                      key={loan.id}
                      onClick={() => {
                        onClose();
                        onNavigate('loans');
                      }}
                      className="w-full flex items-center justify-between px-3 py-2 rounded-xl text-left text-xs text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800/60 transition-colors"
                    >
                      <div className="flex items-center gap-2.5">
                        <div className="w-6 h-6 rounded-lg bg-amber-100 dark:bg-amber-900/40 text-amber-600 dark:text-amber-400 flex items-center justify-center">
                          <Coins className="w-3.5 h-3.5" />
                        </div>
                        <div>
                          <span className="font-mono font-bold text-blue-600 dark:text-blue-400">
                            {loan.loanNo}
                          </span>
                          <span className="text-slate-600 dark:text-slate-300 ml-2 font-medium">
                            {client ? `${client.firstName} ${client.lastName}` : ''}
                          </span>
                          <span className="text-[11px] text-slate-400 ml-2">
                            {formatMoney(loan.principal)}
                          </span>
                        </div>
                      </div>
                      <span className="text-[10px] font-semibold text-slate-500 dark:text-slate-400">
                        {loan.status}
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          {/* Navigation Links */}
          {matchingNav.length > 0 && (
            <div>
              <p className="px-3 py-1 text-[10px] font-bold uppercase tracking-wider text-slate-400 dark:text-slate-500">
                Navigation
              </p>
              <div className="space-y-0.5">
                {matchingNav.map((item) => {
                  const Icon = item.icon;
                  return (
                    <button
                      key={item.id}
                      onClick={() => {
                        onClose();
                        onNavigate(item.tab);
                      }}
                      className="w-full flex items-center justify-between px-3 py-2 rounded-xl text-left text-xs text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800/60 transition-colors"
                    >
                      <div className="flex items-center gap-2.5">
                        <Icon className="w-4 h-4 text-slate-400 dark:text-slate-500" />
                        <span>{item.label}</span>
                      </div>
                      <ArrowRight className="w-3.5 h-3.5 text-slate-400" />
                    </button>
                  );
                })}
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-4 py-2.5 bg-slate-50 dark:bg-slate-900 border-t border-slate-100 dark:border-slate-800 text-[11px] text-slate-500 dark:text-slate-400 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <span>
              <kbd className="font-mono bg-white dark:bg-slate-800 px-1 py-0.5 rounded border border-slate-200 dark:border-slate-700 text-[10px]">
                ↑↓
              </kbd>{' '}
              Navigate
            </span>
            <span>
              <kbd className="font-mono bg-white dark:bg-slate-800 px-1 py-0.5 rounded border border-slate-200 dark:border-slate-700 text-[10px]">
                ESC
              </kbd>{' '}
              Close
            </span>
          </div>
          <span className="font-mono text-[10px] text-blue-600 dark:text-blue-400">Microfinance Command Hub</span>
        </div>
      </div>
    </div>
  );
};
