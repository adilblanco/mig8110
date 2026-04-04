FROM python:3.11-slim

# Installation des dépendances système nécessaires
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Répertoire de travail
WORKDIR /app

# Copie des fichiers de dépendances
COPY Pipfile Pipfile.lock ./

# Python cherchera les modules à partir de /app
ENV PYTHONPATH="/app"

# Chemin local de la taxonomie OFF
ENV OFF_INGREDIENTS_TAXONOMY_PATH="/app/resources/ingredients.txt"

# Installation des dépendances Python
RUN pip install --no-cache-dir pipenv
RUN pipenv requirements > requirements.txt
RUN pipenv requirements --dev > requirements-dev.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copie du projet
COPY . ./

# Commande par défaut
ENTRYPOINT ["python", "run.py"]