"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import type { ContentTemplate } from "@/lib/types";
import { addTemplate, updateTemplate, deleteTemplate } from "@/app/actions/templates";

interface Props {
  templates: ContentTemplate[];
}

const emptyForm = {
  key: "",
  title: "",
  subtitle: "",
  thread_name: "",
  emoji: "",
  category: "content" as "content" | "mass",
  order: "1",
  roles: "",
  base_points: "0",
  loot_bonus_points: "0",
};

function rolesToString(roles: { role_name: string; capacity: number }[]) {
  return roles.map((r) => `${r.role_name}:${r.capacity}`).join(", ");
}

export default function TemplatesClient({ templates }: Props) {
  const router = useRouter();
  const [isPending, startTransition] = useTransition();
  const [showForm, setShowForm] = useState(false);
  const [editKey, setEditKey] = useState<string | null>(null);
  const [form, setForm] = useState(emptyForm);
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null);

  function openAdd() {
    setForm({ ...emptyForm, order: String(templates.length + 1) });
    setEditKey(null);
    setShowForm(true);
  }

  function openEdit(t: ContentTemplate) {
    setForm({
      key: t.key,
      title: t.title,
      subtitle: t.subtitle,
      thread_name: t.thread_name,
      emoji: t.emoji,
      category: t.category,
      order: String(t.order),
      roles: rolesToString(t.roles),
      base_points: String(t.base_points),
      loot_bonus_points: String(t.loot_bonus_points),
    });
    setEditKey(t.key);
    setShowForm(true);
  }

  function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const fd = new FormData(e.currentTarget);
    startTransition(async () => {
      if (editKey) {
        await updateTemplate(editKey, fd);
      } else {
        await addTemplate(fd);
      }
      setShowForm(false);
      setEditKey(null);
      router.refresh();
    });
  }

  function handleDelete(key: string) {
    startTransition(async () => {
      await deleteTemplate(key);
      setDeleteConfirm(null);
      router.refresh();
    });
  }

  function setF(field: string, value: string) {
    setForm((prev) => ({ ...prev, [field]: value }));
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-white">Content Şablonları</h1>
        <button
          onClick={openAdd}
          className="bg-[#5865F2] hover:bg-[#4752c4] text-white font-semibold py-2 px-4 rounded-lg transition-colors text-sm"
        >
          + Şablon Ekle
        </button>
      </div>

      {templates.length === 0 ? (
        <div className="bg-[#1a1d27] border border-[#2a2d3e] rounded-xl p-12 text-center">
          <div className="text-4xl mb-3">📋</div>
          <p className="text-[#a3a6b1]">Henüz şablon eklenmemiş.</p>
        </div>
      ) : (
        <div className="grid gap-4">
          {templates.map((t) => (
            <div
              key={t.key}
              className="bg-[#1a1d27] border border-[#2a2d3e] rounded-xl p-5 flex items-start justify-between gap-4"
            >
              <div className="flex items-start gap-4">
                <span className="text-3xl mt-0.5">{t.emoji}</span>
                <div>
                  <div className="flex items-center gap-2 mb-1">
                    <span className="font-semibold text-white">{t.title}</span>
                    <span className="text-xs px-2 py-0.5 rounded-full bg-[#22263a] text-[#a3a6b1] border border-[#2a2d3e]">
                      #{t.order}
                    </span>
                    <span
                      className={`text-xs px-2 py-0.5 rounded-full font-medium border ${
                        t.category === "mass"
                          ? "bg-blue-500/15 text-blue-300 border-blue-500/30"
                          : "bg-purple-500/15 text-purple-300 border-purple-500/30"
                      }`}
                    >
                      {t.category === "mass" ? "Mass" : "Content"}
                    </span>
                  </div>
                  <p className="text-sm text-[#a3a6b1] mb-2">{t.subtitle}</p>
                  <div className="flex flex-wrap gap-1.5">
                    {t.roles.map((r) => (
                      <span
                        key={r.role_name}
                        className="text-xs bg-[#22263a] text-[#a3a6b1] px-2 py-0.5 rounded border border-[#2a2d3e]"
                      >
                        {r.role_name} × {r.capacity}
                      </span>
                    ))}
                  </div>
                  <div className="mt-2 flex gap-3 text-xs text-[#6d7080]">
                    <span>Baz Puan: <span className="text-[#a3a6b1]">{t.base_points}</span></span>
                    <span>Loot Bonus: <span className="text-[#a3a6b1]">{t.loot_bonus_points}</span></span>
                    <span>Thread: <span className="text-[#a3a6b1]">{t.thread_name}</span></span>
                  </div>
                </div>
              </div>
              <div className="flex gap-2 flex-shrink-0">
                <button
                  onClick={() => openEdit(t)}
                  className="text-xs text-[#5865F2] hover:text-white font-medium transition-colors px-2 py-1 rounded hover:bg-[#5865F2]/20"
                >
                  Düzenle
                </button>
                <button
                  onClick={() => setDeleteConfirm(t.key)}
                  className="text-xs text-[#ed4245] hover:text-white font-medium transition-colors px-2 py-1 rounded hover:bg-[#ed4245]/20"
                >
                  Sil
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Form Modal */}
      {showForm && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4 overflow-y-auto">
          <div className="bg-[#1a1d27] border border-[#2a2d3e] rounded-2xl p-8 max-w-lg w-full shadow-2xl my-8">
            <h3 className="text-lg font-bold text-white mb-6">
              {editKey ? "Şablon Düzenle" : "Şablon Ekle"}
            </h3>
            <form onSubmit={handleSubmit} className="space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <F label="Anahtar (key)" name="key" value={form.key} onChange={(v) => setF("key", v)} required disabled={!!editKey} />
                <F label="Emoji" name="emoji" value={form.emoji} onChange={(v) => setF("emoji", v)} />
              </div>
              <F label="Başlık" name="title" value={form.title} onChange={(v) => setF("title", v)} required />
              <F label="Alt Başlık" name="subtitle" value={form.subtitle} onChange={(v) => setF("subtitle", v)} />
              <div className="grid grid-cols-2 gap-4">
                <F label="Thread Adı" name="thread_name" value={form.thread_name} onChange={(v) => setF("thread_name", v)} />
                <F label="Sıra (order)" name="order" value={form.order} onChange={(v) => setF("order", v)} type="number" />
              </div>
              <div>
                <label className="block text-sm font-medium text-[#a3a6b1] mb-1.5">Kategori</label>
                <select
                  name="category"
                  value={form.category}
                  onChange={(e) => setF("category", e.target.value)}
                  className="w-full bg-[#0f1117] border border-[#2a2d3e] text-white rounded-lg px-3 py-2 text-sm focus:border-[#5865F2] outline-none"
                >
                  <option value="content">Content</option>
                  <option value="mass">Mass</option>
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-[#a3a6b1] mb-1.5">
                  Roller <span className="text-[#6d7080] font-normal">(format: Tank:2, Healer:2, DPS:16)</span>
                </label>
                <input
                  type="text"
                  name="roles"
                  value={form.roles}
                  onChange={(e) => setF("roles", e.target.value)}
                  placeholder="Tank:2, Healer:2, DPS:16"
                  className="w-full bg-[#0f1117] border border-[#2a2d3e] text-white rounded-lg px-3 py-2 text-sm focus:border-[#5865F2] outline-none placeholder:text-[#6d7080]"
                />
              </div>
              <div className="grid grid-cols-2 gap-4">
                <F label="Baz Puan" name="base_points" value={form.base_points} onChange={(v) => setF("base_points", v)} type="number" />
                <F label="Loot Bonus Puan" name="loot_bonus_points" value={form.loot_bonus_points} onChange={(v) => setF("loot_bonus_points", v)} type="number" />
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
                  onClick={() => { setShowForm(false); setEditKey(null); }}
                  className="flex-1 bg-[#22263a] hover:bg-[#2a2d3e] text-white font-semibold py-2.5 rounded-lg transition-colors"
                >
                  İptal
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Delete Confirm */}
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

function F({
  label,
  name,
  value,
  onChange,
  placeholder,
  required,
  disabled,
  type = "text",
}: {
  label: string;
  name: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  required?: boolean;
  disabled?: boolean;
  type?: string;
}) {
  return (
    <div>
      <label className="block text-sm font-medium text-[#a3a6b1] mb-1.5">{label}</label>
      <input
        type={type}
        name={name}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        required={required}
        disabled={disabled}
        className="w-full bg-[#0f1117] border border-[#2a2d3e] text-white rounded-lg px-3 py-2 text-sm focus:border-[#5865F2] outline-none placeholder:text-[#6d7080] disabled:opacity-50"
      />
    </div>
  );
}
