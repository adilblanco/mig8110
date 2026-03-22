import { useNavigate } from "react-router-dom";

export default function ProductList({ product }) {
  const navigate = useNavigate();

  return (
    <div style={{ marginTop: "20px" }}>
      <h2>Résultat</h2>

      <p><strong>Nom :</strong> {product.name}</p>
      <p><strong>Marque :</strong> {product.brand}</p>

      <button onClick={() => navigate(`/product/${product.code}`)}>
        Voir détail produit
      </button>
    </div>
  );
}