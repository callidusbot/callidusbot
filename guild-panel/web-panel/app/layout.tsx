import "./globals.css";
import type { Metadata } from "next";
import SessionProviderWrapper from "@/components/SessionProviderWrapper";
import Sidebar from "@/components/Sidebar";
import Header from "@/components/Header";
import { getServerSession } from "next-auth";
import { authOptions } from "@/lib/auth";

export const metadata: Metadata = {
  title: "CALLIDUS Panel",
  description: "CALLIDUS Guild Yönetim Paneli",
};

export default async function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const session = await getServerSession(authOptions);
  const isAuthed = !!session?.user?.allowed;

  return (
    <html lang="tr">
      <body>
        <SessionProviderWrapper>
          {isAuthed ? (
            <div className="flex h-screen overflow-hidden">
              <Sidebar />
              <div className="flex flex-col flex-1 overflow-hidden">
                <Header user={session.user} />
                <main className="flex-1 overflow-y-auto p-6">{children}</main>
              </div>
            </div>
          ) : (
            <main className="min-h-screen">{children}</main>
          )}
        </SessionProviderWrapper>
      </body>
    </html>
  );
}
