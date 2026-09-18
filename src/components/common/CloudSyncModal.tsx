import React, { useState, useEffect } from 'react';
import {
  Cloud,
  AlertTriangle,
  Copy,
  ExternalLink,
  RefreshCw,
  Database,
  Smartphone,
  Laptop,
  Check,
} from 'lucide-react';
import { useApp } from '../../context/AppContext';
import { Modal } from './Modal';

interface CloudSyncModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export const CloudSyncModal: React.FC<CloudSyncModalProps> = ({ isOpen, onClose }) => {
  const { cloudSyncStatus, lastCloudSync, isTursoActive, refreshFromCloud } = useApp();
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [copiedKey, setCopiedKey] = useState<string | null>(null);
  const [tursoInfo, setTursoInfo] = useState<{
    configured: boolean;
    maskedUrl?: string;
    activeUrl?: string | null;
    vercelSetupNeeded: boolean;
  } | null>(null);

  useEffect(() => {
    if (isOpen) {
      fetch('/api/db/turso-info')
        .then((r) => r.json())
        .then((data) => setTursoInfo(data))
        .catch(() => setTursoInfo(null));
    }
  }, [isOpen]);

  const handleRefresh = async () => {
    setIsRefreshing(true);
    await refreshFromCloud();
    try {
      const res = await fetch('/api/db/turso-info');
      const data = await res.json();
      setTursoInfo(data);
    } catch {}
    setIsRefreshing(false);
  };

  const copyToClipboard = (text: string, keyName: string) => {
    navigator.clipboard.writeText(text);
    setCopiedKey(keyName);
    setTimeout(() => setCopiedKey(null), 2500);
  };

  const exampleTursoUrl = tursoInfo?.activeUrl || 'libsql://loanapp-grayt.aws-ap-northeast-1.turso.io';

