# app/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import products
from app.api import product_routes
from app.db import get_connection


app = FastAPI(
    title="OFF Canada API",
    description="API pour explorer les produits alimentaires canadiens",
    version="1.0.0"
)

# 🌐 CORS configuration pour autoriser le frontend React
origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,   # autorise le frontend
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 🔗 inclusion des routes
app.include_router(products.router, prefix="/api")

@app.get("/health", tags=["health"])
def health():
    db = get_connection ()
    db.execute("SELECT 1")
    return {"status": "ok"}

