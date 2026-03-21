const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000/api";

export async function fetchJSON(path) {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) {
    const txt = await res.text();
    throw new Error(txt || `HTTP ${res.status}`);
  }
  return res.json();
}