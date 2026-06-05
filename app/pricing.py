"""
Moteur de devis — Calcul détaillé par procédé et matière
Coûts : matière + machine + main d'oeuvre, avec coefficients par pays

Calibration sur ETRIERA-330-A (440×83×65mm, ~400€ CNC acier France)
"""

from dataclasses import dataclass, field
from app.analyzer import GeometryFeatures


# ─────────────────────────────────────────────
#  Coefficients par pays  (base France = 1.0)
# ─────────────────────────────────────────────

COUNTRIES = {
    "France": {
        "label": "🇫🇷 France",
        "coeff_machine":  1.00,
        "coeff_mdo":      1.00,
        "coeff_matiere":  1.00,
        "note": "Référence — coûts Europe occidentale",
    },
    "Allemagne": {
        "label": "🇩🇪 Allemagne",
        "coeff_machine":  1.10,
        "coeff_mdo":      1.18,
        "coeff_matiere":  0.97,
        "note": "Salaires élevés, excellent sourcing métaux",
    },
    "Pologne": {
        "label": "🇵🇱 Pologne",
        "coeff_machine":  0.72,
        "coeff_mdo":      0.38,
        "coeff_matiere":  0.92,
        "note": "Main d'œuvre très compétitive, forte industrie mécanique",
    },
    "Chine": {
        "label": "🇨🇳 Chine",
        "coeff_machine":  0.55,
        "coeff_mdo":      0.18,
        "coeff_matiere":  0.75,
        "note": "Coûts très bas — ajouter frais logistique et délais import",
    },
}


# ─────────────────────────────────────────────
#  Matières  (prix France de référence)
# ─────────────────────────────────────────────

MATERIALS = {
    "PLA": {
        "procedes": ["Impression 3D FDM"],
        "prix_kg": 20.0, "densite": 1.24,
        "label": "PLA", "categorie": "FDM",
    },
    "PETG": {
        "procedes": ["Impression 3D FDM"],
        "prix_kg": 25.0, "densite": 1.27,
        "label": "PETG", "categorie": "FDM",
    },
    "ABS": {
        "procedes": ["Impression 3D FDM"],
        "prix_kg": 22.0, "densite": 1.05,
        "label": "ABS", "categorie": "FDM",
    },
    "Résine standard": {
        "procedes": ["Impression 3D SLA/Résine"],
        "prix_kg": 50.0, "densite": 1.10,
        "label": "Résine standard", "categorie": "SLA",
    },
    "Résine technique": {
        "procedes": ["Impression 3D SLA/Résine"],
        "prix_kg": 120.0, "densite": 1.15,
        "label": "Résine technique", "categorie": "SLA",
    },
    "Aluminium 6061": {
        "procedes": ["Usinage CNC", "Tôlerie / Pliage", "Découpe laser"],
        "prix_kg": 8.0, "densite": 2.70,
        "label": "Aluminium 6061", "categorie": "Métal",
    },
    "Acier S235": {
        "procedes": ["Usinage CNC", "Tôlerie / Pliage", "Découpe laser"],
        "prix_kg": 2.5, "densite": 7.85,
        "label": "Acier S235", "categorie": "Métal",
    },
    "Inox 316L": {
        "procedes": ["Usinage CNC", "Tôlerie / Pliage", "Découpe laser"],
        "prix_kg": 12.0, "densite": 7.98,
        "label": "Inox 316L", "categorie": "Métal",
    },
}


# ─────────────────────────────────────────────
#  Paramètres machine par procédé  (base France)
#
#  Calibration :  ETRIERA 440×83×65mm → CNC Acier ≈ 400 €
#
#  Ajustements vs v1 :
#  - FDM  : vitesse_cm3_h 15 → 40  (imprimante moderne ~40 cm³/h réel)
#            taux_machine_h  3 → 1.5 (amortissement réel imprimante bureau)
#  - SLA  : vitesse_cm3_h  8 → 12, taux_machine_h  8 → 4
#  - CNC  : taux_machine_h 45 → 40, taux_mdo_h 35 → 30  (ok, proche réalité)
#            vitesse_cm3_h 20 → 25  (fraiseuse moderne plus rapide)
#  - Laser: taux_machine_h 60 → 35  (location laser fibre réaliste)
#  - Tôle : taux_machine_h 50 → 35
# ─────────────────────────────────────────────

