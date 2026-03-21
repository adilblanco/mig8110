import React from "react";

export default function NutrimentTable({ data }) {
  if (!data) return null;

  return (
    <div>
      {data.serving_size && (
        <div style={{ color: "#666", fontSize: 14, marginBottom: 6 }}>
          Taille de portion: {data.serving_size}
        </div>
      )}
      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead>
          <tr>
            <th style={th}>Nutriment</th>
            <th style={th}>Valeur</th>
            <th style={th}>Unité</th>
          </tr>
        </thead>
        <tbody>
          {data.nutriments.map((n) => (
            <tr key={n.code}>
              <td style={td}>{n.label}</td>
              <td style={td}>{n.value}</td>
              <td style={td}>{n.unit}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const th = { textAlign: "left", borderBottom: "1px solid #ddd", padding: "8px 6px" };
const td = { borderBottom: "1px solid #f2f2f2", padding: "8px 6px" };