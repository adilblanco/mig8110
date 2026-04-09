import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { fetchProductDetails } from "../api/client";

export default function ProductDetails() {
  const { code } = useParams(); // récupérer code URL
  const navigate = useNavigate();

  const [details, setDetails] = useState(null);

  useEffect(() => {
    const load = async () => {
      const res = await fetchProductDetails(code);
      setDetails(res.data);
    };

    load();
  }, [code]);

  if (!details) return <p>Chargement...</p>;

  return (
    <div style={{ padding: "20px" }}>
      <button onClick={() => navigate("/")}>⬅ Retour</button>

      <h2>Détails du produit</h2>

      <h3>Ingrédients</h3>
      <ul>
        {details.ingredients.map((ing, i) => (
          <li key={i}>{ing}</li>
        ))}
      </ul>

      <h3>Nutriments</h3>
      <table border="1">
        <thead>
          <tr>
            <th>Nom</th>
            <th>Valeur</th>
          </tr>
        </thead>
        <tbody>
          {details.nutrients.map((n, i) => (
            <tr key={i}>
              <td>{n.name}</td>
              <td>{n.value}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}