PROCESS_PARAMS = {
    "Impression 3D FDM": {
        "taux_machine_h":   1.5,    # €/h  amortissement imprimante
        "taux_mdo_h":       12.0,   # €/h  opérateur (très peu de présence)
        "temps_setup_h":    0.25,   # h    préparation fichier + lancement
        "temps_postprod_h": 0.20,   # h    retrait pièce + supports basiques
        "vitesse_cm3_h":    40.0,   # cm³/h débit volumique réel
        "marge":            1.20,
    },
    "Impression 3D SLA/Résine": {
        "taux_machine_h":   4.0,
        "taux_mdo_h":       15.0,
        "temps_setup_h":    0.5,
        "temps_postprod_h": 0.75,   # lavage + post-cure UV
        "vitesse_cm3_h":    12.0,
        "marge":            1.25,
    },
    "Découpe laser": {
        "taux_machine_h":   35.0,   # laser CO2/fibre location atelier
        "taux_mdo_h":       18.0,
        "temps_setup_h":    0.4,
        "temps_postprod_h": 0.2,
        "vitesse_cm2_min":  80.0,
        "marge":            1.20,
    },
    "Usinage CNC": {
        "taux_machine_h":   40.0,   # fraiseuse 3 axes, amortissement + énergie
        "taux_mdo_h":       30.0,   # opérateur qualifié
        "temps_setup_h":    1.0,    # bridage, zéro pièce, programme
        "temps_postprod_h": 0.4,    # ébavurage, contrôle dimensionnel
        "vitesse_cm3_h":    200.0,   # volume copeaux enlevés / heure
        "marge":            1.30,
    },
    "Tôlerie / Pliage": {
        "taux_machine_h":   35.0,
        "taux_mdo_h":       25.0,
        "temps_setup_h":    0.6,
        "temps_postprod_h": 0.2,
        "vitesse_cm2_min":  60.0,
        "marge":            1.20,
    },
}


# ─────────────────────────────────────────────
#  Structures
# ─────────────────────────────────────────────

@dataclass
class CoutDetail:
    label: str
    montant: float
    detail: str = ""

@dataclass
class DevisResult:
    procede: str
    materiau: str
    pays: str
    quantite: int
    cout_matiere: float
    cout_machine: float
    cout_mdo: float
    cout_total_unitaire: float
    cout_total: float
    temps_fabrication_h: float
    details: list = field(default_factory=list)
    notes: list = field(default_factory=list)


# ─────────────────────────────────────────────
#  Temps de fabrication
# ─────────────────────────────────────────────

def calc_temps_fabrication(procede: str, features: GeometryFeatures) -> float:
    p = PROCESS_PARAMS[procede]
    volume_cm3 = features.volume_mm3 / 1000.0

    if procede in ("Impression 3D FDM", "Impression 3D SLA/Résine"):
        t_fab = volume_cm3 / p["vitesse_cm3_h"]
        if features.estimated_overhang:
            t_fab *= 1.20

    elif procede in ("Découpe laser", "Tôlerie / Pliage"):
        surface_2d = max(
            features.bbox_x * features.bbox_y,
            features.bbox_x * features.bbox_z,
            features.bbox_y * features.bbox_z,
        ) / 100.0  # cm²
        t_fab = surface_2d / p["vitesse_cm2_min"] / 60.0

    elif procede == "Usinage CNC":
        surface_cm2 = features.surface_mm2 / 100.0
        t_fab = surface_cm2 / p["vitesse_cm3_h"]
        if features.has_complex_curves:
            t_fab *= 1.5
        if features.solidity < 0.3:
            t_fab *= 1.2
    else:
        t_fab = 0.5

    return round(max(t_fab, 0.05), 3)


# ─────────────────────────────────────────────
#  Calcul devis unitaire
# ─────────────────────────────────────────────

