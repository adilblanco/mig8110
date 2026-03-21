import React from "react";

export default function ProductList({ products, selectedId, onSelect }) {
  return (
    <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
      {products.map((p) => (
        <li
          key={p.id}
          style={{
            padding: 12,
            border: "1px solid #ddd",
            borderRadius: 8,
            marginBottom: 8,
            cursor: "pointer",
            background: selectedId === p.id ? "#f0f7ff" : "#fff",
          }}
          onClick={() => onSelect(p)}
        >
          <div style={{ fontWeight: 600 }}>{p.name}</div>
          <div style={{ color: "#666", fontSize: 14 }}>
            {p.brand || "Sans marque"} · {p.category || "Catégorie inconnue"}
          </div>
          {p.serving_size && (
            <div style={{ color: "#666", fontSize: 12 }}>
              Portion: {p.serving_size}
            </div>
          )}
        </li>
      ))}
    </ul>
  );
}