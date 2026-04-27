/**
 * TodoItem 컴포넌트 — 단일 항목 렌더링.
 *
 * 생성: T-002 (Frontend agent)
 */

import { Todo } from "../api";

interface Props {
  todo: Todo;
  onToggle: (t: Todo) => void;
  onDelete: (t: Todo) => void;
}

export function TodoItem({ todo, onToggle, onDelete }: Props) {
  return (
    <li
      style={{
        display: "flex",
        alignItems: "center",
        gap: 8,
        padding: 12,
        borderBottom: "1px solid #eee",
        opacity: todo.completed ? 0.5 : 1,
      }}
    >
      <input
        type="checkbox"
        checked={todo.completed}
        onChange={() => onToggle(todo)}
      />
      <span
        style={{
          flex: 1,
          textDecoration: todo.completed ? "line-through" : "none",
        }}
      >
        {todo.title}
      </span>
      <button onClick={() => onDelete(todo)} aria-label="삭제">
        🗑
      </button>
    </li>
  );
}
