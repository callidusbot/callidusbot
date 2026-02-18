"use client";

import { signOut } from "next-auth/react";

export default function ForbiddenPage() {
  return (
    <div className="min-h-screen bg-[#0f1117] flex items-center justify-center">
      <div className="bg-[#1a1d27] border border-[#ed4245]/30 rounded-2xl p-10 text-center max-w-sm w-full mx-4">
        <div className="text-5xl mb-4">🚫</div>
        <h1 className="text-2xl font-bold text-white mb-2">Yetkin Yok</h1>
        <p className="text-[#a3a6b1] text-sm mb-6">
          Bu panele erişim için gerekli rol(ler)e sahip değilsin.
          Guild Master, Subaylar, Recruiter veya Content Creator rollerinden birine ihtiyacın var.
        </p>
        <button
          onClick={() => signOut({ callbackUrl: "/auth/signin" })}
          className="bg-[#ed4245] hover:bg-[#c03537] text-white font-semibold py-2 px-6 rounded-lg transition-colors"
        >
          Çıkış Yap
        </button>
      </div>
    </div>
  );
}
