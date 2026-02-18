"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import type { DynamicSheet } from "@/lib/types";
import { addSheet, updateSheet, deleteSheet } from "@/app/actions/sheets";

interface Props {
  sheets: DynamicSheet[];
}

const emptyForm = {
  name: "",
  sheet_url_or_id: "",
  tab: "",
  emoji: "",
  type: "content" as const,
};

export default function SheetsClient({ sheets }: Props) {
  const router = useRouter();
  const [isPending, startTransition] = useTransition();
  const [showAdd, setShowAdd] = useState(false);
  const [editSlug, setEditSlug] = useState<string | null>(null);
  const [form, setForm] = useState(emptyForm);
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null);

  function openAdd() {
    setForm(emptyForm);
    setEditSlug(null);
    setShowAdd(true);
  }

  function openEdit(sheet: DynamicSheet) {
    setForm({
      name: sheet.name,
      sheet_url_or_id: sheet.sheet_url_or_id,
      tab: sheet.tab,
      emoji: sheet.emoji,
      type: sheet.type as "content" | "mass",
    });
    setEditSlug(sheet.slug);
    setShowAdd(true);
  }

  function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const fd = new FormData(e.currentTarget);
    startTransition(async () => {
      if (editSlug) {
        await updateSheet(editSlug, fd);
      } else {
        await addSheet(fd);
      }
      setShowAdd(false);
      setEditSlug(null);
      router.refresh();
    });
  }

  function handleDelete(slug: string) {
    startTransition(async () => {
      await deleteSheet(slug);
      setDeleteConfirm(null);
      router.refresh();
    });
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-white">Sheet Yöneticisi</h1>
        <button
          onClick={openAdd}
          className="bg-[#5865F2] hover:bg-[#4752c4] text-white font-semibold py-2 px-4 rounded-lg transition-colors text-sm"
        >
          + Sheet Ekle
        </button>
      </div>

      {sheets.length === 0 ? (
        <div className="bg-[#1a1d27] border border-[#2a2d3e] rounded-xl p-12 text-center">
          <div className="text-4xl mb-3">📊</div>
          <p className="text-[#a3a6b1]">Henüz sheet eklenmemiş.</p>
        </div>
      ) : (
        <div className="bg-[#1a1d27] border border-[#2a2d3e] rounded-xl overflow-hidden">
          <table className="w-full">
            <thead>
              <tr className="border-b border-[#2a2d3e]">
                {["Emoji", "İsim", "Sheet ID", "Tab", "Tür", ""].map((h) => (
                  <th
                    key={h}
                    className="px-6 py-3 text-left text-xs font-semibold text-[#6d7080] uppercase tracking-wider"
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sheets.map((sheet) => (
                <tr
                  key={sheet.slug}
                  className="border-b border-[#2a2d3e] last:border-0 hover:bg-[#22263a]/50 transition-colors"
                >
                  <td className="px-6 py-4 text-xl">{sheet.emoji}</td>
                  <td className="px-6 py-4 text-sm font-medium text-white">
                    {sheet.name}
                  </td>
                  <td className="px-6 py-4 text-sm text-[#a3a6b1] font-mono">
                    {sheet.sheet_url_or_id.length > 30
                      ? sheet.sheet_url_or_id.slice(0, 30) + "…"
                      : sheet.sheet_url_or_id}
                  </td>
                  <td className="px-6 py-4 text-sm text-[#a3a6b1]">{sheet.tab}</td>
                  <td className="px-6 py-4">
                    <span
                      className={`text-xs px-2 py-0.5 rounded-full font-medium border ${
                        sheet.type === "mass"
                          ? "bg-blue-500/15 text-blue-300 border-blue-500/30"
                          : "bg-purple-500/15 text-purple-300 border-purple-500/30"
                      }`}
                    >
                      {sheet.type === "mass" ? "Mass" : "Content"}
                    </span>
                  </td>
                  <td className="px-6 py-4 text-right">
                    <div className="flex items-center justify-end gap-2">
                      <button
                        onClick={() => openEdit(sheet)}
                        className="text-xs text-[#5865F2] hover:text-white font-medium transition-colors px-2 py-1 rounded hover:bg-[#5865F2]/20"
                      >
                        Düzenle
                      </button>
                      <button
                        onClick={() => setDeleteConfirm(sheet.slug)}
                        className="text-xs text-[#ed4245] hover:text-white font-medium transition-colors px-2 py-1 rounded hover:bg-[#ed4245]/20"
                      >
                        Sil
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Add/Edit Modal */}
      {showAdd && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
          <div className="bg-[#1a1d27] border border-[#2a2d3e] rounded-2xl p-8 max-w-md w-full shadow-2xl">
            <h3 className="text-lg font-bold text-white mb-6">
              {editSlug ? "Sheet Düzenle" : "Sheet Ekle"}
            </h3>
            <form onSubmit={handleSubmit} className="space-y-4">
              <Field label="İsim" name="name" value={form.name} onChange={(v) => setForm({ ...form, name: v })} required />
              <Field
                label="Google Sheet URL veya ID"
                name="sheet_url_or_id"
                value={form.sheet_url_or_id}
                onChange={(v) => setForm({ ...form, sheet_url_or_id: v })}
                placeholder="https://docs.google.com/spreadsheets/d/... veya ID"
                required
              />
              <Field label="Tab Adı" name="tab" value={form.tab} onChange={(v) => setForm({ ...form, tab: v })} required />
              <Field label="Emoji" name="emoji" value={form.emoji} onChange={(v) => setForm({ ...form, emoji: v })} />
              <div>
                <label className="block text-sm font-medium text-[#a3a6b1] mb-1.5">Tür</label>
                <select
                  name="type"
                  value={form.type}
                  onChange={(e) => setForm({ ...form, type: e.target.value as "content" | "mass" })}
                  className="w-full bg-[#0f1117] border border-[#2a2d3e] text-white rounded-lg px-3 py-2 text-sm focus:border-[#5865F2] outline-none"
                >
                  <option value="content">Content</option>
                  <option value="mass">Mass</option>
                </select>
              </div>
              <div className="flex gap-3 pt-2">
                <button
                  type="submit"
                  disabled={isPending}
                  className="flex-1 bg-[#5865F2] hover:bg-[#4752c4] text-white font-semibold py-2.5 rounded-lg transition-colors disabled:opacity-50"
                >
                  {isPending ? "Kaydediliyor…" : "Kaydet"}
                </button>
                <button
                  type="button"
                  onClick={() => { setShowAdd(false); setEditSlug(null); }}
                  className="flex-1 bg-[#22263a] hover:bg-[#2a2d3e] text-white font-semibold py-2.5 rounded-lg transition-colors"
                >
                  İptal
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Delete Confirm Modal */}
      {deleteConfirm && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
          <div className="bg-[#1a1d27] border border-[#2a2d3e] rounded-2xl p-8 max-w-sm w-full shadow-2xl text-center">
            <div className="text-3xl mb-3">🗑️</div>
            <h3 className="text-lg font-bold text-white mb-2">Silmek istediğine emin misin?</h3>
            <p className="text-[#a3a6b1] text-sm mb-6">Bu işlem geri alınamaz.</p>
            <div className="flex gap-3">
              <button
                onClick={() => handleDelete(deleteConfirm)}
                disabled={isPending}
                className="flex-1 bg-[#ed4245] hover:bg-[#c03537] text-white font-bold py-2.5 rounded-lg transition-colors disabled:opacity-50"
              >
                Evet, Sil
              </button>
              <button
                onClick={() => setDeleteConfirm(null)}
                className="flex-1 bg-[#22263a] hover:bg-[#2a2d3e] text-white font-semibold py-2.5 rounded-lg transition-colors"
              >
                İptal
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function Field({
  label,
  name,
  value,
  onChange,
  placeholder,
  required,
}: {
  label: string;
  name: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  required?: boolean;
}) {
  return (
    <div>
      <label className="block text-sm font-medium text-[#a3a6b1] mb-1.5">{label}</label>
      <input
        type="text"
        name={name}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        required={required}
        className="w-full bg-[#0f1117] border border-[#2a2d3e] text-white rounded-lg px-3 py-2 text-sm focus:border-[#5865F2] outline-none placeholder:text-[#6d7080]"
      />
    </div>
  );
}