  return (
    <Modal isOpen={isOpen} onClose={onClose} title="Multi-Device Cloud Synchronization" maxWidth="2xl">
      <div className="space-y-6 text-xs text-slate-700 dark:text-slate-300">
        {/* Status Card */}
        <div
          className={`p-4 rounded-xl border flex items-start gap-3.5 transition-colors ${
            isTursoActive
              ? 'bg-emerald-50 dark:bg-emerald-950/30 border-emerald-200 dark:border-emerald-800/60'
              : 'bg-amber-50 dark:bg-amber-950/30 border-amber-200 dark:border-amber-800/60'
          }`}
        >
          <div
            className={`w-9 h-9 rounded-xl flex items-center justify-center shrink-0 ${
              isTursoActive
                ? 'bg-emerald-600 text-white'
                : 'bg-amber-500 text-white'
            }`}
          >
            {isTursoActive ? <Cloud className="w-5 h-5" /> : <AlertTriangle className="w-5 h-5" />}
          </div>

          <div className="flex-1 min-w-0">
            <div className="flex items-center justify-between gap-2">
              <h4 className="font-bold text-sm text-slate-900 dark:text-white">
                {isTursoActive
                  ? 'Turso Cloud Active - Multi-Device Sync Enabled'
                  : 'Local Storage Only - Multi-Device Sync Disabled'}
              </h4>
              <span
                className={`px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider ${
                  isTursoActive
                    ? 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/60 dark:text-emerald-300'
                    : 'bg-amber-100 text-amber-800 dark:bg-amber-900/60 dark:text-amber-300'
                }`}
              >
                {cloudSyncStatus}
              </span>
            </div>

            <p className="mt-1 text-slate-600 dark:text-slate-300 leading-relaxed">
              {isTursoActive
                ? 'All clients, loans, repayments, and accounting records automatically synchronize in real time across every device, phone, and tablet connected to your central Turso Cloud database.'
                : 'Your Vercel deployment is currently operating in offline/local browser mode. Data entered on one device stays only on that browser and will not appear on other devices.'}
            </p>

            <div className="mt-2.5 flex items-center gap-4 text-[11px] text-slate-500 dark:text-slate-400">
              <span className="flex items-center gap-1.5 font-mono">
                <Database className="w-3 h-3 text-slate-400" />
                {tursoInfo?.maskedUrl || 'Local SQLite'}
              </span>
              {lastCloudSync && <span>Last Synced: {lastCloudSync}</span>}
            </div>
          </div>
        </div>

        {/* Why Vercel doesn't show the same data across devices */}
        <div className="bg-slate-50 dark:bg-slate-900/60 border border-slate-200 dark:border-slate-800 rounded-xl p-4 space-y-3">
          <div className="flex items-center gap-2 font-bold text-slate-900 dark:text-white text-xs">
            <Smartphone className="w-4 h-4 text-blue-500" />
            <span>Why did Vercel show different data on another device?</span>
            <Laptop className="w-4 h-4 text-indigo-500" />
          </div>
          <p className="text-slate-600 dark:text-slate-400 leading-relaxed text-[11px]">
            Vercel is a serverless hosting platform. Each serverless function runs in an isolated, temporary container.
            To share data across multiple phones, laptops, and operators, Vercel must be connected to your centralized{' '}
            <strong className="text-slate-900 dark:text-slate-200">Turso Cloud LibSQL database</strong>. When the Vercel
            project does not have your Turso credentials set in its Environment Variables, each device falls back to its
            own separate local browser storage.
          </p>
        </div>

        {/* 3-Step Vercel Setup Guide */}
        <div className="space-y-3">
          <h5 className="font-bold text-xs uppercase tracking-wider text-slate-900 dark:text-white">
            How to Enable Multi-Device Sync on Vercel (3 Steps):
          </h5>

          <div className="space-y-2.5">
            {/* Step 1 */}
            <div className="p-3 bg-white dark:bg-[#111C38] border border-slate-200 dark:border-[#1E2D5A] rounded-xl flex items-start gap-3">
              <span className="w-5 h-5 rounded-full bg-blue-100 dark:bg-blue-900/50 text-blue-600 dark:text-blue-400 flex items-center justify-center font-bold text-[10px] shrink-0 mt-0.5">
                1
              </span>
              <div className="flex-1">
                <p className="font-semibold text-slate-900 dark:text-white">
                  Open your Vercel Project Settings
                </p>
                <p className="text-slate-500 dark:text-slate-400 text-[11px] mt-0.5">
                  Go to{' '}
                  <a
                    href="https://vercel.com/dashboard"
                    target="_blank"
                    rel="noreferrer"
                    className="text-blue-500 hover:underline inline-flex items-center gap-0.5 font-medium"
                  >
                    Vercel Dashboard <ExternalLink className="w-3 h-3" />
                  </a>{' '}
                  &rarr; Select your Project &rarr; Click <strong className="text-slate-700 dark:text-slate-200">Settings</strong> &rarr; Click{' '}
                  <strong className="text-slate-700 dark:text-slate-200">Environment Variables</strong>.
                </p>
              </div>
            </div>

            {/* Step 2 */}
            <div className="p-3 bg-white dark:bg-[#111C38] border border-slate-200 dark:border-[#1E2D5A] rounded-xl flex items-start gap-3">
              <span className="w-5 h-5 rounded-full bg-blue-100 dark:bg-blue-900/50 text-blue-600 dark:text-blue-400 flex items-center justify-center font-bold text-[10px] shrink-0 mt-0.5">
                2
              </span>
              <div className="flex-1 space-y-2">
                <p className="font-semibold text-slate-900 dark:text-white">
                  Add the two Turso Cloud environment variables:
                </p>

                {/* Variable 1 */}
                <div className="flex items-center justify-between gap-2 p-2 bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-lg">
                  <div className="font-mono text-[11px]">
                    <span className="text-blue-600 dark:text-blue-400 font-bold">TURSO_DATABASE_URL</span>
                    <span className="text-slate-400 mx-1">=</span>
                    <span className="text-slate-600 dark:text-slate-300">{exampleTursoUrl}</span>
                  </div>
                  <button
                    onClick={() => copyToClipboard(exampleTursoUrl, 'url')}
                    className="px-2 py-1 bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded text-[10px] font-semibold text-slate-700 dark:text-slate-300 hover:bg-slate-100 flex items-center gap-1 transition-colors"
                  >
                    {copiedKey === 'url' ? <Check className="w-3 h-3 text-emerald-500" /> : <Copy className="w-3 h-3" />}
                    {copiedKey === 'url' ? 'Copied' : 'Copy'}
                  </button>
                </div>

                {/* Variable 2 */}
                <div className="flex items-center justify-between gap-2 p-2 bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-lg">
                  <div className="font-mono text-[11px]">
                    <span className="text-blue-600 dark:text-blue-400 font-bold">TURSO_AUTH_TOKEN</span>
                    <span className="text-slate-400 mx-1">=</span>
                    <span className="text-slate-500 dark:text-slate-400">
                      (Your Turso JWT auth token from your Turso dashboard)
                    </span>
                  </div>
                  <button
                    onClick={() => copyToClipboard('TURSO_AUTH_TOKEN', 'token')}
                    className="px-2 py-1 bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded text-[10px] font-semibold text-slate-700 dark:text-slate-300 hover:bg-slate-100 flex items-center gap-1 transition-colors"
                  >
                    {copiedKey === 'token' ? <Check className="w-3 h-3 text-emerald-500" /> : <Copy className="w-3 h-3" />}
                    {copiedKey === 'token' ? 'Copied Name' : 'Copy Name'}
                  </button>
                </div>
              </div>
            </div>

            {/* Step 3 */}
            <div className="p-3 bg-white dark:bg-[#111C38] border border-slate-200 dark:border-[#1E2D5A] rounded-xl flex items-start gap-3">
              <span className="w-5 h-5 rounded-full bg-blue-100 dark:bg-blue-900/50 text-blue-600 dark:text-blue-400 flex items-center justify-center font-bold text-[10px] shrink-0 mt-0.5">
                3
              </span>
              <div className="flex-1">
                <p className="font-semibold text-slate-900 dark:text-white">
                  Redeploy on Vercel
                </p>
                <p className="text-slate-500 dark:text-slate-400 text-[11px] mt-0.5">
                  Go to <strong className="text-slate-700 dark:text-slate-200">Deployments</strong> &rarr; Click the 3 dots on your latest deployment &rarr; Click <strong className="text-slate-700 dark:text-slate-200">Redeploy</strong>. Once redeployed, any device opening the app will automatically read and write to the same live database!
                </p>
              </div>
            </div>
          </div>
        </div>

        {/* Actions Footer */}
        <div className="pt-2 border-t border-slate-200 dark:border-slate-800 flex items-center justify-between">
          <button
            onClick={handleRefresh}
            disabled={isRefreshing}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-slate-300 dark:border-slate-700 text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 font-semibold transition-colors disabled:opacity-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isRefreshing ? 'animate-spin' : ''}`} />
            <span>{isRefreshing ? 'Testing Connection...' : 'Test & Sync Now'}</span>
          </button>

          <button
            onClick={onClose}
            className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg font-semibold transition-colors"
          >
            Done
          </button>
        </div>
      </div>
    </Modal>
  );
};
