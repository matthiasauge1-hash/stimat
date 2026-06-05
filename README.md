# Stima — Guide de déploiement

## Structure finale

```
step-analyzer/
├── app/
│   ├── __init__.py
│   ├── analyzer.py
│   ├── pricing.py
│   └── main.py          ← sert aussi index.html via GET /
├── index.html
├── requirements.txt
├── Dockerfile
├── railway.toml
└── README.md
```

---

## Déploiement sur Railway (recommandé)

Railway héberge le tout : API FastAPI + frontend index.html sur la même URL.

### Étape 1 — Créer un compte
👉 https://railway.app (gratuit jusqu'à 500h/mois)

### Étape 2 — Déployer depuis GitHub

1. Crée un repo GitHub avec tous les fichiers du dossier `step-analyzer/`
2. Va sur https://railway.app/new
3. Clique "Deploy from GitHub repo"
4. Sélectionne ton repo
5. Railway détecte le Dockerfile automatiquement et build

### Étape 3 — Générer un domaine public
Railway → Settings → Networking → Generate Domain
Tu obtiens : `https://stima-production.up.railway.app`

### Étape 4 — Tester
Ouvre l'URL → interface Stima directement !

---

## Notes importantes

- Premier build : 10-15 min (CadQuery = ~800MB)
- Plan gratuit : mise en veille après 10 min → réveil ~30 sec
- Plan Hobby 5$/mois pour éviter la veille

## Développement local

```bash
conda activate step-analyzer
cd step-analyzer
uvicorn app.main:app --reload
# Ouvrir http://localhost:8000
```

## Prochaines étapes

- [ ] Nom de domaine personnalisé (stima.app)
- [ ] Export PDF des devis
- [ ] Auth utilisateurs
- [ ] Comparateur multi-pays
