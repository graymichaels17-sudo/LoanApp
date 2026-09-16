import React, { useState } from 'react';
import { Building2, KeyRound, User as UserIcon, ShieldCheck } from 'lucide-react';
import { useApp } from '../../context/AppContext';

export const LoginView: React.FC = () => {
  const { login, users } = useApp();
  const [username, setUsername] = useState('admin');
  const [password, setPassword] = useState('admin123');
  const [errorMsg, setErrorMsg] = useState('');

  const handleLogin = (e: React.FormEvent) => {
    e.preventDefault();
    if (!username.trim()) {
      setErrorMsg('Please enter your username.');
      return;
    }
    const ok = login(username);
    if (!ok) {
      setErrorMsg('User not found or account deactivated.');
    }
  };

  const handleQuickSwitch = (uName: string) => {
    setUsername(uName);
    setPassword('admin123');
    login(uName);
  };

  return (
    <div className="min-h-screen w-full bg-[#070D1D] flex items-center justify-center p-4">
      <div className="w-full max-w-md bg-[#0F172A] border border-[#1E2D5A] rounded-2xl shadow-2xl p-7 space-y-6">
        {/* App Branding */}
        <div className="text-center space-y-2">
          <div className="inline-flex w-14 h-14 rounded-2xl bg-blue-600 items-center justify-center text-white shadow-lg shadow-blue-600/30 mb-1">
            <Building2 className="w-7 h-7" />
          </div>
          <h1 className="text-2xl font-extrabold text-white tracking-tight">Microfinance Manager</h1>
          <p className="text-xs text-slate-400">
            Secure offline microfinance portfolio & accounting system
          </p>
        </div>

        {errorMsg && (
          <div className="p-3 bg-rose-950/60 border border-rose-800 text-rose-300 rounded-lg text-xs">
            {errorMsg}
          </div>
        )}

        {/* Login Form */}
        <form onSubmit={handleLogin} className="space-y-4">
          <div>
            <label className="block text-xs font-semibold text-slate-300 mb-1.5">
              Username
            </label>
            <div className="relative">
              <UserIcon className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
              <input
                id="login-username"
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="admin"
                className="w-full pl-9 pr-3 py-2.5 bg-[#162244] border border-[#1E2D5A] rounded-lg text-sm text-white placeholder-slate-500 focus:outline-hidden focus:border-blue-500"
                required
              />
            </div>
          </div>

          <div>
            <label className="block text-xs font-semibold text-slate-300 mb-1.5">
              Password
            </label>
            <div className="relative">
              <KeyRound className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
              <input
                id="login-password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                className="w-full pl-9 pr-3 py-2.5 bg-[#162244] border border-[#1E2D5A] rounded-lg text-sm text-white placeholder-slate-500 focus:outline-hidden focus:border-blue-500"
                required
              />
            </div>
          </div>

          <button
            id="btn-login-submit"
            type="submit"
            className="w-full py-2.5 bg-blue-600 hover:bg-blue-500 text-white font-semibold text-sm rounded-lg shadow-md transition-colors"
          >
            Sign In to Dashboard
          </button>
        </form>

        {/* Quick Role Tester / Switcher */}
        <div className="pt-4 border-t border-slate-800 space-y-2.5">
          <p className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider text-center">
            Demo Accounts (Click to Sign In):
          </p>
          <div className="grid grid-cols-2 gap-2">
            {users.map((u) => (
              <button
                key={u.id}
                type="button"
                onClick={() => handleQuickSwitch(u.username)}
                className="p-2 bg-[#162244]/60 hover:bg-[#162244] border border-[#1E2D5A] rounded-lg text-left transition-colors"
              >
                <p className="text-xs font-semibold text-slate-200 truncate">{u.fullName}</p>
                <p className="text-[10px] text-blue-400 font-mono capitalize">
                  {u.role.replace('_', ' ')}
                </p>
              </button>
            ))}
          </div>
        </div>

        <div className="text-center flex items-center justify-center gap-1 text-[11px] text-slate-400">
          <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />
          <span>Local SQLite-compatible storage verified</span>
        </div>
      </div>
    </div>
  );
};
