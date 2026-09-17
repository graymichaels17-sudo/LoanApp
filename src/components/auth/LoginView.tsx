import React, { useState } from 'react';
import { motion } from 'motion/react';
import {
  Building2,
  KeyRound,
  User as UserIcon,
  ShieldCheck,
  Eye,
  EyeOff,
  ArrowRight,
  Lock,
  CheckCircle2,
  Sun,
  Moon,
} from 'lucide-react';
import { useApp } from '../../context/AppContext';
import { useTheme } from '../../context/ThemeContext';

export const LoginView: React.FC = () => {
  const { login, users } = useApp();
  const { theme, setTheme } = useTheme();
  const [username, setUsername] = useState('admin');
  const [password, setPassword] = useState('admin123');
  const [showPassword, setShowPassword] = useState(false);
  const [errorMsg, setErrorMsg] = useState('');
  const [isLoading, setIsLoading] = useState(false);

  const handleLogin = (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMsg('');
    if (!username.trim()) {
      setErrorMsg('Please enter your credentials to continue.');
      return;
    }
    setIsLoading(true);
    setTimeout(() => {
      const ok = login(username);
      if (!ok) {
        setErrorMsg('Authentication failed: Account not recognized or deactivated.');
        setIsLoading(false);
      }
    }, 200);
  };

  const handleQuickSwitch = (uName: string) => {
    setUsername(uName);
    setPassword('admin123');
    setErrorMsg('');
    login(uName);
  };

  const roleColors: Record<string, { bg: string; text: string; label: string }> = {
    admin: {
      bg: 'bg-indigo-50 dark:bg-indigo-500/10 text-indigo-700 dark:text-indigo-400 border-indigo-200 dark:border-indigo-500/20',
      text: 'Administrator',
      label: 'Full System Access',
    },
    manager: {
      bg: 'bg-blue-50 dark:bg-blue-500/10 text-blue-700 dark:text-blue-400 border-blue-200 dark:border-blue-500/20',
      text: 'Branch Manager',
      label: 'Approvals & Reports',
    },
    loan_officer: {
      bg: 'bg-emerald-50 dark:bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border-emerald-200 dark:border-emerald-500/20',
      text: 'Loan Officer',
      label: 'Underwriting & Clients',
    },
    teller: {
      bg: 'bg-amber-50 dark:bg-amber-500/10 text-amber-700 dark:text-amber-400 border-amber-200 dark:border-amber-500/20',
      text: 'Cashier / Teller',
      label: 'Disbursements & Repayments',
    },
  };

  return (
    <div className="relative min-h-screen w-full bg-slate-50 dark:bg-[#070D1D] text-slate-800 dark:text-slate-100 flex items-center justify-center p-4 sm:p-6 overflow-hidden select-none transition-colors duration-200">
      {/* Ambient background glows */}
      <div className="absolute top-1/4 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[600px] bg-blue-600/10 dark:bg-blue-600/10 rounded-full blur-[120px] pointer-events-none" />
      <div className="absolute bottom-10 right-10 w-[400px] h-[400px] bg-indigo-600/10 dark:bg-indigo-600/10 rounded-full blur-[100px] pointer-events-none" />

      {/* Top right theme switcher */}
      <div className="absolute top-5 right-5 z-20">
        <div
          className="flex items-center p-0.5 rounded-xl bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 shadow-xs"
          role="group"
          aria-label="Color theme switcher"
        >
          <button
            onClick={() => setTheme('light')}
            className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-semibold transition-all ${
              theme === 'light'
                ? 'bg-slate-100 text-slate-900 shadow-2xs font-bold'
                : 'text-slate-500 hover:text-slate-800 dark:text-slate-400'
            }`}
            title="Light Theme"
          >
            <Sun className={`w-3.5 h-3.5 ${theme === 'light' ? 'text-amber-500 fill-amber-500/20' : 'text-slate-400'}`} />
            <span>Light</span>
          </button>
          <button
            onClick={() => setTheme('dark')}
            className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-semibold transition-all ${
              theme === 'dark'
                ? 'bg-slate-800 text-white shadow-2xs font-bold'
                : 'text-slate-500 hover:text-slate-800 dark:text-slate-400'
            }`}
            title="Dark Theme"
          >
            <Moon className={`w-3.5 h-3.5 ${theme === 'dark' ? 'text-blue-400 fill-blue-400/20' : 'text-slate-400'}`} />
            <span>Dark</span>
          </button>
        </div>
      </div>

      <motion.div
        initial={{ opacity: 0, y: 16, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ duration: 0.28, ease: 'easeOut' }}
        className="relative z-10 w-full max-w-lg bg-white/90 dark:bg-[#0E172E]/90 border border-slate-200/90 dark:border-slate-800 shadow-xl dark:shadow-2xl dark:shadow-black/60 rounded-3xl p-7 sm:p-9 backdrop-blur-xl space-y-7 transition-colors"
      >
        {/* Institutional Branding Header */}
        <div className="text-center space-y-3">
          <div className="inline-flex items-center justify-center p-3 rounded-2xl bg-gradient-to-br from-blue-500 to-blue-700 text-white shadow-lg shadow-blue-500/25 ring-4 ring-blue-500/10">
            <Building2 className="w-8 h-8" />
          </div>
          <div>
            <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-blue-50 dark:bg-blue-950/60 border border-blue-200 dark:border-blue-800/60 text-blue-700 dark:text-blue-300 text-xs font-semibold mb-2">
              <ShieldCheck className="w-3.5 h-3.5 text-blue-600 dark:text-blue-400" />
              Core Banking &amp; Microfinance Suite
            </div>
            <h1 className="text-2xl sm:text-3xl font-bold tracking-tight text-slate-900 dark:text-white">
              Microfinance Manager
            </h1>
            <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">
              Institutional portfolio ledger, credit underwriting &amp; double-entry accounting
            </p>
          </div>
        </div>

        {errorMsg && (
          <motion.div
            initial={{ opacity: 0, y: -6 }}
            animate={{ opacity: 1, y: 0 }}
            className="p-3.5 bg-rose-50 dark:bg-rose-950/80 border border-rose-200 dark:border-rose-800/80 text-rose-800 dark:text-rose-200 rounded-xl text-xs sm:text-sm font-medium flex items-center gap-2"
          >
            <Lock className="w-4 h-4 text-rose-600 dark:text-rose-400 shrink-0" />
            <span>{errorMsg}</span>
          </motion.div>
        )}

        {/* Login Form */}
        <form onSubmit={handleLogin} className="space-y-4">
          <div>
            <label className="block text-xs sm:text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5">
              Account Username
            </label>
            <div className="relative">
              <UserIcon className="w-5 h-5 text-slate-400 absolute left-3.5 top-1/2 -translate-y-1/2" />
              <input
                id="login-username"
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="Enter operator username..."
                className="w-full pl-11 pr-4 py-3 bg-slate-50 dark:bg-[#131F3F] border border-slate-200 dark:border-slate-700/80 rounded-xl text-sm sm:text-base text-slate-900 dark:text-white placeholder-slate-400 dark:placeholder-slate-500 focus:outline-hidden focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all font-medium focus:bg-white dark:focus:bg-[#131F3F]"
                required
              />
            </div>
          </div>

          <div>
            <div className="flex items-center justify-between mb-1.5">
              <label className="text-xs sm:text-sm font-semibold text-slate-700 dark:text-slate-300">
                Security Password
              </label>
              <span className="text-xs text-slate-400">Default: admin123</span>
            </div>
            <div className="relative">
              <KeyRound className="w-5 h-5 text-slate-400 absolute left-3.5 top-1/2 -translate-y-1/2" />
              <input
                id="login-password"
                type={showPassword ? 'text' : 'password'}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                className="w-full pl-11 pr-11 py-3 bg-slate-50 dark:bg-[#131F3F] border border-slate-200 dark:border-slate-700/80 rounded-xl text-sm sm:text-base text-slate-900 dark:text-white placeholder-slate-400 dark:placeholder-slate-500 focus:outline-hidden focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all font-medium focus:bg-white dark:focus:bg-[#131F3F]"
                required
              />
              <button
                type="button"
                onClick={() => setShowPassword((p) => !p)}
                className="absolute right-3.5 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 transition-colors p-1"
              >
                {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
            </div>
          </div>

          <button
            id="btn-login-submit"
            type="submit"
            disabled={isLoading}
            className="w-full py-3.5 bg-blue-600 hover:bg-blue-500 active:bg-blue-700 text-white font-semibold text-sm sm:text-base rounded-xl shadow-lg shadow-blue-600/30 transition-all flex items-center justify-center gap-2 group cursor-pointer"
          >
            {isLoading ? (
              <span>Authenticating Session...</span>
            ) : (
              <>
                <span>Sign In to Financial Workspace</span>
                <ArrowRight className="w-4 h-4 group-hover:translate-x-1 transition-transform" />
              </>
            )}
          </button>
        </form>

        {/* Quick Role Switcher for Development & Demonstration */}
        <div className="pt-5 border-t border-slate-100 dark:border-slate-800/80 space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold uppercase tracking-wider text-slate-400">
              Quick Operator Access
            </span>
            <span className="text-xs text-slate-400">1-click login</span>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
            {users.map((u) => {
              const meta = roleColors[u.role] || {
                bg: 'bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 border-slate-200 dark:border-slate-700',
                text: u.role,
                label: 'General Access',
              };
              const isCurrent = username === u.username;

              return (
                <button
                  key={u.id}
                  type="button"
                  onClick={() => handleQuickSwitch(u.username)}
                  className={`p-3 rounded-xl border text-left transition-all flex items-center justify-between group cursor-pointer ${
                    isCurrent
                      ? 'bg-blue-50 dark:bg-blue-900/30 border-blue-500/60 shadow-2xs ring-1 ring-blue-500/30'
                      : 'bg-slate-50/80 dark:bg-[#131F3F]/60 hover:bg-slate-100 dark:hover:bg-[#131F3F] border-slate-200 dark:border-slate-800 hover:border-slate-300 dark:hover:border-slate-700'
                  }`}
                >
                  <div className="min-w-0 pr-2">
                    <p className="text-sm font-semibold text-slate-900 dark:text-white truncate group-hover:text-blue-600 dark:group-hover:text-blue-300 transition-colors">
                      {u.fullName}
                    </p>
                    <p className="text-xs text-slate-500 dark:text-slate-400 truncate mt-0.5">{meta.label}</p>
                  </div>
                  <span className={`text-xs px-2 py-0.5 rounded-md font-medium shrink-0 border ${meta.bg}`}>
                    {meta.text.split(' ')[0]}
                  </span>
                </button>
              );
            })}
          </div>
        </div>

        {/* Institutional Trust Footer */}
        <div className="pt-2 flex flex-col sm:flex-row items-center justify-between gap-2 text-xs text-slate-500 dark:text-slate-400 border-t border-slate-100 dark:border-slate-800/60">
          <div className="flex items-center gap-1.5">
            <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500 dark:text-emerald-400 shrink-0" />
            <span>SQLite3 Compatible &amp; Turso Replicated</span>
          </div>
          <span className="font-mono text-slate-400">v2.4.0 • Zero Data Mode</span>
        </div>
      </motion.div>
    </div>
  );
};
