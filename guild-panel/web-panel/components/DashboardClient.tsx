"use client";

import Image from "next/image";
import { useState } from "react";
import { useRouter } from "next/navigation";
import type { ActiveEvent } from "@/lib/types";
import { closeContentAction } from "@/app/actions/events";

interface Props {
  activeEvents: ActiveEvent[];
  totalSheets: number;
  totalTemplates: number;
  user: { discordId?: string; name: string };
}

export default function DashboardClient({
  activeEvents,
  totalSheets,
  totalTemplates,
  user,
}: Props) {
  const router = useRouter();
  const [modalEvent, setModalEvent] = useState<ActiveEvent | null>(null);
  const [loading, setLoading] = useState(false);
  const [confirmed, setConfirmed] = useState<string[]>([]);

  async function handleClose(startLoot: boolean) {
    if (!modalEvent) return;
    setLoading(true);
    try {
      await closeContentAction({
        event_id: modalEvent.event_id,
        thread_id: modalEvent.thread_id,
        start_loot: startLoot,
        requested_by: user.discordId ? Number(user.discordId) : undefined,
        requested_by_name: user.name,
      });
      setConfirmed((prev) => [...prev, modalEvent.event_id]);
      setModalEvent(null);
      router.refresh();
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }

  function formatDate(ts: number) {
    return new Date(ts * 1000).toLocaleString("tr-TR");
  }

  const stats = [
    { label: "Sheet Sayısı", value: totalSheets, emoji: "📊" },
    { label: "Şablon Sayısı", value: totalTemplates, emoji: "📋" },
    { label: "Aktif Event", value: activeEvents.length, emoji: "🔴" },
  ];

  return (
    <div>
      <h1 className="text-2xl font-bold text-white mb-6">Panel</h1>

      {/* Stats */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-8">
        {stats.map((s) => (
          <div
            key={s.label}
            className="bg-[#1a1d27] border border-[#2a2d3e] rounded-xl p-5 flex items-center gap-4"
          >
            <span className="text-3xl">{s.emoji}</span>
            <div>
              <div className="text-2xl font-bold text-white">{s.value}</div>
              <div className="text-sm text-[#a3a6b1]">{s.label}</div>
            </div>
          </div>
        ))}
      </div>

      {/* Active Events Table */}
      <div className="bg-[#1a1d27] border border-[#2a2d3e] rounded-xl overflow-hidden">
        <div className="px-6 py-4 border-b border-[#2a2d3e]">
          <h2 className="text-lg font-semibold text-white">Aktif Eventler</h2>
        </div>

        {activeEvents.length === 0 ? (
          <div className="p-12 text-center">
            <div className="text-4xl mb-3">📭</div>
            <p className="text-[#a3a6b1]">Şu anda aktif event yok.</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b border-[#2a2d3e]">
                  <th className="px-6 py-3 text-left text-xs font-semibold text-[#6d7080] uppercase tracking-wider">
                    Şablon
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-semibold text-[#6d7080] uppercase tracking-wider">
                    Başlatan
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-semibold text-[#6d7080] uppercase tracking-wider">
                    Başlangıç
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-semibold text-[#6d7080] uppercase tracking-wider">
                    Katılımcı
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-semibold text-[#6d7080] uppercase tracking-wider">
                    Durum
                  </th>
                  <th className="px-6 py-3 text-right text-xs font-semibold text-[#6d7080] uppercase tracking-wider">
                    İşlem
                  </th>
                </tr>
              </thead>
              <tbody>
                {activeEvents.map((evt) => (
                  <tr
                    key={evt.event_id}
                    className="border-b border-[#2a2d3e] last:border-0 hover:bg-[#22263a]/50 transition-colors"
                  >
                    <td className="px-6 py-4 text-sm font-medium text-white">
                      {evt.template_title}
                    </td>
                    <td className="px-6 py-4">
                      <div className="flex items-center gap-2">
                        {evt.started_by_avatar && (
                          <Image
                            src={evt.started_by_avatar}
                            alt={evt.started_by_name}
                            width={24}
                            height={24}
                            className="rounded-full"
                          />
                        )}
                        <span className="text-sm text-[#e3e5e8]">
                          {evt.started_by_name}
                        </span>
                      </div>
                    </td>
                    <td className="px-6 py-4 text-sm text-[#a3a6b1]">
                      {formatDate(evt.started_at)}
                    </td>
                    <td className="px-6 py-4 text-sm text-[#e3e5e8]">
                      {evt.participant_count}
                    </td>
                    <td className="px-6 py-4">
                      <span className="inline-flex items-center gap-1.5 text-xs font-medium px-2.5 py-1 rounded-full bg-green-500/15 text-green-400 border border-green-500/30">
                        <span className="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse" />
                        Aktif
                      </span>
                    </td>
                    <td className="px-6 py-4 text-right">
                      {confirmed.includes(evt.event_id) ? (
                        <span className="text-xs text-green-400 font-medium">
                          ✓ Gönderildi
                        </span>
                      ) : (
                        <button
                          onClick={() => setModalEvent(evt)}
                          className="text-xs bg-[#5865F2] hover:bg-[#4752c4] text-white font-semibold py-1.5 px-3 rounded-lg transition-colors"
                        >
                          Content Kapat
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Modal */}
      {modalEvent && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
          <div className="bg-[#1a1d27] border border-[#2a2d3e] rounded-2xl p-8 max-w-sm w-full shadow-2xl">
            <h3 className="text-lg font-bold text-white mb-2">
              Content Kapat
            </h3>
            <p className="text-[#a3a6b1] text-sm mb-2">
              <span className="font-medium text-white">
                {modalEvent.template_title}
              </span>{" "}
              eventi kapatılıyor.
            </p>
            <p className="text-[#e3e5e8] font-medium mb-6">
              Loot paylaşımı başlatılsın mı?
            </p>
            <div className="flex gap-3">
              <button
                onClick={() => handleClose(true)}
                disabled={loading}
                className="flex-1 bg-[#57F287] hover:bg-[#3dd668] text-[#0f1117] font-bold py-2.5 rounded-lg transition-colors disabled:opacity-50"
              >
                Evet
              </button>
              <button
                onClick={() => handleClose(false)}
                disabled={loading}
                className="flex-1 bg-[#22263a] hover:bg-[#2a2d3e] text-white font-semibold py-2.5 rounded-lg transition-colors disabled:opacity-50"
              >
                Hayır
              </button>
            </div>
            <button
              onClick={() => setModalEvent(null)}
              disabled={loading}
              className="w-full mt-3 text-sm text-[#6d7080] hover:text-[#a3a6b1] transition-colors py-1"
            >
              İptal
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
