from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import product_routes

app = FastAPI()

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
app.include_router(product_routes.router)


@app.get("/")
def root():
    return {"message": "Backend FoodHealth API running"}
