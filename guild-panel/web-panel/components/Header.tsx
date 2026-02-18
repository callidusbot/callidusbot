"use client";

import Image from "next/image";
import { signOut } from "next-auth/react";

interface HeaderProps {
  user: {
    name?: string | null;
    image?: string | null;
    roles?: string[];
  };
}

const roleBadgeColors: Record<string, string> = {
  "Guild Master": "bg-yellow-500/20 text-yellow-300 border-yellow-500/40",
  "Subaylar": "bg-blue-500/20 text-blue-300 border-blue-500/40",
  "Recruiter": "bg-green-500/20 text-green-300 border-green-500/40",
  "Content Creator": "bg-purple-500/20 text-purple-300 border-purple-500/40",
};

export default function Header({ user }: HeaderProps) {
  return (
    <header className="h-14 bg-[#1a1d27] border-b border-[#2a2d3e] flex items-center justify-end px-6 gap-4 flex-shrink-0">
      <div className="flex items-center gap-2">
        {user.roles?.map((role) => (
          <span
            key={role}
            className={`text-xs px-2 py-0.5 rounded-full border font-medium ${
              roleBadgeColors[role] ?? "bg-gray-500/20 text-gray-300 border-gray-500/40"
            }`}
          >
            {role}
          </span>
        ))}
      </div>
      <div className="flex items-center gap-2">
        {user.image && (
          <Image
            src={user.image}
            alt={user.name ?? ""}
            width={32}
            height={32}
            className="rounded-full"
          />
        )}
        <span className="text-sm font-medium text-[#e3e5e8]">
          {user.name}
        </span>
      </div>
      <button
        onClick={() => signOut({ callbackUrl: "/auth/signin" })}
        className="text-xs text-[#a3a6b1] hover:text-white transition-colors px-2 py-1 rounded hover:bg-[#22263a]"
      >
        Çıkış
      </button>
    </header>
  );
}