def calc_devis(
    procede: str,
    materiau_key: str,
    features: GeometryFeatures,
    quantite: int = 1,
    pays: str = "France",
) -> DevisResult:

    mat     = MATERIALS[materiau_key]
    p       = PROCESS_PARAMS[procede]
    country = COUNTRIES.get(pays, COUNTRIES["France"])
    details, notes = [], []

    taux_machine = p["taux_machine_h"] * country["coeff_machine"]
    taux_mdo     = p["taux_mdo_h"]     * country["coeff_mdo"]
    prix_mat_kg  = mat["prix_kg"]       * country["coeff_matiere"]

    volume_cm3       = features.volume_mm3 / 1000.0
    masse_kg         = volume_cm3 * mat["densite"] / 1000.0

    # Pertes matière
    if procede == "Usinage CNC":
        coeff_perte = 3.5
    elif procede in ("Découpe laser", "Tôlerie / Pliage"):
        coeff_perte = 1.3
    elif procede == "Impression 3D FDM":
        coeff_perte = 1.1 + (0.15 if features.estimated_overhang else 0)
    else:
        coeff_perte = 1.05

    masse_achetee_kg = masse_kg * coeff_perte
    cout_matiere     = masse_achetee_kg * prix_mat_kg

    details.append(CoutDetail(
        label="Matière",
        montant=round(cout_matiere, 2),
        detail=f"{masse_achetee_kg*1000:.1f} g × {prix_mat_kg:.2f} €/kg (perte ×{coeff_perte:.1f}, coeff pays ×{country['coeff_matiere']})",
    ))

    if procede == "Usinage CNC":
        notes.append("Perte matière élevée (×3.5) : usinage enlève ~70% du brut")
    if features.estimated_overhang and procede == "Impression 3D FDM":
        notes.append("Surplombs détectés : supports inclus (+15%)")
    if pays == "Chine":
        notes.append("⚠ Prévoir +300–1500 € de frais logistique et 4–8 semaines de délai")

    t_fab            = calc_temps_fabrication(procede, features)
    t_setup_unitaire = p["temps_setup_h"] / quantite

    cout_machine = (t_fab + t_setup_unitaire + p["temps_postprod_h"]) * taux_machine
    details.append(CoutDetail(
        label="Machine",
        montant=round(cout_machine, 2),
        detail=f"{t_fab:.2f}h fab + {t_setup_unitaire:.2f}h setup + {p['temps_postprod_h']:.2f}h finition × {taux_machine:.1f} €/h (×{country['coeff_machine']})",
    ))

    cout_mdo = (t_setup_unitaire + p["temps_postprod_h"]) * taux_mdo
    details.append(CoutDetail(
        label="Main d'œuvre",
        montant=round(cout_mdo, 2),
        detail=f"{t_setup_unitaire:.2f}h setup + {p['temps_postprod_h']:.2f}h finition × {taux_mdo:.1f} €/h (×{country['coeff_mdo']})",
    ))

    sous_total          = cout_matiere + cout_machine + cout_mdo
    cout_total_unitaire = round(sous_total * p["marge"], 2)
    cout_total          = round(cout_total_unitaire * quantite, 2)

    details.append(CoutDetail(
        label=f"Marge ({int((p['marge']-1)*100)}%)",
        montant=round(sous_total * (p["marge"] - 1), 2),
        detail="Frais généraux, bénéfice atelier",
    ))

    if quantite > 1:
        notes.append(f"Setup partagé sur {quantite} pièces → économie d'échelle appliquée")
    if features.has_thin_walls and procede == "Usinage CNC":
        notes.append("⚠ Parois fines : risque vibration, coût réel peut augmenter")

    return DevisResult(
        procede=procede, materiau=mat["label"], pays=pays, quantite=quantite,
        cout_matiere=round(cout_matiere, 2), cout_machine=round(cout_machine, 2),
        cout_mdo=round(cout_mdo, 2), cout_total_unitaire=cout_total_unitaire,
        cout_total=cout_total, temps_fabrication_h=round(t_fab, 2),
        details=details, notes=notes,
    )


# ─────────────────────────────────────────────
#  Calcul complet
# ─────────────────────────────────────────────

