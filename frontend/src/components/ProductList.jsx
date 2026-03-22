// Affiche le résultat de recherche

export default function ProductList({ product, onViewDetails }) {
  return (
    <div style={{ marginTop: "20px" }}>
      <h2>Résultat</h2>

      <p><strong>Nom :</strong> {product.name}</p>
      <p><strong>Marque :</strong> {product.brand}</p>

      <button onClick={onViewDetails}>
        Voir détail produit
      </button>
    </div>
  );
}