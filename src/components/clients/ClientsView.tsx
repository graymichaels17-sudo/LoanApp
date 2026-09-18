import React, { useState } from 'react';
import {
  Users,
  Search,
  UserPlus,
  Phone,
  MapPin,
  Briefcase,
  DollarSign,
  Coins,
  ArrowRight,
  Edit2,
  Upload,
  Download,
} from 'lucide-react';
import { useApp } from '../../context/AppContext';
import { Client } from '../../types';
import { formatMoney } from '../../utils/money';
import { Header } from '../common/Header';
import { StatusBadge } from '../common/Badge';
import { Modal } from '../common/Modal';
import { DataImportExportModal } from '../common/DataImportExportModal';

interface ClientsViewProps {
  onApplyLoanForClient?: (clientId: number) => void;
  defaultOpenNew?: boolean;
}

export const ClientsView: React.FC<ClientsViewProps> = ({
  onApplyLoanForClient,
  defaultOpenNew = false,
}) => {
  const { clients, loans, locations, addClient, updateClient } = useApp();

  const [searchTerm, setSearchTerm] = useState('');
  const [locationFilter, setLocationFilter] = useState('All');
  const [statusFilter, setStatusFilter] = useState('All');

  const [selectedClient, setSelectedClient] = useState<Client | null>(null);
  const [isNewModalOpen, setIsNewModalOpen] = useState(defaultOpenNew);
  const [isEditModalOpen, setIsEditModalOpen] = useState(false);
  const [isImportExportModalOpen, setIsImportExportModalOpen] = useState(false);
  const [importExportTab, setImportExportTab] = useState<'export' | 'import'>('export');

  // New Client Form State
  const [formData, setFormData] = useState({
    firstName: '',
    lastName: '',
    nationalId: '',
    gender: 'Male' as Client['gender'],
    location: locations[0] || 'Harare Central',
    phone: '',
    address: '',
    occupation: '',
    averageIncome: '',
    guarantor: '',
    guarantorPhone: '',
    notes: '',
    status: 'Active' as Client['status'],
  });

  const resetForm = () => {
    setFormData({
      firstName: '',
      lastName: '',
      nationalId: '',
      gender: 'Male',
      location: locations[0] || 'Harare Central',
      phone: '',
      address: '',
      occupation: '',
      averageIncome: '',
      guarantor: '',
      guarantorPhone: '',
      notes: '',
      status: 'Active',
    });
  };

  const handleCreateClient = (e: React.FormEvent) => {
    e.preventDefault();
    if (!formData.firstName.trim() || !formData.lastName.trim() || !formData.nationalId.trim()) {
      alert('Please provide first name, last name, and national ID.');
      return;
    }

    const newClient = addClient({
      firstName: formData.firstName.trim(),
      lastName: formData.lastName.trim(),
      nationalId: formData.nationalId.trim(),
      gender: formData.gender,
      location: formData.location,
      phone: formData.phone.trim(),
      address: formData.address.trim(),
      occupation: formData.occupation.trim(),
      averageIncome: parseFloat(formData.averageIncome) || 0,
      guarantor: formData.guarantor.trim(),
      guarantorPhone: formData.guarantorPhone.trim(),
      dateRegistered: '2026-09-16',
      status: formData.status,
      notes: formData.notes.trim(),
    });

    setIsNewModalOpen(false);
    resetForm();
    setSelectedClient(newClient);
  };

  const handleUpdateClient = (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedClient) return;

    updateClient(selectedClient.id, {
      firstName: formData.firstName.trim(),
      lastName: formData.lastName.trim(),
      nationalId: formData.nationalId.trim(),
      gender: formData.gender,
      location: formData.location,
      phone: formData.phone.trim(),
      address: formData.address.trim(),
      occupation: formData.occupation.trim(),
      averageIncome: parseFloat(formData.averageIncome) || 0,
      guarantor: formData.guarantor.trim(),
      guarantorPhone: formData.guarantorPhone.trim(),
      notes: formData.notes.trim(),
      status: formData.status,
    });

    setSelectedClient({
      ...selectedClient,
      firstName: formData.firstName.trim(),
      lastName: formData.lastName.trim(),
      nationalId: formData.nationalId.trim(),
      gender: formData.gender,
      location: formData.location,
      phone: formData.phone.trim(),
      address: formData.address.trim(),
      occupation: formData.occupation.trim(),
      averageIncome: parseFloat(formData.averageIncome) || 0,
      guarantor: formData.guarantor.trim(),
      guarantorPhone: formData.guarantorPhone.trim(),
      notes: formData.notes.trim(),
      status: formData.status,
    });

    setIsEditModalOpen(false);
  };

  const openEdit = (client: Client) => {
    setSelectedClient(client);
    setFormData({
      firstName: client.firstName,
      lastName: client.lastName,
      nationalId: client.nationalId,
      gender: client.gender,
      location: client.location,
      phone: client.phone,
      address: client.address || '',
      occupation: client.occupation || '',
      averageIncome: client.averageIncome ? client.averageIncome.toString() : '',
      guarantor: client.guarantor || '',
      guarantorPhone: client.guarantorPhone || '',
      notes: client.notes || '',
      status: client.status,
    });
    setIsEditModalOpen(true);
  };

  // Filter clients
  const filteredClients = clients.filter((c) => {
    const q = searchTerm.toLowerCase();
    const matchesSearch =
      !searchTerm ||
      c.clientNo.toLowerCase().includes(q) ||
      c.firstName.toLowerCase().includes(q) ||
      c.lastName.toLowerCase().includes(q) ||
      c.nationalId.toLowerCase().includes(q) ||
      c.phone.toLowerCase().includes(q);

    const matchesLocation = locationFilter === 'All' || c.location === locationFilter;
    const matchesStatus = statusFilter === 'All' || c.status === statusFilter;

    return matchesSearch && matchesLocation && matchesStatus;
  });

  const clientLoans = selectedClient
    ? loans.filter((l) => l.clientId === selectedClient.id)
    : [];

  return (
    <div id="clients-view" className="space-y-6">
      <Header
        title="Client Registry"
        subtitle="Manage borrowers, personal identification, KYC documentation, and credit histories"
        actions={
          <div className="flex items-center gap-2">
            <button
              onClick={() => {
                setImportExportTab('import');
                setIsImportExportModalOpen(true);
              }}
              className="flex items-center gap-1.5 px-3 py-2 bg-slate-100 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 text-slate-700 dark:text-slate-200 rounded-lg text-xs font-semibold hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors shadow-2xs"
              title="Import clients from Excel spreadsheet"
            >
              <Upload className="w-4 h-4 text-blue-500" />
              <span>Import Excel</span>
            </button>

            <button
              onClick={() => {
                setImportExportTab('export');
                setIsImportExportModalOpen(true);
              }}
              className="flex items-center gap-1.5 px-3 py-2 bg-slate-100 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 text-slate-700 dark:text-slate-200 rounded-lg text-xs font-semibold hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors shadow-2xs"
              title="Export clients to Excel or PDF"
            >
              <Download className="w-4 h-4 text-emerald-500" />
              <span>Export</span>
            </button>

            <button
              id="btn-register-client"
              onClick={() => {
                resetForm();
                setIsNewModalOpen(true);
              }}
              className="flex items-center gap-1.5 px-3.5 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-xs font-semibold shadow-xs transition-colors"
            >
              <UserPlus className="w-4 h-4" />
              Register New Client
            </button>
          </div>
        }
      />

      {/* Filters & Search */}
      <div className="flex flex-col sm:flex-row gap-3 items-center justify-between">
        <div className="relative w-full sm:w-80">
          <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            placeholder="Search by name, client #, ID, or phone..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="w-full pl-9 pr-3 py-2 bg-white dark:bg-[#111C38] border border-slate-200/80 dark:border-[#1E2D5A] rounded-xl text-xs text-slate-900 dark:text-white placeholder-slate-400 focus:outline-hidden focus:border-blue-500 shadow-2xs"
          />
        </div>

        <div className="flex items-center gap-2 w-full sm:w-auto">
          <select
            value={locationFilter}
            onChange={(e) => setLocationFilter(e.target.value)}
            className="px-3 py-2 bg-white dark:bg-[#111C38] border border-slate-200/80 dark:border-[#1E2D5A] rounded-xl text-xs text-slate-700 dark:text-slate-200 focus:outline-hidden focus:border-blue-500 shadow-2xs"
          >
            <option value="All">All Locations</option>
            {locations.map((loc) => (
              <option key={loc} value={loc}>
                {loc}
              </option>
            ))}
          </select>

          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="px-3 py-2 bg-white dark:bg-[#111C38] border border-slate-200/80 dark:border-[#1E2D5A] rounded-xl text-xs text-slate-700 dark:text-slate-200 focus:outline-hidden focus:border-blue-500 shadow-2xs"
          >
            <option value="All">All Statuses</option>
            <option value="Active">Active</option>
            <option value="Inactive">Inactive</option>
            <option value="Blacklisted">Blacklisted</option>
          </select>
        </div>
      </div>

      {/* Main Table and Details Split */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Clients Table (2 columns on lg) */}
        <div className="lg:col-span-2 bg-white dark:bg-[#111C38] border border-slate-200/80 dark:border-[#1E2D5A] rounded-2xl overflow-hidden flex flex-col shadow-2xs">
          <div className="px-4 py-3 border-b border-slate-100 dark:border-[#1E2D5A] flex items-center justify-between bg-slate-50/50 dark:bg-transparent">
            <span className="text-xs font-bold text-slate-700 dark:text-slate-300">
              {filteredClients.length} Registered Client(s)
            </span>
            <span className="text-[11px] text-slate-500 dark:text-slate-400">Click a client to view credit file</span>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-slate-50 dark:bg-[#0B1329] text-slate-500 dark:text-slate-400 uppercase text-[10px] tracking-wider border-b border-slate-100 dark:border-[#1E2D5A]">
                <tr>
                  <th className="px-4 py-3">Client #</th>
                  <th className="px-4 py-3">Name</th>
                  <th className="px-4 py-3">National ID</th>
                  <th className="px-4 py-3">Location</th>
                  <th className="px-4 py-3">Phone</th>
                  <th className="px-4 py-3">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-[#1E2D5A]">
                {filteredClients.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="px-4 py-8 text-center text-slate-400 text-xs">
                      No clients found matching your search.
                    </td>
                  </tr>
                ) : (
                  filteredClients.map((c) => {
                    const isSelected = selectedClient?.id === c.id;
                    return (
                      <tr
                        key={c.id}
                        onClick={() => setSelectedClient(c)}
                        className={`cursor-pointer transition-colors ${
                          isSelected
                            ? 'bg-blue-50 dark:bg-blue-900/30 text-blue-900 dark:text-white font-medium'
                            : 'hover:bg-slate-50 dark:hover:bg-slate-800/40 text-slate-700 dark:text-slate-300'
                        }`}
                      >
                        <td className="px-4 py-3 font-mono font-semibold text-blue-600 dark:text-blue-400">
                          {c.clientNo}
                        </td>
                        <td className="px-4 py-3 font-semibold text-slate-900 dark:text-white">
                          {c.firstName} {c.lastName}
                        </td>
                        <td className="px-4 py-3 font-mono text-[11px] text-slate-500 dark:text-slate-300">
                          {c.nationalId}
                        </td>
                        <td className="px-4 py-3 text-slate-500 dark:text-slate-400">{c.location}</td>
                        <td className="px-4 py-3 font-mono text-slate-600 dark:text-slate-300">{c.phone}</td>
                        <td className="px-4 py-3">
                          <StatusBadge status={c.status} />
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </div>

        {/* Client Profile / Details Card */}
        <div className="bg-white dark:bg-[#111C38] border border-slate-200/80 dark:border-[#1E2D5A] rounded-2xl p-5 flex flex-col justify-between space-y-4 shadow-2xs">
          {selectedClient ? (
            <div className="space-y-4">
              <div className="flex items-start justify-between border-b border-slate-100 dark:border-[#1E2D5A] pb-4">
                <div>
                  <div className="flex items-center gap-2">
                    <h3 className="text-base font-bold text-slate-900 dark:text-white">
                      {selectedClient.firstName} {selectedClient.lastName}
                    </h3>
                    <StatusBadge status={selectedClient.status} />
                  </div>
                  <p className="text-xs font-mono text-blue-600 dark:text-blue-400 mt-0.5">
                    {selectedClient.clientNo} • Reg: {selectedClient.dateRegistered}
                  </p>
                </div>
                <button
                  onClick={() => openEdit(selectedClient)}
                  className="p-1.5 rounded-lg bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-600 dark:text-slate-300 transition-colors"
                  title="Edit Client"
                >
                  <Edit2 className="w-4 h-4" />
                </button>
              </div>

              {/* Demographics & KYC Details */}
              <div className="space-y-2.5 text-xs">
                <div className="flex items-center gap-2 text-slate-600 dark:text-slate-300">
                  <MapPin className="w-4 h-4 text-slate-400 shrink-0" />
                  <span>
                    {selectedClient.location} - {selectedClient.address || 'No physical address'}
                  </span>
                </div>
                <div className="flex items-center gap-2 text-slate-600 dark:text-slate-300">
                  <Phone className="w-4 h-4 text-slate-400 shrink-0" />
                  <span className="font-mono">{selectedClient.phone}</span>
                </div>
                <div className="flex items-center gap-2 text-slate-600 dark:text-slate-300">
                  <Briefcase className="w-4 h-4 text-slate-400 shrink-0" />
                  <span>{selectedClient.occupation || 'Self Employed'}</span>
                </div>
                <div className="flex items-center gap-2 text-slate-600 dark:text-slate-300">
                  <DollarSign className="w-4 h-4 text-emerald-500 shrink-0" />
                  <span>Monthly Income: {formatMoney(selectedClient.averageIncome)}</span>
                </div>
                {selectedClient.guarantor && (
                  <div className="p-2.5 bg-slate-50 dark:bg-[#0B1329] border border-slate-100 dark:border-[#1E2D5A] rounded-xl space-y-1">
                    <p className="text-[11px] font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                      Guarantor / Surety
                    </p>
                    <p className="text-xs font-semibold text-slate-800 dark:text-white">{selectedClient.guarantor}</p>
                    {selectedClient.guarantorPhone && (
                      <p className="text-[11px] font-mono text-slate-500 dark:text-slate-400">
                        {selectedClient.guarantorPhone}
                      </p>
                    )}
                  </div>
                )}
                {selectedClient.notes && (
                  <div className="p-2.5 bg-slate-50 dark:bg-[#0B1329] border border-slate-100 dark:border-[#1E2D5A] rounded-xl">
                    <p className="text-[11px] font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider mb-1">
                      Notes
                    </p>
                    <p className="text-xs text-slate-600 dark:text-slate-300">{selectedClient.notes}</p>
                  </div>
                )}
              </div>

              {/* Loans History for this client */}
              <div className="border-t border-slate-100 dark:border-[#1E2D5A] pt-4 space-y-2">
                <div className="flex items-center justify-between">
                  <h4 className="text-xs font-bold text-slate-900 dark:text-white flex items-center gap-1.5">
                    <Coins className="w-3.5 h-3.5 text-amber-500" />
                    Loan History ({clientLoans.length})
                  </h4>
                  {onApplyLoanForClient && (
                    <button
                      onClick={() => onApplyLoanForClient(selectedClient.id)}
                      className="text-[11px] font-semibold text-blue-600 dark:text-blue-400 hover:underline flex items-center gap-1"
                    >
                      New Loan
                      <ArrowRight className="w-3 h-3" />
                    </button>
                  )}
                </div>

                {clientLoans.length === 0 ? (
                  <p className="text-xs text-slate-400 italic py-2">No loans applied yet.</p>
                ) : (
                  <div className="space-y-1.5 max-h-48 overflow-y-auto">
                    {clientLoans.map((l) => (
                      <div
                        key={l.id}
                        className="p-2 bg-slate-50 dark:bg-[#0B1329] border border-slate-100 dark:border-[#1E2D5A] rounded-xl flex items-center justify-between text-xs"
                      >
                        <div>
                          <p className="font-mono font-semibold text-blue-600 dark:text-blue-400">{l.loanNo}</p>
                          <p className="text-[11px] text-slate-500 dark:text-slate-400">
                            {formatMoney(l.principal)} • {l.termMonths} {l.repaymentFrequency}
                          </p>
                        </div>
                        <StatusBadge status={l.status} />
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center py-16 text-center text-slate-400 dark:text-slate-500 space-y-2">
              <Users className="w-10 h-10 text-slate-300 dark:text-slate-600" />
              <p className="text-xs">Select a client from the registry to view their profile.</p>
            </div>
          )}
        </div>
      </div>

      {/* Register Client Modal */}
      <Modal
        isOpen={isNewModalOpen}
        onClose={() => setIsNewModalOpen(false)}
        title="Register New Client"
        maxWidth="xl"
      >
        <form onSubmit={handleCreateClient} className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1">
                First Name *
              </label>
              <input
                type="text"
                required
                value={formData.firstName}
                onChange={(e) => setFormData({ ...formData, firstName: e.target.value })}
                className="w-full px-3 py-2 bg-[#162244] border border-[#1E2D5A] rounded-lg text-xs text-white focus:outline-hidden focus:border-blue-500"
              />
            </div>
            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1">Last Name *</label>
              <input
                type="text"
                required
                value={formData.lastName}
                onChange={(e) => setFormData({ ...formData, lastName: e.target.value })}
                className="w-full px-3 py-2 bg-[#162244] border border-[#1E2D5A] rounded-lg text-xs text-white focus:outline-hidden focus:border-blue-500"
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1">
                National ID Number *
              </label>
              <input
                type="text"
                required
                placeholder="63-123456-X-00"
                value={formData.nationalId}
                onChange={(e) => setFormData({ ...formData, nationalId: e.target.value })}
                className="w-full px-3 py-2 bg-[#162244] border border-[#1E2D5A] rounded-lg text-xs text-white font-mono focus:outline-hidden focus:border-blue-500"
              />
            </div>
            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1">Gender</label>
              <select
                value={formData.gender}
                onChange={(e) =>
                  setFormData({ ...formData, gender: e.target.value as Client['gender'] })
                }
                className="w-full px-3 py-2 bg-[#162244] border border-[#1E2D5A] rounded-lg text-xs text-white focus:outline-hidden focus:border-blue-500"
              >
                <option value="Male">Male</option>
                <option value="Female">Female</option>
                <option value="Other">Other</option>
              </select>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1">Branch / Location</label>
              <select
                value={formData.location}
                onChange={(e) => setFormData({ ...formData, location: e.target.value })}
                className="w-full px-3 py-2 bg-[#162244] border border-[#1E2D5A] rounded-lg text-xs text-white focus:outline-hidden focus:border-blue-500"
              >
                {locations.map((l) => (
                  <option key={l} value={l}>
                    {l}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1">Phone Number</label>
              <input
                type="text"
                placeholder="+263 77..."
                value={formData.phone}
                onChange={(e) => setFormData({ ...formData, phone: e.target.value })}
                className="w-full px-3 py-2 bg-[#162244] border border-[#1E2D5A] rounded-lg text-xs text-white font-mono focus:outline-hidden focus:border-blue-500"
              />
            </div>
          </div>

          <div>
            <label className="block text-xs font-semibold text-slate-300 mb-1">Residential Address</label>
            <input
              type="text"
              value={formData.address}
              onChange={(e) => setFormData({ ...formData, address: e.target.value })}
              className="w-full px-3 py-2 bg-[#162244] border border-[#1E2D5A] rounded-lg text-xs text-white focus:outline-hidden focus:border-blue-500"
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1">Occupation / Trade</label>
              <input
                type="text"
                value={formData.occupation}
                onChange={(e) => setFormData({ ...formData, occupation: e.target.value })}
                className="w-full px-3 py-2 bg-[#162244] border border-[#1E2D5A] rounded-lg text-xs text-white focus:outline-hidden focus:border-blue-500"
              />
            </div>
            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1">
                Average Monthly Income ($)
              </label>
              <input
                type="number"
                step="any"
                value={formData.averageIncome}
                onChange={(e) => setFormData({ ...formData, averageIncome: e.target.value })}
                className="w-full px-3 py-2 bg-[#162244] border border-[#1E2D5A] rounded-lg text-xs text-white focus:outline-hidden focus:border-blue-500"
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4 border-t border-[#1E2D5A] pt-3">
            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1">Guarantor Name</label>
              <input
                type="text"
                value={formData.guarantor}
                onChange={(e) => setFormData({ ...formData, guarantor: e.target.value })}
                className="w-full px-3 py-2 bg-[#162244] border border-[#1E2D5A] rounded-lg text-xs text-white focus:outline-hidden focus:border-blue-500"
              />
            </div>
            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1">
                Guarantor Phone
              </label>
              <input
                type="text"
                value={formData.guarantorPhone}
                onChange={(e) => setFormData({ ...formData, guarantorPhone: e.target.value })}
                className="w-full px-3 py-2 bg-[#162244] border border-[#1E2D5A] rounded-lg text-xs text-white font-mono focus:outline-hidden focus:border-blue-500"
              />
            </div>
          </div>

          <div>
            <label className="block text-xs font-semibold text-slate-300 mb-1">Internal Notes</label>
            <textarea
              rows={2}
              value={formData.notes}
              onChange={(e) => setFormData({ ...formData, notes: e.target.value })}
              className="w-full px-3 py-2 bg-[#162244] border border-[#1E2D5A] rounded-lg text-xs text-white focus:outline-hidden focus:border-blue-500"
            />
          </div>

          <div className="flex justify-end gap-2 pt-2 border-t border-[#1E2D5A]">
            <button
              type="button"
              onClick={() => setIsNewModalOpen(false)}
              className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-xs font-semibold transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-xs font-semibold shadow-xs transition-colors"
            >
              Save Client
            </button>
          </div>
        </form>
      </Modal>

      {/* Edit Client Modal */}
      <Modal
        isOpen={isEditModalOpen}
        onClose={() => setIsEditModalOpen(false)}
        title={`Edit Client: ${selectedClient?.clientNo}`}
        maxWidth="xl"
      >
        <form onSubmit={handleUpdateClient} className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1">
                First Name *
              </label>
              <input
                type="text"
                required
                value={formData.firstName}
                onChange={(e) => setFormData({ ...formData, firstName: e.target.value })}
                className="w-full px-3 py-2 bg-[#162244] border border-[#1E2D5A] rounded-lg text-xs text-white focus:outline-hidden focus:border-blue-500"
              />
            </div>
            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1">Last Name *</label>
              <input
                type="text"
                required
                value={formData.lastName}
                onChange={(e) => setFormData({ ...formData, lastName: e.target.value })}
                className="w-full px-3 py-2 bg-[#162244] border border-[#1E2D5A] rounded-lg text-xs text-white focus:outline-hidden focus:border-blue-500"
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1">
                National ID Number *
              </label>
              <input
                type="text"
                required
                value={formData.nationalId}
                onChange={(e) => setFormData({ ...formData, nationalId: e.target.value })}
                className="w-full px-3 py-2 bg-[#162244] border border-[#1E2D5A] rounded-lg text-xs text-white font-mono focus:outline-hidden focus:border-blue-500"
              />
            </div>
            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1">Status</label>
              <select
                value={formData.status}
                onChange={(e) =>
                  setFormData({ ...formData, status: e.target.value as Client['status'] })
                }
                className="w-full px-3 py-2 bg-[#162244] border border-[#1E2D5A] rounded-lg text-xs text-white focus:outline-hidden focus:border-blue-500"
              >
                <option value="Active">Active</option>
                <option value="Inactive">Inactive</option>
                <option value="Blacklisted">Blacklisted</option>
              </select>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1">Location</label>
              <select
                value={formData.location}
                onChange={(e) => setFormData({ ...formData, location: e.target.value })}
                className="w-full px-3 py-2 bg-[#162244] border border-[#1E2D5A] rounded-lg text-xs text-white focus:outline-hidden focus:border-blue-500"
              >
                {locations.map((l) => (
                  <option key={l} value={l}>
                    {l}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1">Phone Number</label>
              <input
                type="text"
                value={formData.phone}
                onChange={(e) => setFormData({ ...formData, phone: e.target.value })}
                className="w-full px-3 py-2 bg-[#162244] border border-[#1E2D5A] rounded-lg text-xs text-white font-mono focus:outline-hidden focus:border-blue-500"
              />
            </div>
          </div>

          <div>
            <label className="block text-xs font-semibold text-slate-300 mb-1">Address</label>
            <input
              type="text"
              value={formData.address}
              onChange={(e) => setFormData({ ...formData, address: e.target.value })}
              className="w-full px-3 py-2 bg-[#162244] border border-[#1E2D5A] rounded-lg text-xs text-white focus:outline-hidden focus:border-blue-500"
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1">Occupation</label>
              <input
                type="text"
                value={formData.occupation}
                onChange={(e) => setFormData({ ...formData, occupation: e.target.value })}
                className="w-full px-3 py-2 bg-[#162244] border border-[#1E2D5A] rounded-lg text-xs text-white focus:outline-hidden focus:border-blue-500"
              />
            </div>
            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1">
                Average Income ($)
              </label>
              <input
                type="number"
                step="any"
                value={formData.averageIncome}
                onChange={(e) => setFormData({ ...formData, averageIncome: e.target.value })}
                className="w-full px-3 py-2 bg-[#162244] border border-[#1E2D5A] rounded-lg text-xs text-white focus:outline-hidden focus:border-blue-500"
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4 border-t border-[#1E2D5A] pt-3">
            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1">Guarantor</label>
              <input
                type="text"
                value={formData.guarantor}
                onChange={(e) => setFormData({ ...formData, guarantor: e.target.value })}
                className="w-full px-3 py-2 bg-[#162244] border border-[#1E2D5A] rounded-lg text-xs text-white focus:outline-hidden focus:border-blue-500"
              />
            </div>
            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1">
                Guarantor Phone
              </label>
              <input
                type="text"
                value={formData.guarantorPhone}
                onChange={(e) => setFormData({ ...formData, guarantorPhone: e.target.value })}
                className="w-full px-3 py-2 bg-[#162244] border border-[#1E2D5A] rounded-lg text-xs text-white font-mono focus:outline-hidden focus:border-blue-500"
              />
            </div>
          </div>

          <div>
            <label className="block text-xs font-semibold text-slate-300 mb-1">Notes</label>
            <textarea
              rows={2}
              value={formData.notes}
              onChange={(e) => setFormData({ ...formData, notes: e.target.value })}
              className="w-full px-3 py-2 bg-[#162244] border border-[#1E2D5A] rounded-lg text-xs text-white focus:outline-hidden focus:border-blue-500"
            />
          </div>

          <div className="flex justify-end gap-2 pt-2 border-t border-[#1E2D5A]">
            <button
              type="button"
              onClick={() => setIsEditModalOpen(false)}
              className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-xs font-semibold transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-xs font-semibold shadow-xs transition-colors"
            >
              Update Client
            </button>
          </div>
        </form>
      </Modal>

      {/* Data Center: Import & Export Modal */}
      <DataImportExportModal
        isOpen={isImportExportModalOpen}
        onClose={() => setIsImportExportModalOpen(false)}
        initialTab={importExportTab}
        initialSection="clients"
      />
    </div>
  );
};