def calc_devis_complet(features: GeometryFeatures, quantite: int = 1, pays: str = "France") -> dict:
    resultats = {}
    for procede in PROCESS_PARAMS:
        matieres = [k for k, m in MATERIALS.items() if procede in m["procedes"]]
        devis_procede = []
        for mat_key in matieres:
            try:
                devis_procede.append(calc_devis(procede, mat_key, features, quantite, pays))
            except Exception:
                pass
        if devis_procede:
            resultats[procede] = devis_procede
    return resultats


# ─────────────────────────────────────────────
#  Moteur de délais de fabrication
#  Délai total = fab + file d'attente + post-traitement + livraison
#  Tout en jours ouvrés
# ─────────────────────────────────────────────

DELAIS_BASE = {
    "Impression 3D FDM": {
        "file_attente_j":   1,    # atelier rarement surchargé
        "postprod_j":       1,    # retrait supports, ponçage léger
        "livraison_fr_j":   2,
        "label_postprod":   "Retrait supports + nettoyage",
    },
    "Impression 3D SLA/Résine": {
        "file_attente_j":   2,
        "postprod_j":       2,    # lavage IPA + post-cure UV + séchage
        "livraison_fr_j":   2,
        "label_postprod":   "Lavage IPA + post-cure UV",
    },
    "Découpe laser": {
        "file_attente_j":   2,
        "postprod_j":       1,    # ébavurage, nettoyage
        "livraison_fr_j":   2,
        "label_postprod":   "Ébavurage + nettoyage",
    },
    "Usinage CNC": {
        "file_attente_j":   5,    # programmation + planning atelier
        "postprod_j":       2,    # ébavurage, contrôle dimensionnel, traitement surface optionnel
        "livraison_fr_j":   2,
        "label_postprod":   "Ébavurage + contrôle dimensionnel",
    },
    "Tôlerie / Pliage": {
        "file_attente_j":   3,
        "postprod_j":       1,
        "livraison_fr_j":   2,
        "label_postprod":   "Ébavurage + redressage",
    },
}

# Coefficients délai par pays
# Impacte la file d'attente et la livraison (pas le temps de fab)
DELAIS_PAYS = {
    "France":    { "coeff_attente": 1.0, "livraison_j": 2,  "douane_j": 0 },
    "Allemagne": { "coeff_attente": 0.9, "livraison_j": 3,  "douane_j": 0 },
    "Pologne":   { "coeff_attente": 0.8, "livraison_j": 5,  "douane_j": 0 },
    "Chine":     { "coeff_attente": 0.5, "livraison_j": 25, "douane_j": 5 },
}


@dataclass
class DelaiResult:
    procede: str
    pays: str
    temps_fab_h: float          # heures de fabrication pure
    file_attente_j: float       # jours ouvrés d'attente atelier
    postprod_j: float           # jours post-traitement
    livraison_j: float          # jours livraison
    douane_j: float             # jours dédouanement
    total_j: float              # total jours ouvrés
    total_semaines: float       # arrondi en semaines
    label_postprod: str
    urgence_possible: bool      # express possible ?
    urgence_surcoût_pct: int    # surcoût express en %
    breakdown: list = field(default_factory=list)  # détail affichable


