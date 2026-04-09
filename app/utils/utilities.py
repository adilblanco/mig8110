import unicodedata
import re

# Pré‑compilation des regex = beaucoup plus rapide
RE_PUNCT = re.compile(r"[^\w\s]", flags=re.UNICODE)  # toute ponctuation
RE_TRAILING_COMMA = re.compile(r",$")  # virgule en fin de chaîne

class Utilities:
    """
    Les utilitaires 
    """
    def clean_string(texte):

        if not texte:
            return None
        texte = str(texte)

    # 1️⃣ Normalisation Unicode + suppression accents
        texte =  ''.join(c for c in unicodedata.normalize('NFD', texte) if not unicodedata.combining(c))
        
    # 2️⃣ Remplacer toute ponctuation par une virgule
        texte = RE_PUNCT.sub(",", texte)

        # Remplacer les caractères spéciaux par des espaces
        #texte = re.sub(r"[^a-zA-Z0-9&]", " ", texte)

        # Supprimer les espaces multiples et les remplacer par un seul espace
        texte = re.sub(r"\s+", " ", texte).strip()


    # 5️⃣ ❗ Supprimer la virgule finale (si présente)
        texte = RE_TRAILING_COMMA.sub("", texte)

        # Mettre en minuscule
        texte = texte.lower()

    return texte

    

