import React, { useState, useRef, useEffect } from 'react';
import {
  Search,
  Plus,
  Coins,
  UserPlus,
  ArrowDownLeft,
  Database,
  Calendar,
  Sun,
  Moon,
  HelpCircle,
  Menu,
  LogOut,
  Building,
  ChevronDown,
} from 'lucide-react';
import { useApp } from '../../context/AppContext';
import { useTheme } from '../../context/ThemeContext';
import { ActiveTab } from './Sidebar';

interface TopbarProps {
  onOpenCommandPalette: () => void;
  onOpenQuickRepayment: () => void;
  onOpenNewClient: () => void;
  onOpenNewLoan: () => void;
  onOpenShortcuts: () => void;
  onToggleMobileSidebar: () => void;
  onNavigate: (tab: ActiveTab) => void;
}

export const Topbar: React.FC<TopbarProps> = ({
  onOpenCommandPalette,
  onOpenQuickRepayment,
  onOpenNewClient,
  onOpenNewLoan,
  onOpenShortcuts,
  onToggleMobileSidebar,
  onNavigate,
}) => {
  const { currentUser, logout, systemDate } = useApp();
  const { theme, toggleTheme } = useTheme();

  const [isActionsDropdownOpen, setIsActionsDropdownOpen] = useState(false);
  const [isUserMenuOpen, setIsUserMenuOpen] = useState(false);

  const actionsRef = useRef<HTMLDivElement>(null);
  const userRef = useRef<HTMLDivElement>(null);

  // Close dropdowns on outside click
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (actionsRef.current && !actionsRef.current.contains(e.target as Node)) {
        setIsActionsDropdownOpen(false);
      }
      if (userRef.current && !userRef.current.contains(e.target as Node)) {
        setIsUserMenuOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  return (
    <header
      id="app-topbar"
      className="sticky top-0 z-30 h-16 bg-white/95 dark:bg-[#0B1329]/95 backdrop-blur-md border-b border-slate-200/80 dark:border-slate-800/80 px-4 sm:px-6 flex items-center justify-between gap-4 transition-colors"
    >
      {/* Left: Mobile hamburger & Global Search Trigger */}
      <div className="flex items-center gap-3 flex-1 max-w-xl">
        <button
          onClick={onToggleMobileSidebar}
          className="lg:hidden p-2 rounded-xl text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
          title="Toggle Navigation Menu"
        >
          <Menu className="w-5 h-5" />
        </button>

        {/* Global Search Button */}
        <button
          onClick={onOpenCommandPalette}
          className="w-full max-w-md flex items-center justify-between px-3.5 py-2 rounded-xl bg-slate-100/80 dark:bg-slate-900 border border-slate-200/80 dark:border-slate-800 text-xs text-slate-500 dark:text-slate-400 hover:border-blue-400/50 hover:bg-white dark:hover:bg-slate-800/60 shadow-2xs transition-all group"
        >
          <div className="flex items-center gap-2.5">
            <Search className="w-4 h-4 text-slate-400 group-hover:text-blue-500 transition-colors" />
            <span className="hidden sm:inline">Search clients, loans, accounts, or type command...</span>
            <span className="sm:hidden">Search...</span>
          </div>
          <kbd className="hidden sm:inline-block font-mono text-[10px] font-semibold bg-white dark:bg-slate-800 text-slate-500 dark:text-slate-400 px-1.5 py-0.5 rounded border border-slate-200 dark:border-slate-700 shadow-2xs">
            Ctrl+K
          </kbd>
        </button>
      </div>

      {/* Right: Telemetry, Quick Actions, Theme, User */}
      <div className="flex items-center gap-2 sm:gap-2.5">
        {/* SQLite Database Status Pill */}
        <button
          onClick={() => onNavigate('sqlite')}
          className="hidden md:flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-emerald-50 dark:bg-emerald-950/40 border border-emerald-200/80 dark:border-emerald-800/60 text-emerald-700 dark:text-emerald-300 text-xs font-semibold hover:bg-emerald-100 dark:hover:bg-emerald-900/40 transition-colors"
          title="SQLite Database is connected and active. Click to view SQLite Studio."
        >
          <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
          <Database className="w-3.5 h-3.5 text-emerald-600 dark:text-emerald-400" />
          <span>SQLite 3 Online</span>
        </button>

        {/* System Date Pill */}
        <div className="hidden xl:flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-slate-100 dark:bg-slate-800/80 border border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-300 text-xs font-mono">
          <Calendar className="w-3.5 h-3.5 text-slate-400" />
          <span>{systemDate || '2026-09-16'}</span>
        </div>

        {/* Quick Action Dropdown */}
        <div className="relative" ref={actionsRef}>
          <button
            onClick={() => setIsActionsDropdownOpen(!isActionsDropdownOpen)}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-blue-600 hover:bg-blue-500 text-white rounded-xl text-xs font-semibold shadow-xs transition-colors"
          >
            <Plus className="w-4 h-4" />
            <span className="hidden sm:inline">Quick Action</span>
            <ChevronDown className="w-3.5 h-3.5 opacity-80" />
          </button>

          {isActionsDropdownOpen && (
            <div className="absolute right-0 mt-2 w-52 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl shadow-xl p-1.5 z-50 text-xs animate-in fade-in zoom-in-95">
              <button
                onClick={() => {
                  setIsActionsDropdownOpen(false);
                  onOpenQuickRepayment();
                }}
                className="w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-left text-slate-700 dark:text-slate-200 hover:bg-blue-50 dark:hover:bg-blue-950/40 hover:text-blue-600 dark:hover:text-blue-400 transition-colors font-medium"
              >
                <div className="w-6 h-6 rounded-md bg-emerald-100 dark:bg-emerald-900/40 text-emerald-600 dark:text-emerald-400 flex items-center justify-center">
                  <ArrowDownLeft className="w-3.5 h-3.5" />
                </div>
                <span>Record Repayment</span>
              </button>

              <button
                onClick={() => {
                  setIsActionsDropdownOpen(false);
                  onOpenNewLoan();
                }}
                className="w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-left text-slate-700 dark:text-slate-200 hover:bg-blue-50 dark:hover:bg-blue-950/40 hover:text-blue-600 dark:hover:text-blue-400 transition-colors font-medium"
              >
                <div className="w-6 h-6 rounded-md bg-blue-100 dark:bg-blue-900/40 text-blue-600 dark:text-blue-400 flex items-center justify-center">
                  <Coins className="w-3.5 h-3.5" />
                </div>
                <span>New Loan Application</span>
              </button>

              <button
                onClick={() => {
                  setIsActionsDropdownOpen(false);
                  onOpenNewClient();
                }}
                className="w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-left text-slate-700 dark:text-slate-200 hover:bg-blue-50 dark:hover:bg-blue-950/40 hover:text-blue-600 dark:hover:text-blue-400 transition-colors font-medium"
              >
                <div className="w-6 h-6 rounded-md bg-indigo-100 dark:bg-indigo-900/40 text-indigo-600 dark:text-indigo-400 flex items-center justify-center">
                  <UserPlus className="w-3.5 h-3.5" />
                </div>
                <span>Register New Client</span>
              </button>

              <div className="my-1 border-t border-slate-100 dark:border-slate-800" />

              <button
                onClick={() => {
                  setIsActionsDropdownOpen(false);
                  onNavigate('sqlite');
                }}
                className="w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-left text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors font-medium"
              >
                <div className="w-6 h-6 rounded-md bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 flex items-center justify-center">
                  <Database className="w-3.5 h-3.5" />
                </div>
                <span>Open SQLite Console</span>
              </button>
            </div>
          )}
        </div>

        {/* Shortcuts Helper Button */}
        <button
          onClick={onOpenShortcuts}
          className="p-2 rounded-xl text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
          title="Keyboard Shortcuts (?)"
        >
          <HelpCircle className="w-4 h-4" />
        </button>

        {/* Theme Switcher Toggle */}
        <button
          onClick={toggleTheme}
          className="p-2 rounded-xl text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
          title={theme === 'dark' ? 'Switch to Clean Light Theme' : 'Switch to Dark Theme'}
        >
          {theme === 'dark' ? (
            <Sun className="w-4 h-4 text-amber-400" />
          ) : (
            <Moon className="w-4 h-4 text-slate-600" />
          )}
        </button>

        {/* User Menu */}
        {currentUser && (
          <div className="relative ml-1" ref={userRef}>
            <button
              onClick={() => setIsUserMenuOpen(!isUserMenuOpen)}
              className="flex items-center gap-2 p-1.5 rounded-xl hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
            >
              <div className="w-8 h-8 rounded-full bg-blue-600 text-white font-bold text-xs flex items-center justify-center shadow-xs">
                {currentUser.fullName
                  .split(' ')
                  .map((n) => n[0])
                  .slice(0, 2)
                  .join('')
                  .toUpperCase()}
              </div>
              <div className="hidden md:block text-left text-xs leading-tight pr-1">
                <p className="font-bold text-slate-800 dark:text-white truncate max-w-[120px]">
                  {currentUser.fullName}
                </p>
                <p className="text-[10px] text-slate-400 capitalize">
                  {currentUser.role.replace('_', ' ')}
                </p>
              </div>
              <ChevronDown className="w-3.5 h-3.5 text-slate-400 hidden md:block" />
            </button>

            {isUserMenuOpen && (
              <div className="absolute right-0 mt-2 w-48 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl shadow-xl p-1.5 z-50 text-xs animate-in fade-in zoom-in-95">
                <div className="px-3 py-2 border-b border-slate-100 dark:border-slate-800 mb-1">
                  <p className="font-bold text-slate-800 dark:text-white truncate">{currentUser.fullName}</p>
                  <p className="text-[10px] text-slate-400 capitalize font-mono">
                    {currentUser.role.replace('_', ' ')}
                  </p>
                </div>

                <button
                  onClick={() => {
                    setIsUserMenuOpen(false);
                    onNavigate('settings');
                  }}
                  className="w-full flex items-center gap-2 px-3 py-1.5 rounded-lg text-left text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
                >
                  <Building className="w-3.5 h-3.5 text-slate-400" />
                  <span>Company Settings</span>
                </button>

                <button
                  onClick={() => {
                    setIsUserMenuOpen(false);
                    logout();
                  }}
                  className="w-full flex items-center gap-2 px-3 py-1.5 rounded-lg text-left text-rose-600 dark:text-rose-400 hover:bg-rose-50 dark:hover:bg-rose-950/40 transition-colors font-medium"
                >
                  <LogOut className="w-3.5 h-3.5" />
                  <span>Sign Out</span>
                </button>
              </div>
            )}
          </div>
        )}
      </div>
    </header>
  );
};