def calc_delai(
    procede: str,
    features,
    pays: str = "France",
    quantite: int = 1,
) -> DelaiResult:
    base   = DELAIS_BASE[procede]
    cpays  = DELAIS_PAYS.get(pays, DELAIS_PAYS["France"])
    params = PROCESS_PARAMS[procede]

    # Temps fab en heures → converti en jours ouvrés (7h/jour)
    t_fab_h   = calc_temps_fabrication(procede, features)
    t_fab_h  *= quantite  # séquentiel pour simplifier
    t_fab_j   = round(t_fab_h / 7, 2)

    # File d'attente ajustée par pays et quantité
    attente = base["file_attente_j"] * cpays["coeff_attente"]
    if quantite > 10:
        attente *= 1.5   # grosse série = plus long à planifier
    if quantite > 100:
        attente *= 2.0

    postprod = base["postprod_j"]
    if quantite > 1:
        postprod += round(quantite * 0.02, 1)  # léger scaling postprod

    livraison = cpays["livraison_j"]
    douane    = cpays["douane_j"]

    total = round(t_fab_j + attente + postprod + livraison + douane, 1)
    semaines = round(total / 5, 1)

    # Express possible seulement pour impression 3D et découpe laser
    urgence_possible   = procede in ("Impression 3D FDM", "Impression 3D SLA/Résine", "Découpe laser")
    urgence_surcoût    = 60 if procede == "Usinage CNC" else 35

    breakdown = [
        {"label": "Fabrication",       "valeur": round(t_fab_j, 1),  "unite": "j",  "color": "#00d4ff"},
        {"label": "File d'attente",    "valeur": round(attente, 1),   "unite": "j",  "color": "#a78bfa"},
        {"label": base["label_postprod"], "valeur": round(postprod,1),"unite": "j",  "color": "#ff8c00"},
        {"label": "Livraison",         "valeur": livraison,           "unite": "j",  "color": "#00ff88"},
    ]
    if douane > 0:
        breakdown.append({"label": "Dédouanement", "valeur": douane, "unite": "j", "color": "#ff3a3a"})

    return DelaiResult(
        procede=procede, pays=pays,
        temps_fab_h=round(t_fab_h, 2),
        file_attente_j=round(attente, 1),
        postprod_j=round(postprod, 1),
        livraison_j=livraison,
        douane_j=douane,
        total_j=total,
        total_semaines=semaines,
        label_postprod=base["label_postprod"],
        urgence_possible=urgence_possible,
        urgence_surcoût_pct=urgence_surcoût,
        breakdown=breakdown,
    )


def calc_delais_complet(features, quantite: int = 1, pays: str = "France") -> dict:
    return {
        procede: calc_delai(procede, features, pays, quantite)
        for procede in PROCESS_PARAMS
    }


# ─────────────────────────────────────────────
#  Tolérance & Finition
#  Impact sur : coût machine, délai, compatibilité procédé
# ─────────────────────────────────────────────

# Rugosité Ra — impact sur temps machine et coût
RUGOSITES = {
    "Ra 0.8":  { "label": "Ra 0.8 µm — Rectifié/poli miroir", "coeff_machine": 2.2, "coeff_delai": 1.4, "procedes_ok": ["Usinage CNC"], "note": "Rectification ou polissage manuel requis" },
    "Ra 1.6":  { "label": "Ra 1.6 µm — Finition soignée",     "coeff_machine": 1.5, "coeff_delai": 1.2, "procedes_ok": ["Usinage CNC", "Impression 3D SLA/Résine"], "note": "Passes de finition supplémentaires" },
    "Ra 3.2":  { "label": "Ra 3.2 µm — Standard usiné",       "coeff_machine": 1.0, "coeff_delai": 1.0, "procedes_ok": ["Usinage CNC", "Découpe laser", "Tôlerie / Pliage", "Impression 3D SLA/Résine"], "note": "Standard atelier" },
    "Ra 6.3":  { "label": "Ra 6.3 µm — Brut d'usinage",       "coeff_machine": 0.85,"coeff_delai": 0.9, "procedes_ok": ["Usinage CNC", "Découpe laser", "Tôlerie / Pliage", "Impression 3D FDM", "Impression 3D SLA/Résine"], "note": "Pas de finition spéciale" },
    "Aucune":  { "label": "Aucune exigence",                   "coeff_machine": 1.0, "coeff_delai": 1.0, "procedes_ok": ["Usinage CNC", "Découpe laser", "Tôlerie / Pliage", "Impression 3D FDM", "Impression 3D SLA/Résine"], "note": "" },
}

