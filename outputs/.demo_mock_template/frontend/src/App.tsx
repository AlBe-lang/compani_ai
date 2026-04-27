/**
 * Todo App — main view.
 *
 * 생성: T-002 (Frontend agent)
 * Q&A 기록: backend → frontend "PATCH 형식?" → "JSON Merge Patch (RFC 7396)"
 */

import { useEffect, useState } from "react";
import { TodoItem } from "./components/TodoItem";
import { fetchTodos, createTodo, patchTodo, deleteTodo, Todo } from "./api";

export default function App() {
  const [todos, setTodos] = useState<Todo[]>([]);
  const [title, setTitle] = useState("");
  const [error, setError] = useState<string>("");

  useEffect(() => {
    fetchTodos()
      .then(setTodos)
      .catch((e: Error) => setError(e.message));
  }, []);

  async function handleAdd() {
    if (!title.trim()) return;
    try {
      const created = await createTodo({ title: title.trim() });
      setTodos((prev) => [created, ...prev]);
      setTitle("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "create failed");
    }
  }

  async function handleToggle(todo: Todo) {
    try {
      const updated = await patchTodo(todo.id, { completed: !todo.completed });
      setTodos((prev) => prev.map((t) => (t.id === todo.id ? updated : t)));
    } catch (e) {
      setError(e instanceof Error ? e.message : "update failed");
    }
  }

  async function handleDelete(todo: Todo) {
    try {
      await deleteTodo(todo.id);
      setTodos((prev) => prev.filter((t) => t.id !== todo.id));
    } catch (e) {
      setError(e instanceof Error ? e.message : "delete failed");
    }
  }

  return (
    <main style={{ maxWidth: 600, margin: "40px auto", padding: 20 }}>
      <h1>📝 Todo</h1>
      {error && <div style={{ color: "red" }}>{error}</div>}
      <div style={{ display: "flex", gap: 8, marginBottom: 20 }}>
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleAdd()}
          placeholder="해야 할 일을 입력하세요"
          style={{ flex: 1, padding: 8 }}
        />
        <button onClick={handleAdd}>추가</button>
      </div>
      <ul style={{ listStyle: "none", padding: 0 }}>
        {todos.map((t) => (
          <TodoItem key={t.id} todo={t} onToggle={handleToggle} onDelete={handleDelete} />
        ))}
      </ul>
    </main>
  );
}
