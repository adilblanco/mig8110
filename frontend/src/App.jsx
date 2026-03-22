import { useState } from "react";
import { fetchProductByCode } from "./api/client";
import ProductList from "./components/ProductList";
import NutrimentTable from "./components/NutrimentTable";

export default function App() {
  const [code, setCode] = useState("");
  const [product, setProduct] = useState(null);
  const [viewDetails, setViewDetails] = useState(false);

  // 🔍 Recherche produit
  const handleSearch = async () => {
    try {
      const res = await fetchProductByCode(code);
      setProduct(res.data);
      setViewDetails(false);
    } catch (err) {
      alert("Produit non trouvé");
    }
  };

  // 📄 Voir détail
  if (viewDetails && product) {
    return (
      <NutrimentTable
        productCode={product.code}
        onBack={() => setViewDetails(false)}
      />
    );
  }

  return (
    <div style={{ padding: "20px" }}>
      <h1>Recherche Produit</h1>

      {/* Champ de recherche */}
      <input
        type="text"
        placeholder="Code produit"
        value={code}
        onChange={(e) => setCode(e.target.value)}
      />

      <button onClick={handleSearch}>Rechercher</button>

      {/* Résultat */}
      {product && (
        <ProductList
          product={product}
          onViewDetails={() => setViewDetails(true)}
        />
      )}
    </div>
  );
}