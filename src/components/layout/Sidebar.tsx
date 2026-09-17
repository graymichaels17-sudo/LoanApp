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
  const {
    currentUser,
    logout,
    systemDate,
    clients,
    loans,
    cloudSyncStatus,
    lastCloudSync,
    refreshFromCloud,
    isTursoActive,
  } = useApp();

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
        : 'text-slate-600 hover:text-slate-900 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800/70 dark:hover:text-white'
    }`;

  const sidebarContent = (
    <aside
      id="app-sidebar"
      className="w-64 bg-white dark:bg-[#0B1329] border-r border-slate-200/90 dark:border-slate-800 flex flex-col h-full select-none shrink-0 transition-colors"
    >
      {/* Brand Header */}
      <div className="px-5 py-4 border-b border-slate-200/80 dark:border-slate-800/80 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-blue-600 flex items-center justify-center text-white shadow-xs">
            <Building2 className="w-5 h-5" />
          </div>
          <div>
            <h1 className="font-bold text-sm tracking-tight text-slate-900 dark:text-white leading-tight">
              Microfinance
            </h1>
            <span className="text-[10px] text-blue-600 dark:text-blue-400 font-mono font-medium">SQLite 3 • Pro</span>
          </div>
        </div>

        {onCloseMobile && (
          <button
            onClick={onCloseMobile}
            className="lg:hidden p-1.5 rounded-lg text-slate-400 hover:text-slate-700 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
          >
            ✕
          </button>
        )}
      </div>

      {/* User Card */}
      {currentUser && (
        <div className="p-3 mx-3 my-3 bg-slate-50/80 dark:bg-[#111C38] border border-slate-200/80 dark:border-slate-800 rounded-xl flex items-center gap-3 shadow-2xs">
          <div className="w-8 h-8 rounded-lg bg-blue-600 text-white font-bold text-xs flex items-center justify-center shrink-0 shadow-xs">
            {getInitials(currentUser.fullName)}
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-xs font-semibold text-slate-900 dark:text-white truncate">{currentUser.fullName}</p>
            <p className="text-[11px] text-slate-500 dark:text-slate-400 capitalize truncate">
              {currentUser.role.replace('_', ' ')}
            </p>
          </div>
        </div>
      )}

      {/* Navigation List */}
      <div className="flex-1 overflow-y-auto px-3 py-1 space-y-4">
        {/* OVERVIEW */}
        <div>
          <p className="px-3 text-[10px] font-bold uppercase tracking-wider text-slate-400 dark:text-slate-500 mb-1.5">
            Overview
          </p>
          <button
            id="nav-dashboard"
            onClick={() => handleNavClick('dashboard')}
            className={navItemClass(activeTab === 'dashboard')}
          >
            <LayoutDashboard className="w-4 h-4 text-blue-500 dark:text-blue-400" />
            <span className="flex-1">Dashboard</span>
            <kbd className="text-[10px] bg-slate-100 dark:bg-slate-800/80 text-slate-500 dark:text-slate-400 px-1 rounded border border-slate-200 dark:border-slate-700">Alt+1</kbd>
          </button>
        </div>

        {/* OPERATIONS */}
        <div>
          <p className="px-3 text-[10px] font-bold uppercase tracking-wider text-slate-400 dark:text-slate-500 mb-1.5">
            Operations
          </p>
          <div className="space-y-1">
            <button
              id="nav-clients"
              onClick={() => handleNavClick('clients')}
              className={navItemClass(activeTab === 'clients')}
            >
              <Users className="w-4 h-4 text-emerald-500 dark:text-emerald-400" />
              <span className="flex-1">Clients</span>
              <span className="text-[10px] bg-emerald-50 dark:bg-emerald-950/60 text-emerald-700 dark:text-emerald-300 font-mono px-1.5 py-0.5 rounded-full border border-emerald-200 dark:border-emerald-800/80 font-semibold">
                {clients.length}
              </span>
            </button>

            <button
              id="nav-loans"
              onClick={() => handleNavClick('loans')}
              className={navItemClass(activeTab === 'loans')}
            >
              <Coins className="w-4 h-4 text-amber-500 dark:text-amber-400" />
              <span className="flex-1">Loans &amp; Workflows</span>
              {pendingApprovalsCount > 0 ? (
                <span className="text-[10px] bg-amber-500 text-slate-950 font-bold px-1.5 py-0.2 rounded-full">
                  {pendingApprovalsCount}
                </span>
              ) : (
                <kbd className="text-[10px] bg-slate-100 dark:bg-slate-800/80 text-slate-500 dark:text-slate-400 px-1 rounded border border-slate-200 dark:border-slate-700">Alt+3</kbd>
              )}
            </button>

            <button
              id="nav-rollovers"
              onClick={() => handleNavClick('rollovers')}
              className={navItemClass(activeTab === 'rollovers')}
            >
              <RefreshCw className="w-4 h-4 text-indigo-500 dark:text-indigo-400" />
              <span className="flex-1">Rollovers</span>
              <kbd className="text-[10px] bg-slate-100 dark:bg-slate-800/80 text-slate-500 dark:text-slate-400 px-1 rounded border border-slate-200 dark:border-slate-700">Alt+4</kbd>
            </button>

            <button
              id="nav-bad-debts"
              onClick={() => handleNavClick('bad_debts')}
              className={navItemClass(activeTab === 'bad_debts')}
            >
              <AlertOctagon className="w-4 h-4 text-rose-500 dark:text-rose-400" />
              <span className="flex-1">Bad Debts</span>
              <kbd className="text-[10px] bg-slate-100 dark:bg-slate-800/80 text-slate-500 dark:text-slate-400 px-1 rounded border border-slate-200 dark:border-slate-700">Alt+5</kbd>
            </button>
          </div>
        </div>

        {/* FINANCE */}
        <div>
          <p className="px-3 text-[10px] font-bold uppercase tracking-wider text-slate-400 dark:text-slate-500 mb-1.5">
            Finance
          </p>
          <div className="space-y-1">
            <button
              id="nav-reports"
              onClick={() => handleNavClick('reports')}
              className={navItemClass(activeTab === 'reports')}
            >
              <FileSpreadsheet className="w-4 h-4 text-teal-500 dark:text-teal-400" />
              <span className="flex-1">Reports &amp; PAR</span>
              <kbd className="text-[10px] bg-slate-100 dark:bg-slate-800/80 text-slate-500 dark:text-slate-400 px-1 rounded border border-slate-200 dark:border-slate-700">Alt+6</kbd>
            </button>

            <button
              id="nav-accounting"
              onClick={() => handleNavClick('accounting')}
              className={navItemClass(activeTab === 'accounting')}
            >
              <Scale className="w-4 h-4 text-sky-500 dark:text-sky-400" />
              <span className="flex-1">Accounting &amp; Ledger</span>
              <kbd className="text-[10px] bg-slate-100 dark:bg-slate-800/80 text-slate-500 dark:text-slate-400 px-1 rounded border border-slate-200 dark:border-slate-700">Alt+7</kbd>
            </button>

            <button
              id="nav-payroll"
              onClick={() => handleNavClick('payroll')}
              className={navItemClass(activeTab === 'payroll')}
            >
              <Receipt className="w-4 h-4 text-violet-500 dark:text-violet-400" />
              <span className="flex-1">Payroll &amp; Statutory</span>
              <kbd className="text-[10px] bg-slate-100 dark:bg-slate-800/80 text-slate-500 dark:text-slate-400 px-1 rounded border border-slate-200 dark:border-slate-700">Alt+8</kbd>
            </button>
          </div>
        </div>

        {/* ADMINISTRATION */}
        <div>
          <p className="px-3 text-[10px] font-bold uppercase tracking-wider text-slate-400 dark:text-slate-500 mb-1.5">
            Administration
          </p>
          <div className="space-y-1">
            <button
              id="nav-sqlite"
              onClick={() => handleNavClick('sqlite')}
              className={navItemClass(activeTab === 'sqlite')}
            >
              <Database className="w-4 h-4 text-cyan-500 dark:text-cyan-400" />
              <span className="flex-1">SQLite Database</span>
              <span className="w-2 h-2 rounded-full bg-emerald-500" />
            </button>

            <button
              id="nav-settings"
              onClick={() => handleNavClick('settings')}
              className={navItemClass(activeTab === 'settings')}
            >
              <Settings className="w-4 h-4 text-slate-500 dark:text-slate-400" />
              <span className="flex-1">Settings &amp; Backups</span>
              <kbd className="text-[10px] bg-slate-100 dark:bg-slate-800/80 text-slate-500 dark:text-slate-400 px-1 rounded border border-slate-200 dark:border-slate-700">Alt+9</kbd>
            </button>
          </div>
        </div>
      </div>

      {/* Multi-User Cloud Sync & Online Status */}
      <div className="mx-3 my-2 p-2.5 rounded-xl bg-slate-50/90 dark:bg-[#091024] border border-slate-200/80 dark:border-slate-800/80 space-y-1.5 shadow-2xs">
        <div className="flex items-center justify-between">
          <span className="flex items-center gap-1.5 text-[11px] font-semibold text-slate-700 dark:text-slate-200">
            <span
              className={`w-2 h-2 rounded-full ${
                isTursoActive
                  ? 'bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.5)] animate-pulse'
                  : 'bg-blue-500'
              }`}
            />
            {isTursoActive ? 'Turso Cloud Online' : 'Local SQLite'}
          </span>
          <button
            onClick={() => refreshFromCloud()}
            title="Refresh latest data from cloud"
            className="text-slate-400 hover:text-slate-700 dark:hover:text-white p-1 rounded hover:bg-slate-200/70 dark:hover:bg-slate-800 transition-colors"
          >
            <RefreshCw
              className={`w-3 h-3 ${cloudSyncStatus === 'syncing' ? 'animate-spin text-blue-500' : ''}`}
            />
          </button>
        </div>
        <div className="flex items-center justify-between text-[10px] text-slate-500 dark:text-slate-400 pt-0.5 border-t border-slate-200/80 dark:border-slate-800/60">
          <span>Multi-User Sync</span>
          <span className="font-mono text-emerald-600 dark:text-emerald-400 font-medium">
            {cloudSyncStatus === 'syncing' ? 'Syncing...' : lastCloudSync ? `Synced ${lastCloudSync}` : 'Ready'}
          </span>
        </div>
      </div>

      {/* Footer info & Logout */}
      <div className="p-3 border-t border-slate-200/80 dark:border-slate-800 bg-slate-50/60 dark:bg-[#070D1D] space-y-2">
        <div className="flex items-center justify-between text-[11px] text-slate-500 dark:text-slate-400 px-1">
          <span>Date:</span>
          <span className="font-mono text-slate-700 dark:text-slate-200 font-medium">{systemDate}</span>
        </div>
        <button
          id="btn-logout"
          onClick={logout}
          className="w-full flex items-center justify-center gap-2 px-3 py-2 text-xs font-semibold text-rose-600 dark:text-rose-400 hover:bg-rose-50 dark:hover:bg-rose-950/40 hover:text-rose-700 dark:hover:text-rose-300 rounded-lg transition-colors border border-rose-200 dark:border-rose-900/40"
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
          <div className="relative flex-1 flex flex-col max-w-xs w-full bg-white dark:bg-[#0B1329] z-10 animate-in slide-in-from-left duration-200">
            {sidebarContent}
          </div>
        </div>
      )}
    </>
  );
};
