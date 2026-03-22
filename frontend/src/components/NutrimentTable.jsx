import { useEffect, useState } from "react";
import { fetchProductDetails } from "../api/client";

// Page détail produit
export default function NutrimentTable({ productCode, onBack }) {
  const [details, setDetails] = useState(null);

  // Charger les détails au montage
  useEffect(() => {
    const loadDetails = async () => {
      const res = await fetchProductDetails(productCode);
      setDetails(res.data);
    };

    loadDetails();
  }, [productCode]);

  if (!details) return <p>Chargement...</p>;

  return (
    <div style={{ padding: "20px" }}>
      <button onClick={onBack}>⬅ Retour</button>

      <h2>Détails du produit</h2>

      {/* Ingrédients */}
      <h3>Ingrédients</h3>
      <ul>
        {details.ingredients.map((ing, index) => (
          <li key={index}>{ing}</li>
        ))}
      </ul>

      {/* Nutriments */}
      <h3>Nutriments</h3>
      <table border="1">
        <thead>
          <tr>
            <th>Nom</th>
            <th>Valeur</th>
          </tr>
        </thead>
        <tbody>
          {details.nutrients.map((n, index) => (
            <tr key={index}>
              <td>{n.name}</td>
              <td>{n.value}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}