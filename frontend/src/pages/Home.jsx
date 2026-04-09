import { useState } from "react";
import { fetchProductByCode } from "../api/client";
import ProductList from "../components/ProductList";

export default function Home() {
  const [code, setCode] = useState("");
  const [product, setProduct] = useState(null);

  const handleSearch = async () => {
    try {
      const res = await fetchProductByCode(code);
      setProduct(res.data);
    } catch {
      alert("Produit non trouvé");
    }
  };

  return (
    <div style={{ padding: "20px" }}>
      <h1>Recherche Produit</h1>

      <input
        type="text"
        placeholder="Code produit"
        value={code}
        onChange={(e) => setCode(e.target.value)}
      />

      <button onClick={handleSearch}>Rechercher</button>

      {product && <ProductList product={product} />}
    </div>
  );
}