# Classes de tolérance ISO — impact sur temps machine
TOLERANCES_ISO = {
    "IT6":  { "label": "IT6 — Précision élevée (±0.01mm)",   "coeff_machine": 2.0, "coeff_delai": 1.5, "procedes_ok": ["Usinage CNC"], "note": "Métrologie obligatoire, machines de précision" },
    "IT7":  { "label": "IT7 — Bonne précision (±0.02mm)",    "coeff_machine": 1.4, "coeff_delai": 1.2, "procedes_ok": ["Usinage CNC"], "note": "Contrôle dimensionnel systématique" },
    "IT8":  { "label": "IT8 — Précision courante (±0.05mm)", "coeff_machine": 1.0, "coeff_delai": 1.0, "procedes_ok": ["Usinage CNC", "Découpe laser", "Tôlerie / Pliage"], "note": "Standard atelier CNC" },
    "IT11": { "label": "IT11 — Précision libre (±0.2mm)",    "coeff_machine": 0.9, "coeff_delai": 0.9, "procedes_ok": ["Usinage CNC", "Découpe laser", "Tôlerie / Pliage", "Impression 3D FDM", "Impression 3D SLA/Résine"], "note": "Tolérance générale, pas de contrôle spécifique" },
    "Libre":{ "label": "Libre — Pas d'exigence dimensionnelle","coeff_machine": 1.0, "coeff_delai": 1.0, "procedes_ok": ["Usinage CNC", "Découpe laser", "Tôlerie / Pliage", "Impression 3D FDM", "Impression 3D SLA/Résine"], "note": "" },
}

# Traitements de surface — coût fixe (€) + coût/cm² + compatibilité matières
TRAITEMENTS = {
    "Aucun": {
        "label": "Aucun traitement",
        "cout_fixe": 0, "cout_cm2": 0,
        "delai_j": 0,
        "matieres_ok": ["*"],
        "procedes_ok": ["*"],
        "note": "",
    },
    "Anodisation": {
        "label": "Anodisation (type II)",
        "cout_fixe": 40.0,   # frais de bain minimum
        "cout_cm2":  0.08,   # €/cm²
        "delai_j":   3,
        "matieres_ok": ["Aluminium 6061"],
        "procedes_ok": ["Usinage CNC", "Découpe laser", "Tôlerie / Pliage"],
        "note": "Uniquement sur aluminium — protection + esthétique",
    },
    "Anodisation dure": {
        "label": "Anodisation dure (type III)",
        "cout_fixe": 65.0,
        "cout_cm2":  0.15,
        "delai_j":   4,
        "matieres_ok": ["Aluminium 6061"],
        "procedes_ok": ["Usinage CNC"],
        "note": "Dureté élevée, résistance usure — pièces mécaniques",
    },
    "Zingage": {
        "label": "Zingage électrolytique",
        "cout_fixe": 35.0,
        "cout_cm2":  0.06,
        "delai_j":   3,
        "matieres_ok": ["Acier S235"],
        "procedes_ok": ["Usinage CNC", "Découpe laser", "Tôlerie / Pliage"],
        "note": "Protection anticorrosion acier",
    },
    "Peinture": {
        "label": "Peinture / thermolaquage",
        "cout_fixe": 50.0,
        "cout_cm2":  0.10,
        "delai_j":   4,
        "matieres_ok": ["Aluminium 6061", "Acier S235", "Inox 316L"],
        "procedes_ok": ["Usinage CNC", "Découpe laser", "Tôlerie / Pliage"],
        "note": "RAL au choix — protection + esthétique",
    },
    "Passivation": {
        "label": "Passivation (inox)",
        "cout_fixe": 30.0,
        "cout_cm2":  0.04,
        "delai_j":   2,
        "matieres_ok": ["Inox 316L"],
        "procedes_ok": ["Usinage CNC", "Tôlerie / Pliage"],
        "note": "Renforce la résistance à la corrosion de l'inox",
    },
    "Sablage": {
        "label": "Sablage / grenaillage",
        "cout_fixe": 25.0,
        "cout_cm2":  0.05,
        "delai_j":   1,
        "matieres_ok": ["Aluminium 6061", "Acier S235", "Inox 316L"],
        "procedes_ok": ["Usinage CNC", "Découpe laser", "Tôlerie / Pliage", "Impression 3D SLA/Résine"],
        "note": "Finition mate uniforme, prépare à la peinture",
    },
}


@dataclass
class FinitionConfig:
    """Configuration tolérance + finition choisie par l'utilisateur."""
    rugosite:    str = "Aucune"
    tolerance:   str = "Libre"
    traitement:  str = "Aucun"


