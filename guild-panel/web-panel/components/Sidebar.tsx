"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const navItems = [
  { href: "/", label: "Panel", icon: "⬛" },
  { href: "/sheets", label: "Sheet Yöneticisi", icon: "📊" },
  { href: "/templates", label: "Content Şablonları", icon: "📋" },
  { href: "/puan", label: "Puan Ayarları", icon: "⭐" },
];

export default function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="w-56 flex-shrink-0 bg-[#1a1d27] border-r border-[#2a2d3e] flex flex-col">
      <div className="px-4 py-5 border-b border-[#2a2d3e]">
        <span className="text-white font-bold text-lg tracking-wide">
          ⚔️ CALLIDUS
        </span>
      </div>
      <nav className="flex-1 py-4 px-2">
        {navItems.map((item) => {
          const active =
            item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`flex items-center gap-3 px-3 py-2.5 rounded-lg mb-1 text-sm font-medium transition-colors ${
                active
                  ? "bg-[#5865F2] text-white"
                  : "text-[#a3a6b1] hover:bg-[#22263a] hover:text-white"
              }`}
            >
              <span>{item.icon}</span>
              {item.label}
            </Link>
          );
        })}
      </nav>
    </aside>
  );
}
