/**
 * API 클라이언트 — fetch wrapper.
 *
 * 생성: T-002 (Frontend agent)
 */

export interface Todo {
  id: number;
  title: string;
  description: string;
  completed: boolean;
  created_at: string;
  updated_at: string;
  owner_id: number;
}

export interface TodoCreate {
  title: string;
  description?: string;
}

export interface TodoPatch {
  title?: string;
  description?: string;
  completed?: boolean;
}

const BASE = import.meta.env.VITE_API_BASE || "/api/todos";

function authHeader(): Record<string, string> {
  const token = localStorage.getItem("token");
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export async function fetchTodos(): Promise<Todo[]> {
  const r = await fetch(BASE, { headers: { ...authHeader() } });
  if (!r.ok) throw new Error(`fetch failed: ${r.status}`);
  return r.json();
}

export async function createTodo(payload: TodoCreate): Promise<Todo> {
  const r = await fetch(BASE, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...authHeader(),
    },
    body: JSON.stringify(payload),
  });
  if (!r.ok) throw new Error(`create failed: ${r.status}`);
  return r.json();
}

export async function patchTodo(id: number, patch: TodoPatch): Promise<Todo> {
  const r = await fetch(`${BASE}/${id}`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
      ...authHeader(),
    },
    body: JSON.stringify(patch),
  });
  if (!r.ok) throw new Error(`patch failed: ${r.status}`);
  return r.json();
}

export async function deleteTodo(id: number): Promise<void> {
  const r = await fetch(`${BASE}/${id}`, {
    method: "DELETE",
    headers: { ...authHeader() },
  });
  if (!r.ok && r.status !== 204) throw new Error(`delete failed: ${r.status}`);
}
