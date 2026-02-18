"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import type { PuanConfig } from "@/lib/types";
import { savePuanConfig, resetAllPoints } from "@/app/actions/puan";

interface Props {
  config: PuanConfig;
  user: { discordId?: string; name: string };
}

export default function PuanClient({ config, user }: Props) {
  const router = useRouter();
  const [isPending, startTransition] = useTransition();
  const [showResetConfirm, setShowResetConfirm] = useState(false);
  const [saved, setSaved] = useState(false);
  const [resetDone, setResetDone] = useState(false);

  function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const fd = new FormData(e.currentTarget);
    startTransition(async () => {
      await savePuanConfig(fd);
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
      router.refresh();
    });
  }

  function handleReset() {
    startTransition(async () => {
      await resetAllPoints(user.name, user.discordId);
      setShowResetConfirm(false);
      setResetDone(true);
      setTimeout(() => setResetDone(false), 4000);
    });
  }

  return (
    <div>
      <h1 className="text-2xl font-bold text-white mb-6">Puan Ayarları</h1>

      <form onSubmit={handleSubmit} className="space-y-6 max-w-2xl">
        {/* Voice */}
        <Section title="🎤 Ses Kanalı Puanları">
          <div className="grid grid-cols-2 gap-4">
            <NumField label="Dakika Başı Puan" name="puan_per_minute" defaultValue={config.voice.puan_per_minute} step="0.01" />
            <NumField label="Günlük Maksimum" name="daily_max" defaultValue={config.voice.daily_max} />
            <NumField label="Uyarı Eşiği (dk)" name="warning_threshold" defaultValue={config.voice.warning_threshold} />
            <NumField label="Kick Eşiği (dk)" name="kick_threshold" defaultValue={config.voice.kick_threshold} />
          </div>
        </Section>

        {/* Content */}
        <Section title="⚔️ Content Varsayılanları">
          <div className="grid grid-cols-2 gap-4">
            <NumField label="Varsayılan Baz Puan" name="content_base" defaultValue={config.content?.default_base_points ?? 0} />
            <NumField label="Varsayılan Loot Bonus" name="content_loot" defaultValue={config.content?.default_loot_bonus_points ?? 0} />
          </div>
        </Section>

        {/* Mass */}
        <Section title="🛡️ Mass Varsayılanları">
          <div className="grid grid-cols-2 gap-4">
            <NumField label="Varsayılan Baz Puan" name="mass_base" defaultValue={config.mass?.default_base_points ?? 0} />
            <NumField label="Varsayılan Loot Bonus" name="mass_loot" defaultValue={config.mass?.default_loot_bonus_points ?? 0} />
          </div>
        </Section>

        <div className="flex items-center gap-3">
          <button
            type="submit"
            disabled={isPending}
            className="bg-[#5865F2] hover:bg-[#4752c4] text-white font-semibold py-2.5 px-6 rounded-lg transition-colors disabled:opacity-50"
          >
            {isPending ? "Kaydediliyor…" : "Ayarları Kaydet"}
          </button>
          {saved && (
            <span className="text-sm text-[#57F287] font-medium">✓ Kaydedildi</span>
          )}
        </div>
      </form>

      {/* Danger Zone */}
      <div className="mt-10 max-w-2xl">
        <div className="border border-[#ed4245]/30 rounded-xl overflow-hidden">
          <div className="bg-[#ed4245]/10 px-6 py-4 border-b border-[#ed4245]/30">
            <h2 className="text-[#ed4245] font-bold text-lg">⚠️ Tehlikeli Bölge</h2>
          </div>
          <div className="bg-[#1a1d27] p-6">
            <div className="flex items-center justify-between gap-4">
              <div>
                <p className="text-white font-semibold mb-1">Tüm Puanları Sıfırla</p>
                <p className="text-sm text-[#a3a6b1]">
                  Bu işlem tüm üyelerin puanlarını sıfırlar. Geri alınamaz.
                </p>
              </div>
              <button
                onClick={() => setShowResetConfirm(true)}
                className="flex-shrink-0 bg-[#ed4245] hover:bg-[#c03537] text-white font-bold py-2.5 px-5 rounded-lg transition-colors text-sm"
              >
                Tüm Puanları Sıfırla
              </button>
            </div>
            {resetDone && (
              <p className="mt-3 text-sm text-[#FEE75C] font-medium">
                ✓ Sıfırlama komutu kuyruğa eklendi.
              </p>
            )}
          </div>
        </div>
      </div>

      {/* Reset Confirm Modal */}
      {showResetConfirm && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
          <div className="bg-[#1a1d27] border border-[#ed4245]/40 rounded-2xl p-8 max-w-sm w-full shadow-2xl text-center">
            <div className="text-4xl mb-3">⚠️</div>
            <h3 className="text-lg font-bold text-white mb-2">Emin misin?</h3>
            <p className="text-[#a3a6b1] text-sm mb-6">
              Tüm üyelerin puanları sıfırlanacak. Bu işlem geri alınamaz.
            </p>
            <div className="flex gap-3">
              <button
                onClick={handleReset}
                disabled={isPending}
                className="flex-1 bg-[#ed4245] hover:bg-[#c03537] text-white font-bold py-2.5 rounded-lg transition-colors disabled:opacity-50"
              >
                Evet, Sıfırla
              </button>
              <button
                onClick={() => setShowResetConfirm(false)}
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

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="bg-[#1a1d27] border border-[#2a2d3e] rounded-xl overflow-hidden">
      <div className="px-6 py-4 border-b border-[#2a2d3e]">
        <h2 className="font-semibold text-white">{title}</h2>
      </div>
      <div className="p-6">{children}</div>
    </div>
  );
}

function NumField({
  label,
  name,
  defaultValue,
  step = "1",
}: {
  label: string;
  name: string;
  defaultValue: number;
  step?: string;
}) {
  return (
    <div>
      <label className="block text-sm font-medium text-[#a3a6b1] mb-1.5">{label}</label>
      <input
        type="number"
        name={name}
        defaultValue={defaultValue}
        step={step}
        min="0"
        className="w-full bg-[#0f1117] border border-[#2a2d3e] text-white rounded-lg px-3 py-2 text-sm focus:border-[#5865F2] outline-none"
      />
    </div>
  );
}
