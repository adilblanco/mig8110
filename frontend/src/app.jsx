import React, { useState, useEffect } from "react";
import { fetchJSON } from "./api/client";
import ProductList from "./components/ProductList";
import NutrimentTable from "./components/NutrimentTable";

export default function App() {
  const [query, setQuery] = useState("");
  const [products, setProducts] = useState([]);
  const [selected, setSelected] = useState(null);
  const [per, setPer] = useState("serving");
  const [nutriments, setNutriments] = useState(null);
  const [loadingSearch, setLoadingSearch] = useState(false);
  const [loadingNutriments, setLoadingNutriments] = useState(false);
  const [error, setError] = useState("");

  const search = async (e) => {
    e?.preventDefault();
    if (!query.trim()) return;
    setLoadingSearch(true);
    setError("");
    setProducts([]);
    setSelected(null);
    setNutriments(null);

    try {
      const data = await fetchJSON(`/products?name=${encodeURIComponent(query)}&limit=20&offset=0`);
      setProducts(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoadingSearch(false);
    }
  };

  const loadNutriments = async (productId, perValue = per) => {
    setLoadingNutriments(true);
    setError("");
    setNutriments(null);

    try {
      const data = await fetchJSON(`/products/${productId}/nutriments?per=${encodeURIComponent(perValue)}`);
      setNutriments(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoadingNutriments(false);
    }
  };

  const onSelectProduct = async (p) => {
    setSelected(p);
    await loadNutriments(p.id, per);
  };

  useEffect(() => {
    if (selected) {
      loadNutriments(selected.id, per);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [per]);

  return (
    <div style={{ maxWidth: 980, margin: "0 auto", padding: 24, fontFamily: "system-ui, sans-serif" }}>
      <h1 style={{ marginBottom: 8 }}>FoodHealth</h1>
      <p style={{ marginTop: 0, color: "#555" }}>Recherchez un produit et affichez ses nutriments.</p>

      <form onSubmit={search} style={{ display: "flex", gap: 8, marginBottom: 16 }}>
        <input
          type="text"
          placeholder="Ex: cola"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          style={{ flex: 1, padding: 10, fontSize: 16 }}
        />
        <button type="submit" style={{ padding: "10px 16px" }}>
          {loadingSearch ? "Recherche..." : "Rechercher"}
        </button>
      </form>

      {error && <div style={{ background: "#fdecea", color: "#611a15", padding: 12, borderRadius: 6, marginBottom: 12 }}>{error}</div>}

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
        <div>
          <h2 style={{ marginTop: 0 }}>Résultats</h2>
          {!loadingSearch && products.length === 0 && <div>Aucun résultat pour l’instant.</div>}
          <ProductList products={products} selectedId={selected?.id} onSelect={onSelectProduct} />
        </div>

        <div>
          <h2 style={{ marginTop: 0 }}>Nutriments</h2>
          {!selected && <div>Sélectionnez un produit à gauche.</div>}

          {selected && (
            <>
              <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 12 }}>
                <strong>{selected.name}</strong>
                <span style={{ color: "#666" }}>
                  ({selected.brand || "Sans marque"})
                </span>
                <div style={{ marginLeft: "auto" }}>
                  <label htmlFor="per" style={{ marginRight: 8 }}>Base :</label>
                  <select id="per" value={per} onChange={(e) => setPer(e.target.value)} style={{ padding: 6 }}>
                    <option value="serving">Par portion</option>
                    <option value="100g">Pour 100 g</option>
                    <option value="package">Par emballage</option>
                  </select>
                </div>
              </div>

              {loadingNutriments && <div>Chargement des nutriments...</div>}
              {!loadingNutriments && nutriments && <NutrimentTable data={nutriments} />}
            </>
          )}
        </div>
      </div>
    </div>
  );
}