import { getServerSession } from "next-auth";
import { authOptions } from "@/lib/auth";
import { redirect } from "next/navigation";
import ForbiddenPage from "@/components/ForbiddenPage";
import { readJsonObject } from "@/lib/bot-utils";
import type { PuanConfig } from "@/lib/types";
import { DEFAULT_PUAN_CONFIG } from "@/lib/types";
import PuanClient from "@/components/PuanClient";

export const dynamic = "force-dynamic";

export default async function PuanPage() {
  const session = await getServerSession(authOptions);
  if (!session) redirect("/auth/signin");
  if (!session.user?.allowed) return <ForbiddenPage />;

  const config = readJsonObject<PuanConfig>("puan_config.json", DEFAULT_PUAN_CONFIG);

  return (
    <PuanClient
      config={config}
      user={{
        discordId: session.user.discordId,
        name: session.user.name ?? "Unknown",
      }}
    />
  );
}