@dataclass
class FinitionImpact:
    """Impact calculé de la config finition sur un devis."""
    compatible:         bool
    incompatibilites:   list
    surcoût_machine:    float
    surcoût_traitement: float
    surcoût_total:      float
    delai_extra_j:      float
    lignes_devis:       list   # lignes détaillées à ajouter au devis
    notes:              list


def calc_finition_impact(
    procede: str,
    materiau_key: str,
    features,
    config: FinitionConfig,
    cout_base: float,
    pays: str = "France",
) -> FinitionImpact:
    """
    Calcule l'impact d'une config tolérance/finition sur le devis.
    """
    mat      = MATERIALS[materiau_key]
    rug      = RUGOSITES[config.rugosite]
    tol      = TOLERANCES_ISO[config.tolerance]
    trait    = TRAITEMENTS[config.traitement]
    country  = COUNTRIES.get(pays, COUNTRIES["France"])

    incompatibilites = []
    lignes_devis     = []
    notes            = []

    # ── Vérification compatibilité ──
    if procede not in rug["procedes_ok"]:
        incompatibilites.append(f"Rugosité {config.rugosite} non atteignable en {procede}")
    if procede not in tol["procedes_ok"]:
        incompatibilites.append(f"Tolérance {config.tolerance} non atteignable en {procede}")
    if trait["matieres_ok"] != ["*"] and mat["label"] not in trait["matieres_ok"]:
        incompatibilites.append(f"Traitement '{config.traitement}' incompatible avec {mat['label']}")
    if trait["procedes_ok"] != ["*"] and procede not in trait["procedes_ok"]:
        incompatibilites.append(f"Traitement '{config.traitement}' incompatible avec {procede}")

    compatible = len(incompatibilites) == 0

    # ── Surcoût machine (tolérance + rugosité) ──
    coeff_machine = rug["coeff_machine"] * tol["coeff_machine"]
    surcoût_machine = 0.0
    if coeff_machine != 1.0 and compatible:
        # Appliqué uniquement sur le coût machine (pas matière)
        surcoût_machine = round(cout_base * (coeff_machine - 1.0) * 0.6, 2)
        if config.rugosite != "Aucune":
            lignes_devis.append({
                "label":  f"Rugosité {config.rugosite}",
                "montant": round(surcoût_machine * 0.5, 2),
                "detail": f"Passes finition supplémentaires (×{rug['coeff_machine']})",
            })
            if rug["note"]: notes.append(rug["note"])
        if config.tolerance != "Libre":
            lignes_devis.append({
                "label":  f"Tolérance {config.tolerance}",
                "montant": round(surcoût_machine * 0.5, 2),
                "detail": f"Contrôle dimensionnel renforcé (×{tol['coeff_machine']})",
            })
            if tol["note"]: notes.append(tol["note"])

    # ── Surcoût traitement de surface ──
    surcoût_traitement = 0.0
    if config.traitement != "Aucun" and compatible:
        surface_cm2 = features.surface_mm2 / 100.0
        cout_trait  = trait["cout_fixe"] + trait["cout_cm2"] * surface_cm2
        cout_trait  *= country["coeff_machine"]   # coût main d'œuvre local
        surcoût_traitement = round(cout_trait, 2)
        lignes_devis.append({
            "label":  trait["label"],
            "montant": surcoût_traitement,
            "detail": f"Fixe {trait['cout_fixe']}€ + {surface_cm2:.0f}cm² × {trait['cout_cm2']}€/cm² (coeff pays ×{country['coeff_machine']})",
        })
        if trait["note"]: notes.append(trait["note"])

    surcoût_total = round(surcoût_machine + surcoût_traitement, 2)

    # ── Délai extra ──
    delai_extra = 0.0
    if compatible:
        delai_extra = round(
            trait["delai_j"] +
            (1.5 if rug["coeff_delai"] > 1.0 else 0) +
            (1.0 if tol["coeff_delai"] > 1.0 else 0),
            1
        )

    return FinitionImpact(
        compatible=compatible,
        incompatibilites=incompatibilites,
        surcoût_machine=surcoût_machine,
        surcoût_traitement=surcoût_traitement,
        surcoût_total=surcoût_total,
        delai_extra_j=delai_extra,
        lignes_devis=lignes_devis,
        notes=notes,
    )
