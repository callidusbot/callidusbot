"use client";

import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { Suspense } from "react";

function ErrorContent() {
  const params = useSearchParams();
  const error = params.get("error");

  return (
    <div className="min-h-screen bg-[#0f1117] flex items-center justify-center">
      <div className="bg-[#1a1d27] border border-[#2a2d3e] rounded-2xl p-10 text-center max-w-sm w-full mx-4">
        <div className="text-4xl mb-4">⚠️</div>
        <h1 className="text-xl font-bold text-white mb-2">Giriş Hatası</h1>
        <p className="text-[#a3a6b1] text-sm mb-6">
          {error === "AccessDenied"
            ? "Bu panele erişim yetkin yok."
            : "Bir hata oluştu. Lütfen tekrar dene."}
        </p>
        <Link
          href="/auth/signin"
          className="inline-block bg-[#5865F2] hover:bg-[#4752c4] text-white font-semibold py-2 px-6 rounded-lg transition-colors"
        >
          Geri Dön
        </Link>
      </div>
    </div>
  );
}

export default function AuthErrorPage() {
  return (
    <Suspense fallback={<div className="min-h-screen bg-[#0f1117]" />}>
      <ErrorContent />
    </Suspense>
  );
}
