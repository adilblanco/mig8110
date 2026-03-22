import axios from "axios";

// URL backend depuis .env
const API = axios.create({
  baseURL: import.meta.env.VITE_API_URL,
});

// 🔍 Recherche produit par code
export const fetchProductByCode = (code) =>
  API.get(`/products/${code}`);

// 📊 Détails produit (nutriments + ingrédients)
export const fetchProductDetails = (code) =>
  API.get(`/products/${code}/details`);