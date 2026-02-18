"use server";

import { readJson, writeJsonAtomic } from "@/lib/bot-utils";
import { revalidatePath } from "next/cache";
import type { DynamicSheet } from "@/lib/types";

function extractSheetId(input: string): string {
  const match = input.match(/\/d\/([a-zA-Z0-9_-]+)/);
  return match ? match[1] : input.trim();
}

function generateSlug(name: string, existing: string[]): string {
  const base = name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
  let slug = base;
  let i = 2;
  while (existing.includes(slug)) {
    slug = `${base}-${i}`;
    i++;
  }
  return slug;
}

export async function addSheet(formData: FormData) {
  const name = (formData.get("name") as string).trim();
  const sheet_url_or_id = extractSheetId(formData.get("sheet_url_or_id") as string);
  const tab = (formData.get("tab") as string).trim();
  const emoji = (formData.get("emoji") as string).trim();
  const type = formData.get("type") as "content" | "mass";

  const sheets = readJson<DynamicSheet[]>("dynamic_sheets.json");
  const safeSheets = Array.isArray(sheets) ? sheets : [];

  const slug = generateSlug(name, safeSheets.map((s) => s.slug));

  const newSheet: DynamicSheet = {
    name,
    sheet_url_or_id,
    tab,
    emoji,
    type,
    slug,
  };

  writeJsonAtomic("dynamic_sheets.json", [...safeSheets, newSheet]);
  revalidatePath("/sheets");
}

export async function updateSheet(slug: string, formData: FormData) {
  const sheets = readJson<DynamicSheet[]>("dynamic_sheets.json");
  const safeSheets = Array.isArray(sheets) ? sheets : [];

  const name = (formData.get("name") as string).trim();
  const sheet_url_or_id = extractSheetId(formData.get("sheet_url_or_id") as string);
  const tab = (formData.get("tab") as string).trim();
  const emoji = (formData.get("emoji") as string).trim();
  const type = formData.get("type") as "content" | "mass";

  const updated = safeSheets.map((s) =>
    s.slug === slug ? { ...s, name, sheet_url_or_id, tab, emoji, type } : s
  );

  writeJsonAtomic("dynamic_sheets.json", updated);
  revalidatePath("/sheets");
}

export async function deleteSheet(slug: string) {
  const sheets = readJson<DynamicSheet[]>("dynamic_sheets.json");
  const safeSheets = Array.isArray(sheets) ? sheets : [];
  writeJsonAtomic("dynamic_sheets.json", safeSheets.filter((s) => s.slug !== slug));
  revalidatePath("/sheets");
}
