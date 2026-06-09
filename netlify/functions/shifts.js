import { getStore } from "@netlify/blobs";

const STORE = "emily-shifts";
const KEY   = "overrides";

export default async (req) => {
  const cors = {
    "Access-Control-Allow-Origin":  "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
  };

  if (req.method === "OPTIONS") {
    return new Response(null, { status: 204, headers: cors });
  }

  const store = getStore(STORE);

  // ── GET: return current shifts (or empty if none saved yet) ──
  if (req.method === "GET") {
    try {
      const data = await store.get(KEY, { type: "json" });
      return Response.json(data ?? {}, { headers: cors });
    } catch {
      return Response.json({}, { headers: cors });
    }
  }

  // ── POST: save shifts (password required) ──
  if (req.method === "POST") {
    let body;
    try {
      body = await req.json();
    } catch {
      return new Response("Bad request", { status: 400, headers: cors });
    }

    const { password, shifts } = body;

    if (!password || password !== process.env.EDIT_PASSWORD) {
      return new Response("Unauthorized", { status: 401, headers: cors });
    }

    if (!shifts || typeof shifts !== "object" || Array.isArray(shifts)) {
      return new Response("Invalid shifts data", { status: 400, headers: cors });
    }

    try {
      await store.set(KEY, JSON.stringify(shifts));
      return Response.json({ ok: true }, { headers: cors });
    } catch (e) {
      return new Response("Storage error: " + e.message, { status: 500, headers: cors });
    }
  }

  return new Response("Method not allowed", { status: 405, headers: cors });
};

export const config = { path: "/api/shifts" };
