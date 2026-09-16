import React from 'react';
import {
  LayoutDashboard,
  Users,
  Coins,
  RefreshCw,
  AlertOctagon,
  FileSpreadsheet,
  Scale,
  Receipt,
  Settings,
  Database,
  LogOut,
  Building2,
} from 'lucide-react';
import { useApp } from '../../context/AppContext';

export type ActiveTab =
  | 'dashboard'
  | 'clients'
  | 'loans'
  | 'rollovers'
  | 'bad_debts'
  | 'reports'
  | 'accounting'
  | 'payroll'
  | 'sqlite'
  | 'settings';

interface SidebarProps {
  activeTab: ActiveTab;
  setActiveTab: (tab: ActiveTab) => void;
  isOpenMobile?: boolean;
  onCloseMobile?: () => void;
}

export const Sidebar: React.FC<SidebarProps> = ({
  activeTab,
  setActiveTab,
  isOpenMobile = false,
  onCloseMobile,
}) => {
  const { currentUser, logout, systemDate, clients, loans } = useApp();

  const pendingApprovalsCount = loans.filter(
    (l) => l.status === 'Pending' && l.approvalStatus === 'Pending'
  ).length;

  const handleNavClick = (tab: ActiveTab) => {
    setActiveTab(tab);
    if (onCloseMobile) onCloseMobile();
  };

  const getInitials = (name: string) => {
    return name
      .split(' ')
      .map((n) => n[0])
      .slice(0, 2)
      .join('')
      .toUpperCase();
  };

  const navItemClass = (isActive: boolean) =>
    `w-full flex items-center gap-3 px-3 py-2 rounded-xl text-xs font-semibold transition-all text-left ${
      isActive
        ? 'bg-blue-600 text-white shadow-xs'
        : 'text-slate-300 hover:bg-slate-800/70 hover:text-white'
    }`;

  const sidebarContent = (
    <aside
      id="app-sidebar"
      className="w-64 bg-[#0B1329] border-r border-slate-800 flex flex-col h-full select-none shrink-0"
    >
      {/* Brand Header */}
      <div className="px-5 py-4 border-b border-slate-800/80 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-blue-600 flex items-center justify-center text-white shadow-sm">
            <Building2 className="w-5 h-5" />
          </div>
          <div>
            <h1 className="font-bold text-sm tracking-tight text-white leading-tight">
              Microfinance
            </h1>
            <span className="text-[10px] text-blue-400 font-mono">SQLite 3 • Pro</span>
          </div>
        </div>

        {onCloseMobile && (
          <button
            onClick={onCloseMobile}
            className="lg:hidden p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800"
          >
            ✕
          </button>
        )}
      </div>

      {/* User Card */}
      {currentUser && (
        <div className="p-3 mx-3 my-3 bg-[#111C38] border border-slate-800 rounded-xl flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-blue-600 text-white font-bold text-xs flex items-center justify-center shrink-0">
            {getInitials(currentUser.fullName)}
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-xs font-semibold text-white truncate">{currentUser.fullName}</p>
            <p className="text-[11px] text-slate-400 capitalize truncate">
              {currentUser.role.replace('_', ' ')}
            </p>
          </div>
        </div>
      )}

      {/* Navigation List */}
      <div className="flex-1 overflow-y-auto px-3 py-1 space-y-4">
        {/* OVERVIEW */}
        <div>
          <p className="px-3 text-[10px] font-bold uppercase tracking-wider text-slate-400 mb-1.5">
            Overview
          </p>
          <button
            id="nav-dashboard"
            onClick={() => handleNavClick('dashboard')}
            className={navItemClass(activeTab === 'dashboard')}
          >
            <LayoutDashboard className="w-4 h-4 text-blue-400" />
            <span className="flex-1">Dashboard</span>
            <kbd className="text-[10px] bg-slate-800/80 text-slate-400 px-1 rounded border border-slate-700">Alt+1</kbd>
          </button>
        </div>

        {/* OPERATIONS */}
        <div>
          <p className="px-3 text-[10px] font-bold uppercase tracking-wider text-slate-400 mb-1.5">
            Operations
          </p>
          <div className="space-y-1">
            <button
              id="nav-clients"
              onClick={() => handleNavClick('clients')}
              className={navItemClass(activeTab === 'clients')}
            >
              <Users className="w-4 h-4 text-emerald-400" />
              <span className="flex-1">Clients</span>
              <span className="text-[10px] bg-emerald-950/60 text-emerald-300 font-mono px-1.5 py-0.5 rounded-full border border-emerald-800/80">
                {clients.length}
              </span>
            </button>

            <button
              id="nav-loans"
              onClick={() => handleNavClick('loans')}
              className={navItemClass(activeTab === 'loans')}
            >
              <Coins className="w-4 h-4 text-amber-400" />
              <span className="flex-1">Loans &amp; Workflows</span>
              {pendingApprovalsCount > 0 ? (
                <span className="text-[10px] bg-amber-500 text-slate-950 font-bold px-1.5 py-0.2 rounded-full">
                  {pendingApprovalsCount}
                </span>
              ) : (
                <kbd className="text-[10px] bg-slate-800/80 text-slate-400 px-1 rounded border border-slate-700">Alt+3</kbd>
              )}
            </button>

            <button
              id="nav-rollovers"
              onClick={() => handleNavClick('rollovers')}
              className={navItemClass(activeTab === 'rollovers')}
            >
              <RefreshCw className="w-4 h-4 text-indigo-400" />
              <span className="flex-1">Rollovers</span>
              <kbd className="text-[10px] bg-slate-800/80 text-slate-400 px-1 rounded border border-slate-700">Alt+4</kbd>
            </button>

            <button
              id="nav-bad-debts"
              onClick={() => handleNavClick('bad_debts')}
              className={navItemClass(activeTab === 'bad_debts')}
            >
              <AlertOctagon className="w-4 h-4 text-rose-400" />
              <span className="flex-1">Bad Debts</span>
              <kbd className="text-[10px] bg-slate-800/80 text-slate-400 px-1 rounded border border-slate-700">Alt+5</kbd>
            </button>
          </div>
        </div>

        {/* FINANCE */}
        <div>
          <p className="px-3 text-[10px] font-bold uppercase tracking-wider text-slate-400 mb-1.5">
            Finance
          </p>
          <div className="space-y-1">
            <button
              id="nav-reports"
              onClick={() => handleNavClick('reports')}
              className={navItemClass(activeTab === 'reports')}
            >
              <FileSpreadsheet className="w-4 h-4 text-teal-400" />
              <span className="flex-1">Reports &amp; PAR</span>
              <kbd className="text-[10px] bg-slate-800/80 text-slate-400 px-1 rounded border border-slate-700">Alt+6</kbd>
            </button>

            <button
              id="nav-accounting"
              onClick={() => handleNavClick('accounting')}
              className={navItemClass(activeTab === 'accounting')}
            >
              <Scale className="w-4 h-4 text-sky-400" />
              <span className="flex-1">Accounting &amp; Ledger</span>
              <kbd className="text-[10px] bg-slate-800/80 text-slate-400 px-1 rounded border border-slate-700">Alt+7</kbd>
            </button>

            <button
              id="nav-payroll"
              onClick={() => handleNavClick('payroll')}
              className={navItemClass(activeTab === 'payroll')}
            >
              <Receipt className="w-4 h-4 text-violet-400" />
              <span className="flex-1">Payroll &amp; Statutory</span>
              <kbd className="text-[10px] bg-slate-800/80 text-slate-400 px-1 rounded border border-slate-700">Alt+8</kbd>
            </button>
          </div>
        </div>

        {/* ADMINISTRATION */}
        <div>
          <p className="px-3 text-[10px] font-bold uppercase tracking-wider text-slate-400 mb-1.5">
            Administration
          </p>
          <div className="space-y-1">
            <button
              id="nav-sqlite"
              onClick={() => handleNavClick('sqlite')}
              className={navItemClass(activeTab === 'sqlite')}
            >
              <Database className="w-4 h-4 text-cyan-400" />
              <span className="flex-1">SQLite Database</span>
              <span className="w-2 h-2 rounded-full bg-emerald-400" />
            </button>

            <button
              id="nav-settings"
              onClick={() => handleNavClick('settings')}
              className={navItemClass(activeTab === 'settings')}
            >
              <Settings className="w-4 h-4 text-slate-400" />
              <span className="flex-1">Settings &amp; Backups</span>
              <kbd className="text-[10px] bg-slate-800/80 text-slate-400 px-1 rounded border border-slate-700">Alt+9</kbd>
            </button>
          </div>
        </div>
      </div>

      {/* Footer info & Logout */}
      <div className="p-3 border-t border-slate-800 bg-[#070D1D] space-y-2">
        <div className="flex items-center justify-between text-[11px] text-slate-400 px-1">
          <span>Date:</span>
          <span className="font-mono text-slate-200">{systemDate}</span>
        </div>
        <button
          id="btn-logout"
          onClick={logout}
          className="w-full flex items-center justify-center gap-2 px-3 py-2 text-xs font-semibold text-rose-400 hover:bg-rose-950/40 hover:text-rose-300 rounded-lg transition-colors border border-rose-900/40"
        >
          <LogOut className="w-3.5 h-3.5" />
          Log Out
        </button>
      </div>
    </aside>
  );

  return (
    <>
      {/* Desktop Sidebar */}
      <div className="hidden lg:block h-screen">{sidebarContent}</div>

      {/* Mobile Drawer */}
      {isOpenMobile && (
        <div className="lg:hidden fixed inset-0 z-50 flex">
          <div
            className="fixed inset-0 bg-slate-900/60 backdrop-blur-xs transition-opacity"
            onClick={onCloseMobile}
          />
          <div className="relative flex-1 flex flex-col max-w-xs w-full bg-[#0B1329] z-10 animate-in slide-in-from-left duration-200">
            {sidebarContent}
          </div>
        </div>
      )}
    </>
  );
};
