import React, { useState, useEffect } from 'react';
import { useApp } from './context/AppContext';
import { Sidebar, ActiveTab } from './components/layout/Sidebar';
import { Topbar } from './components/layout/Topbar';
import { CommandPalette } from './components/common/CommandPalette';
import { QuickRepaymentModal } from './components/loans/QuickRepaymentModal';
import { ShortcutsModal } from './components/common/ShortcutsModal';
import { LoginView } from './components/auth/LoginView';
import { DashboardView } from './components/dashboard/DashboardView';
import { ClientsView } from './components/clients/ClientsView';
import { LoansView } from './components/loans/LoansView';
import { RolloversView } from './components/rollovers/RolloversView';
import { BadDebtsView } from './components/badDebts/BadDebtsView';
import { ReportsView } from './components/reports/ReportsView';
import { AccountingView } from './components/accounting/AccountingView';
import { PayrollView } from './components/payroll/PayrollView';
import { SqliteView } from './components/sqlite/SqliteView';
import { SettingsView } from './components/settings/SettingsView';

export const App: React.FC = () => {
  const { currentUser } = useApp();
  const [activeTab, setActiveTab] = useState<ActiveTab>('dashboard');
  const [isCommandPaletteOpen, setIsCommandPaletteOpen] = useState(false);
  const [isQuickRepaymentOpen, setIsQuickRepaymentOpen] = useState(false);
  const [isShortcutsOpen, setIsShortcutsOpen] = useState(false);
  const [isMobileSidebarOpen, setIsMobileSidebarOpen] = useState(false);

  // Global keyboard shortcuts (Ctrl+K, Alt+1-0, ?)
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Command palette trigger: Ctrl+K or Cmd+K
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setIsCommandPaletteOpen((prev) => !prev);
        return;
      }

      // Help shortcuts trigger: '?' key when not typing in form inputs
      const target = e.target as HTMLElement;
      const isInput =
        target.tagName === 'INPUT' ||
        target.tagName === 'TEXTAREA' ||
        target.tagName === 'SELECT' ||
        target.isContentEditable;

      if (!isInput && e.key === '?' && !e.ctrlKey && !e.altKey && !e.metaKey) {
        e.preventDefault();
        setIsShortcutsOpen(true);
        return;
      }

      // Navigation accelerators: Alt+1 to Alt+9, Alt+0
      if (e.altKey) {
        const tabMap: Record<string, ActiveTab> = {
          '1': 'dashboard',
          '2': 'clients',
          '3': 'loans',
          '4': 'rollovers',
          '5': 'bad_debts',
          '6': 'reports',
          '7': 'accounting',
          '8': 'payroll',
          '9': 'settings',
          '0': 'sqlite',
        };

        if (tabMap[e.key]) {
          e.preventDefault();
          setActiveTab(tabMap[e.key]);
        }
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  if (!currentUser) {
    return <LoginView />;
  }

  return (
    <div id="app-root" className="flex h-screen bg-slate-50 dark:bg-[#070D1D] text-slate-800 dark:text-slate-100 overflow-hidden font-sans transition-colors duration-200">
      {/* Sidebar for Navigation with Responsive Drawer */}
      <Sidebar
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        isOpenMobile={isMobileSidebarOpen}
        onCloseMobile={() => setIsMobileSidebarOpen(false)}
      />

      {/* Main Content Area */}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        {/* Global Topbar Header with Search, Shortcuts & Quick Actions */}
        <Topbar
          onOpenCommandPalette={() => setIsCommandPaletteOpen(true)}
          onOpenQuickRepayment={() => setIsQuickRepaymentOpen(true)}
          onOpenNewClient={() => setActiveTab('clients')}
          onOpenNewLoan={() => setActiveTab('loans')}
          onOpenShortcuts={() => setIsShortcutsOpen(true)}
          onToggleMobileSidebar={() => setIsMobileSidebarOpen((prev) => !prev)}
          onNavigate={setActiveTab}
        />

        {/* Scrollable View Container */}
        <main id="main-content" className="flex-1 overflow-y-auto p-4 sm:p-6 lg:p-8">
          <div className="max-w-7xl mx-auto pb-12">
            {activeTab === 'dashboard' && <DashboardView onNavigate={setActiveTab} />}
            {activeTab === 'clients' && <ClientsView />}
            {activeTab === 'loans' && <LoansView />}
            {activeTab === 'rollovers' && <RolloversView />}
            {activeTab === 'bad_debts' && <BadDebtsView />}
            {activeTab === 'reports' && <ReportsView />}
            {activeTab === 'accounting' && <AccountingView />}
            {activeTab === 'payroll' && <PayrollView />}
            {activeTab === 'sqlite' && <SqliteView />}
            {activeTab === 'settings' && <SettingsView />}
          </div>
        </main>
      </div>

      {/* Global Interactive Modals */}
      <CommandPalette
        isOpen={isCommandPaletteOpen}
        onClose={() => setIsCommandPaletteOpen(false)}
        onNavigate={(tab) => {
          setActiveTab(tab);
          setIsCommandPaletteOpen(false);
        }}
        onOpenQuickRepayment={() => {
          setIsCommandPaletteOpen(false);
          setIsQuickRepaymentOpen(true);
        }}
        onOpenNewClient={() => {
          setIsCommandPaletteOpen(false);
          setActiveTab('clients');
        }}
        onOpenNewLoan={() => {
          setIsCommandPaletteOpen(false);
          setActiveTab('loans');
        }}
      />

      <QuickRepaymentModal
        isOpen={isQuickRepaymentOpen}
        onClose={() => setIsQuickRepaymentOpen(false)}
      />

      <ShortcutsModal
        isOpen={isShortcutsOpen}
        onClose={() => setIsShortcutsOpen(false)}
      />
    </div>
  );
};

export default App;
