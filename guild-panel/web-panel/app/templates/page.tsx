import { getServerSession } from "next-auth";
import { authOptions } from "@/lib/auth";
import { redirect } from "next/navigation";
import ForbiddenPage from "@/components/ForbiddenPage";
import { readJson } from "@/lib/bot-utils";
import type { ContentTemplate } from "@/lib/types";
import TemplatesClient from "@/components/TemplatesClient";

export const dynamic = "force-dynamic";

export default async function TemplatesPage() {
  const session = await getServerSession(authOptions);
  if (!session) redirect("/auth/signin");
  if (!session.user?.allowed) return <ForbiddenPage />;

  const raw = readJson<ContentTemplate[]>("content_templates.json");
  const templates = (Array.isArray(raw) ? raw : []).sort((a, b) => a.order - b.order);

  return <TemplatesClient templates={templates} />;
}
