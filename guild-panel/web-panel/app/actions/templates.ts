"use server";

import { readJson, writeJsonAtomic, pushToQueue } from "@/lib/bot-utils";
import { revalidatePath } from "next/cache";
import type { ContentTemplate, ContentRole } from "@/lib/types";

function parseRoles(raw: string): ContentRole[] {
  if (!raw.trim()) return [];
  return raw
    .split(",")
    .map((part) => {
      const [role_name, cap] = part.split(":").map((s) => s.trim());
      return { role_name: role_name ?? "", capacity: parseInt(cap ?? "1") || 1 };
    })
    .filter((r) => r.role_name);
}

async function notifyBotReload() {
  try {
    await pushToQueue("reload_templates", {});
  } catch {
    // Sessizce geç — bot çalışmıyorsa sorun değil
  }
}

export async function addTemplate(formData: FormData) {
  const templates = readJson<ContentTemplate[]>("content_templates.json");
  const safe = Array.isArray(templates) ? templates : [];

  const key = (formData.get("key") as string).trim();
  const title = (formData.get("title") as string).trim();
  const subtitle = (formData.get("subtitle") as string).trim();
  const thread_name = (formData.get("thread_name") as string).trim();
  const emoji = (formData.get("emoji") as string).trim();
  const category = formData.get("category") as "content" | "mass";
  const order = parseInt(formData.get("order") as string) || safe.length + 1;
  const roles = parseRoles(formData.get("roles") as string);
  const base_points = parseFloat(formData.get("base_points") as string) || 0;
  const loot_bonus_points = parseFloat(formData.get("loot_bonus_points") as string) || 0;

  const newTemplate: ContentTemplate = {
    key, title, subtitle, thread_name, emoji, category, order,
    roles, base_points, loot_bonus_points,
  };

  const sorted = [...safe, newTemplate].sort((a, b) => a.order - b.order);
  writeJsonAtomic("content_templates.json", sorted);
  await notifyBotReload();
  revalidatePath("/templates");
}

export async function updateTemplate(key: string, formData: FormData) {
  const templates = readJson<ContentTemplate[]>("content_templates.json");
  const safe = Array.isArray(templates) ? templates : [];

  const title = (formData.get("title") as string).trim();
  const subtitle = (formData.get("subtitle") as string).trim();
  const thread_name = (formData.get("thread_name") as string).trim();
  const emoji = (formData.get("emoji") as string).trim();
  const category = formData.get("category") as "content" | "mass";
  const order = parseInt(formData.get("order") as string) || 1;
  const roles = parseRoles(formData.get("roles") as string);
  const base_points = parseFloat(formData.get("base_points") as string) || 0;
  const loot_bonus_points = parseFloat(formData.get("loot_bonus_points") as string) || 0;

  const updated = safe
    .map((t) =>
      t.key === key
        ? { ...t, title, subtitle, thread_name, emoji, category, order, roles, base_points, loot_bonus_points }
        : t
    )
    .sort((a, b) => a.order - b.order);

  writeJsonAtomic("content_templates.json", updated);
  await notifyBotReload();
  revalidatePath("/templates");
}

export async function deleteTemplate(key: string) {
  const templates = readJson<ContentTemplate[]>("content_templates.json");
  const safe = Array.isArray(templates) ? templates : [];
  writeJsonAtomic("content_templates.json", safe.filter((t) => t.key !== key));
  await notifyBotReload();
  revalidatePath("/templates");
}
