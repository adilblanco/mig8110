import { useState } from 'react';
import axios from 'axios';

function App() {
  const [barcode, setBarcode] = useState(""); // État pour la saisie utilisateur
  const [product, setProduct] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const handleSearch = () => {
    if (!barcode) return;

    setLoading(true);
    setError(null);
    setProduct(null);

    axios.get(`http://localhost:8000/api/products/${barcode}`)
      .then(response => {
        console.log("Données reçues de FastAPI:", response.data);
        setProduct(response.data);
        setLoading(false);
      })
      .catch(err => {
        console.error("Erreur de connexion au Backend:", err);
        setError("Produit non trouvé ou erreur serveur.");
        setLoading(false);
      });
  };

  return (
    <div style={{ padding: '20px', fontFamily: 'Arial, sans-serif' }}>
      <h1>Recherche FoodHealth</h1>
      
      {/* Zone de saisie */}
      <div style={{ marginBottom: '20px' }}>
        <input 
          type="text" 
          placeholder="Saisissez le code-barres..." 
          value={barcode}
          onChange={(e) => setBarcode(e.target.value)}
          style={{ padding: '8px', width: '250px', marginRight: '10px' }}
        />
        <button 
          onClick={handleSearch}
          style={{ padding: '8px 15px', cursor: 'pointer', backgroundColor: '#4CAF50', color: 'white', border: 'none', borderRadius: '4px' }}
        >
          Rechercher
        </button>
      </div>

      <hr />

      {/* Affichage des résultats */}
      {loading && <p>Recherche en cours dans MotherDuck...</p>}
      
      {error && <p style={{ color: 'red' }}>{error}</p>}

      {product ? (
        <div style={{ border: '1px solid #ccc', padding: '15px', borderRadius: '8px', marginTop: '20px', backgroundColor: '#f9f9f9' }}>
          <h2 style={{ marginTop: 0 }}>Résultat :</h2>
          <h3>Produit : {product.name || "Nom non disponible"}</h3>
          <p><strong>Marque :</strong> {product.brand || "Non spécifiée"}</p>
          <p><strong>Catégorie :</strong> {product.category || "Inconnue"}</p>
        </div>
      ) : (
        !loading && !error && <p>Entrez un code pour afficher les détails du produit.</p>
      )}
    </div>
  );
}

export default App;