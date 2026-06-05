"""
Moteur de devis — Calcul détaillé par procédé et matière
Sources & calibration 2025-2026 :
  - CNC France : hdproto.com, waykenrm, xometry.pro → 45–95€/h tout inclus, médiane 65€
  - FDM : sinterit.com, galaxy3d.fr → 1.5–5€/h machine, débit 30–60 cm³/h
  - SLA : sculpteo.com, 3dkfactory.com → 4–12€/h, débit 8–15 cm³/h
  - Laser fibre métal : 80–150€/h machine industrielle
  - Tôlerie : dampere.fr, yunik-deco → 40–70€/h + 5–8€/pli
  - Matières : inox 316L 4–8€/kg, alu 6061 6–12€/kg, acier S235 1.5–3€/kg (France 2025-2026)
  - Calibration ETRIERA 440×83×65mm acier S235 → cible 400€ → obtenu 399€ ✅
"""

from dataclasses import dataclass, field
from app.analyzer import GeometryFeatures


# ─────────────────────────────────────────────
#  Coefficients par pays  (base France = 1.0)
# ─────────────────────────────────────────────

COUNTRIES = {
    "France": {
        "label": "🇫🇷 France",
        "coeff_machine": 1.00,
        "coeff_mdo":     1.00,
        "coeff_matiere": 1.00,
        "note": "Référence — coûts Europe occidentale",
    },
    "Allemagne": {
        "label": "🇩🇪 Allemagne",
        "coeff_machine": 1.10,
        "coeff_mdo":     1.18,
        "coeff_matiere": 0.97,
        "note": "Salaires élevés, excellent sourcing métaux",
    },
    "Pologne": {
        "label": "🇵🇱 Pologne",
        "coeff_machine": 0.72,
        "coeff_mdo":     0.38,
        "coeff_matiere": 0.92,
        "note": "Main d'œuvre très compétitive, forte industrie mécanique",
    },
    "Chine": {
        "label": "🇨🇳 Chine",
        "coeff_machine": 0.55,
        "coeff_mdo":     0.18,
        "coeff_matiere": 0.75,
        "note": "Coûts très bas — ajouter frais logistique et délais import",
    },
}


# ─────────────────────────────────────────────
#  Matières premières  (prix France 2025-2026)
# ─────────────────────────────────────────────

MATERIALS = {
    "PLA": {
        "procedes": ["Impression 3D FDM"],
        "prix_kg": 20.0,    # 15–25€/kg filament PLA service bureau
        "densite": 1.24,
        "label": "PLA", "categorie": "FDM",
    },
    "PETG": {
        "procedes": ["Impression 3D FDM"],
        "prix_kg": 25.0,
        "densite": 1.27,
        "label": "PETG", "categorie": "FDM",
    },
    "ABS": {
        "procedes": ["Impression 3D FDM"],
        "prix_kg": 22.0,
        "densite": 1.05,
        "label": "ABS", "categorie": "FDM",
    },
    "Résine standard": {
        "procedes": ["Impression 3D SLA/Résine"],
        "prix_kg": 50.0,    # 40–60€/kg résine standard SLA
        "densite": 1.10,
        "label": "Résine standard", "categorie": "SLA",
    },
    "Résine technique": {
        "procedes": ["Impression 3D SLA/Résine"],
        "prix_kg": 120.0,   # 80–150€/kg résine technique (ABS-like, résistance thermique)
        "densite": 1.15,
        "label": "Résine technique", "categorie": "SLA",
    },
    "Aluminium 6061": {
        "procedes": ["Usinage CNC", "Tôlerie / Pliage", "Découpe laser"],
        "prix_kg": 9.0,     # 6–12€/kg alu 6061 barres/tôles distribution France 2025
        "densite": 2.70,
        "label": "Aluminium 6061", "categorie": "Métal",
    },
    "Acier S235": {
        "procedes": ["Usinage CNC", "Tôlerie / Pliage", "Découpe laser"],
        "prix_kg": 2.2,     # 1.5–3€/kg acier S235 distribution France 2025
        "densite": 7.85,
        "label": "Acier S235", "categorie": "Métal",
    },
    "Inox 316L": {
        "procedes": ["Usinage CNC", "Tôlerie / Pliage", "Découpe laser"],
        "prix_kg": 6.0,     # 4–8€/kg inox 316L tôles/barres France 2026
        "densite": 7.98,
        "label": "Inox 316L", "categorie": "Métal",
    },
}


# ─────────────────────────────────────────────
#  Paramètres process  (base France, calibrés 2025-2026)
#
#  CNC : modèle taux tout-inclus (machine + MdO + énergie + outillage)
#        calibré sur ETRIERA 440×83×65mm acier S235 → 399€ ✅
#  Autres : taux machine + MdO séparés
# ─────────────────────────────────────────────

PROCESS_PARAMS = {
    "Impression 3D FDM": {
        "taux_machine_h":   2.5,    # €/h amortissement + énergie imprimante (1.5–5€)
        "taux_mdo_h":       12.0,   # €/h opérateur (présence ~15min/h en pratique)
        "temps_setup_h":    0.25,   # h   slicing + lancement + vérification départ
        "temps_postprod_h": 0.20,   # h   retrait pièce + supports
        "vitesse_cm3_h":    40.0,   # cm³/h débit volumique réel imprimante moderne
        "marge":            1.20,
        "mdo_inclus":       False,
    },
    "Impression 3D SLA/Résine": {
        "taux_machine_h":   6.0,    # €/h imprimante résine pro (Form3+, Phrozen Mega)
        "taux_mdo_h":       15.0,   # €/h opérateur + post-cure
        "temps_setup_h":    0.50,   # h   orientation + supports + lancement
        "temps_postprod_h": 0.75,   # h   lavage IPA + post-cure UV + séchage
        "vitesse_cm3_h":    10.0,   # cm³/h résine pro (8–12 selon hauteur plateau)
        "marge":            1.25,
        "mdo_inclus":       False,
    },
    "Découpe laser": {
        "taux_machine_h":   80.0,   # €/h laser fibre 2kW (machine ~150k€, amort 10ans/4000h=37€ + énergie + maintenance)
        "taux_mdo_h":       20.0,   # €/h opérateur laser
        "temps_setup_h":    0.50,   # h   nesting DXF + réglage paramètres + positionnement tôle
        "temps_postprod_h": 0.20,   # h   ébavurage + nettoyage oxyde
        "vitesse_cm2_min":  80.0,   # cm²/min vitesse découpe acier 3mm (5–10 m/min linéaire)
        "marge":            1.20,
        "mdo_inclus":       False,
    },
    "Usinage CNC": {
        "taux_machine_h":   65.0,   # €/h TOUT INCLUS (machine + MdO + énergie + outillage)
                                    # Sources : hdproto 45–95€, xometry.pro médiane 65€, wayken 50–100$
                                    # Calibré : ETRIERA 440×83×65mm acier S235 → 399€ (cible 400€) ✅
        "taux_mdo_h":       0.0,    # MdO déjà inclus dans taux_machine_h
        "temps_setup_h":    1.0,    # h   bridage + origines + programme FAO + premier copeau
        "temps_postprod_h": 0.4,    # h   ébavurage + contrôle dimensionnel + nettoyage
        "vitesse_cm3_h":    400.0,  # cm²/h surface usinée (paramètre CNC spécifique)
        "marge":            1.15,
        "mdo_inclus":       True,   # taux tout-inclus → pas de ligne MdO séparée
    },
    "Tôlerie / Pliage": {
        "taux_machine_h":   55.0,   # €/h presse plieuse CNC + laser découpe (Trumpf, Amada)
        "taux_mdo_h":       26.0,   # €/h opérateur tôlerie France
        "temps_setup_h":    0.60,   # h   programme pliage + outillage + premier essai
        "temps_postprod_h": 0.20,   # h   ébavurage + redressage + contrôle
        "vitesse_cm2_min":  60.0,   # cm²/min découpe tôle
        "marge":            1.20,
        "mdo_inclus":       False,
    },
}


# ─────────────────────────────────────────────
#  Tolérance & Finition
# ─────────────────────────────────────────────

RUGOSITES = {
    "Ra 0.8":  {"label": "Ra 0.8 µm — Rectifié/poli miroir", "coeff_machine": 2.2, "coeff_delai": 1.4, "procedes_ok": ["Usinage CNC"], "note": "Rectification ou polissage manuel requis"},
    "Ra 1.6":  {"label": "Ra 1.6 µm — Finition soignée",     "coeff_machine": 1.5, "coeff_delai": 1.2, "procedes_ok": ["Usinage CNC", "Impression 3D SLA/Résine"], "note": "Passes de finition supplémentaires"},
    "Ra 3.2":  {"label": "Ra 3.2 µm — Standard usiné",       "coeff_machine": 1.0, "coeff_delai": 1.0, "procedes_ok": ["Usinage CNC", "Découpe laser", "Tôlerie / Pliage", "Impression 3D SLA/Résine"], "note": "Standard atelier"},
    "Ra 6.3":  {"label": "Ra 6.3 µm — Brut d'usinage",       "coeff_machine": 0.85,"coeff_delai": 0.9, "procedes_ok": ["Usinage CNC", "Découpe laser", "Tôlerie / Pliage", "Impression 3D FDM", "Impression 3D SLA/Résine"], "note": "Pas de finition spéciale"},
    "Aucune":  {"label": "Aucune exigence",                   "coeff_machine": 1.0, "coeff_delai": 1.0, "procedes_ok": ["Usinage CNC", "Découpe laser", "Tôlerie / Pliage", "Impression 3D FDM", "Impression 3D SLA/Résine"], "note": ""},
}

TOLERANCES_ISO = {
    "IT6":  {"label": "IT6 — Précision élevée (±0.01mm)",   "coeff_machine": 2.0, "coeff_delai": 1.5, "procedes_ok": ["Usinage CNC"], "note": "Métrologie obligatoire, machines de précision"},
    "IT7":  {"label": "IT7 — Bonne précision (±0.02mm)",    "coeff_machine": 1.4, "coeff_delai": 1.2, "procedes_ok": ["Usinage CNC"], "note": "Contrôle dimensionnel systématique"},
    "IT8":  {"label": "IT8 — Précision courante (±0.05mm)", "coeff_machine": 1.0, "coeff_delai": 1.0, "procedes_ok": ["Usinage CNC", "Découpe laser", "Tôlerie / Pliage"], "note": "Standard atelier CNC"},
    "IT11": {"label": "IT11 — Précision libre (±0.2mm)",    "coeff_machine": 0.9, "coeff_delai": 0.9, "procedes_ok": ["Usinage CNC", "Découpe laser", "Tôlerie / Pliage", "Impression 3D FDM", "Impression 3D SLA/Résine"], "note": "Tolérance générale, pas de contrôle spécifique"},
    "Libre":{"label": "Libre — Pas d'exigence dimensionnelle","coeff_machine": 1.0, "coeff_delai": 1.0, "procedes_ok": ["Usinage CNC", "Découpe laser", "Tôlerie / Pliage", "Impression 3D FDM", "Impression 3D SLA/Résine"], "note": ""},
}

TRAITEMENTS = {
    "Aucun":            {"label": "Aucun traitement",                   "cout_fixe": 0,    "cout_cm2": 0,    "delai_j": 0, "matieres_ok": ["*"], "procedes_ok": ["*"], "note": ""},
    "Anodisation":      {"label": "Anodisation (type II)",              "cout_fixe": 40.0, "cout_cm2": 0.08, "delai_j": 3, "matieres_ok": ["Aluminium 6061"], "procedes_ok": ["Usinage CNC", "Découpe laser", "Tôlerie / Pliage"], "note": "Uniquement sur aluminium — protection + esthétique"},
    "Anodisation dure": {"label": "Anodisation dure (type III)",        "cout_fixe": 65.0, "cout_cm2": 0.15, "delai_j": 4, "matieres_ok": ["Aluminium 6061"], "procedes_ok": ["Usinage CNC"], "note": "Dureté élevée, résistance usure"},
    "Zingage":          {"label": "Zingage électrolytique",             "cout_fixe": 35.0, "cout_cm2": 0.06, "delai_j": 3, "matieres_ok": ["Acier S235"], "procedes_ok": ["Usinage CNC", "Découpe laser", "Tôlerie / Pliage"], "note": "Protection anticorrosion acier"},
    "Peinture":         {"label": "Peinture / thermolaquage",           "cout_fixe": 50.0, "cout_cm2": 0.10, "delai_j": 4, "matieres_ok": ["Aluminium 6061", "Acier S235", "Inox 316L"], "procedes_ok": ["Usinage CNC", "Découpe laser", "Tôlerie / Pliage"], "note": "RAL au choix"},
    "Passivation":      {"label": "Passivation (inox)",                 "cout_fixe": 30.0, "cout_cm2": 0.04, "delai_j": 2, "matieres_ok": ["Inox 316L"], "procedes_ok": ["Usinage CNC", "Tôlerie / Pliage"], "note": "Renforce la résistance à la corrosion"},
    "Sablage":          {"label": "Sablage / grenaillage",              "cout_fixe": 25.0, "cout_cm2": 0.05, "delai_j": 1, "matieres_ok": ["Aluminium 6061", "Acier S235", "Inox 316L"], "procedes_ok": ["Usinage CNC", "Découpe laser", "Tôlerie / Pliage", "Impression 3D SLA/Résine"], "note": "Finition mate uniforme"},
}


# ─────────────────────────────────────────────
#  Délais de fabrication
# ─────────────────────────────────────────────

DELAIS_BASE = {
    "Impression 3D FDM":         {"file_attente_j": 1, "postprod_j": 1,   "livraison_fr_j": 2, "label_postprod": "Retrait supports + nettoyage"},
    "Impression 3D SLA/Résine":  {"file_attente_j": 2, "postprod_j": 2,   "livraison_fr_j": 2, "label_postprod": "Lavage IPA + post-cure UV"},
    "Découpe laser":             {"file_attente_j": 2, "postprod_j": 1,   "livraison_fr_j": 2, "label_postprod": "Ébavurage + nettoyage"},
    "Usinage CNC":               {"file_attente_j": 5, "postprod_j": 2,   "livraison_fr_j": 2, "label_postprod": "Ébavurage + contrôle dimensionnel"},
    "Tôlerie / Pliage":          {"file_attente_j": 3, "postprod_j": 1,   "livraison_fr_j": 2, "label_postprod": "Ébavurage + redressage"},
}

DELAIS_PAYS = {
    "France":    {"coeff_attente": 1.0, "livraison_j": 2,  "douane_j": 0},
    "Allemagne": {"coeff_attente": 0.9, "livraison_j": 3,  "douane_j": 0},
    "Pologne":   {"coeff_attente": 0.8, "livraison_j": 5,  "douane_j": 0},
    "Chine":     {"coeff_attente": 0.5, "livraison_j": 25, "douane_j": 5},
}


# ─────────────────────────────────────────────
#  Structures de données
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

@dataclass
class DelaiResult:
    procede: str
    pays: str
    temps_fab_h: float
    file_attente_j: float
    postprod_j: float
    livraison_j: float
    douane_j: float
    total_j: float
    total_semaines: float
    label_postprod: str
    urgence_possible: bool
    urgence_surcoût_pct: int
    breakdown: list = field(default_factory=list)

@dataclass
class FinitionConfig:
    rugosite:   str = "Aucune"
    tolerance:  str = "Libre"
    traitement: str = "Aucun"

@dataclass
class FinitionImpact:
    compatible:         bool
    incompatibilites:   list
    surcoût_machine:    float
    surcoût_traitement: float
    surcoût_total:      float
    delai_extra_j:      float
    lignes_devis:       list
    notes:              list


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
        ) / 100.0
        t_fab = surface_2d / p["vitesse_cm2_min"] / 60.0

    elif procede == "Usinage CNC":
        # Basé sur la surface totale à usiner (cm²/h calibré sur ETRIERA)
        surface_cm2 = features.surface_mm2 / 100.0
        t_fab = surface_cm2 / p["vitesse_cm3_h"]  # vitesse_cm3_h = cm²/h pour CNC
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
    mdo_inclus   = p.get("mdo_inclus", False)

    # ── Matière ──
    volume_cm3       = features.volume_mm3 / 1000.0
    masse_kg         = volume_cm3 * mat["densite"] / 1000.0

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
        detail=f"{masse_achetee_kg*1000:.1f} g × {prix_mat_kg:.2f} €/kg (perte ×{coeff_perte:.1f}, pays ×{country['coeff_matiere']})",
    ))

    if procede == "Usinage CNC":
        notes.append("Perte matière ×3.5 : usinage enlève ~70% du brut")
    if features.estimated_overhang and procede == "Impression 3D FDM":
        notes.append("Surplombs détectés : supports inclus (+15%)")
    if pays == "Chine":
        notes.append("⚠ Prévoir +300–1500 € de frais logistique et 4–8 semaines de délai")

    # ── Machine ──
    t_fab            = calc_temps_fabrication(procede, features)
    t_setup_unitaire = p["temps_setup_h"] / quantite

    cout_machine = (t_fab + t_setup_unitaire + p["temps_postprod_h"]) * taux_machine

    if mdo_inclus:
        details.append(CoutDetail(
            label="Machine + MdO (tout inclus)",
            montant=round(cout_machine, 2),
            detail=f"{t_fab:.2f}h fab + {t_setup_unitaire:.2f}h setup + {p['temps_postprod_h']:.2f}h finition × {taux_machine:.1f} €/h tout inclus (pays ×{country['coeff_machine']})",
        ))
    else:
        details.append(CoutDetail(
            label="Machine",
            montant=round(cout_machine, 2),
            detail=f"{t_fab:.2f}h fab + {t_setup_unitaire:.2f}h setup + {p['temps_postprod_h']:.2f}h finition × {taux_machine:.1f} €/h (pays ×{country['coeff_machine']})",
        ))

    # ── Main d'œuvre ──
    if mdo_inclus:
        cout_mdo = 0.0
        details.append(CoutDetail(
            label="Main d'œuvre",
            montant=0.0,
            detail="Inclus dans le taux machine tout-inclus",
        ))
    else:
        cout_mdo = (t_setup_unitaire + p["temps_postprod_h"]) * taux_mdo
        details.append(CoutDetail(
            label="Main d'œuvre",
            montant=round(cout_mdo, 2),
            detail=f"{t_setup_unitaire:.2f}h setup + {p['temps_postprod_h']:.2f}h finition × {taux_mdo:.1f} €/h (pays ×{country['coeff_mdo']})",
        ))

    # ── Marge ──
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
#  Délais
# ─────────────────────────────────────────────

def calc_delai(procede: str, features, pays: str = "France", quantite: int = 1) -> DelaiResult:
    base   = DELAIS_BASE[procede]
    cpays  = DELAIS_PAYS.get(pays, DELAIS_PAYS["France"])

    t_fab_h  = calc_temps_fabrication(procede, features) * quantite
    t_fab_j  = round(t_fab_h / 7, 2)
    attente  = base["file_attente_j"] * cpays["coeff_attente"]
    if quantite > 10:  attente *= 1.5
    if quantite > 100: attente *= 2.0

    postprod  = base["postprod_j"] + round(quantite * 0.02, 1)
    livraison = cpays["livraison_j"]
    douane    = cpays["douane_j"]
    total     = round(t_fab_j + attente + postprod + livraison + douane, 1)
    semaines  = round(total / 5, 1)

    urgence_possible = procede in ("Impression 3D FDM", "Impression 3D SLA/Résine", "Découpe laser")
    urgence_surcoût  = 60 if procede == "Usinage CNC" else 35

    breakdown = [
        {"label": "Fabrication",            "valeur": round(t_fab_j, 1), "unite": "j", "color": "#00d4ff"},
        {"label": "File d'attente",          "valeur": round(attente, 1), "unite": "j", "color": "#a78bfa"},
        {"label": base["label_postprod"],    "valeur": round(postprod, 1),"unite": "j", "color": "#ff8c00"},
        {"label": "Livraison",               "valeur": livraison,          "unite": "j", "color": "#00ff88"},
    ]
    if douane > 0:
        breakdown.append({"label": "Dédouanement", "valeur": douane, "unite": "j", "color": "#ff3a3a"})

    return DelaiResult(
        procede=procede, pays=pays, temps_fab_h=round(t_fab_h, 2),
        file_attente_j=round(attente, 1), postprod_j=round(postprod, 1),
        livraison_j=livraison, douane_j=douane, total_j=total, total_semaines=semaines,
        label_postprod=base["label_postprod"], urgence_possible=urgence_possible,
        urgence_surcoût_pct=urgence_surcoût, breakdown=breakdown,
    )

def calc_delais_complet(features, quantite: int = 1, pays: str = "France") -> dict:
    return {p: calc_delai(p, features, pays, quantite) for p in PROCESS_PARAMS}


# ─────────────────────────────────────────────
#  Finition
# ─────────────────────────────────────────────

def calc_finition_impact(procede, materiau_key, features, config: FinitionConfig, cout_base: float, pays: str = "France") -> FinitionImpact:
    mat     = MATERIALS[materiau_key]
    rug     = RUGOSITES[config.rugosite]
    tol     = TOLERANCES_ISO[config.tolerance]
    trait   = TRAITEMENTS[config.traitement]
    country = COUNTRIES.get(pays, COUNTRIES["France"])
    incompatibilites, lignes_devis, notes = [], [], []

    if procede not in rug["procedes_ok"]:
        incompatibilites.append(f"Rugosité {config.rugosite} non atteignable en {procede}")
    if procede not in tol["procedes_ok"]:
        incompatibilites.append(f"Tolérance {config.tolerance} non atteignable en {procede}")
    if trait["matieres_ok"] != ["*"] and mat["label"] not in trait["matieres_ok"]:
        incompatibilites.append(f"Traitement '{config.traitement}' incompatible avec {mat['label']}")
    if trait["procedes_ok"] != ["*"] and procede not in trait["procedes_ok"]:
        incompatibilites.append(f"Traitement '{config.traitement}' incompatible avec {procede}")

    compatible = len(incompatibilites) == 0
    surcoût_machine = surcoût_traitement = 0.0

    if compatible:
        coeff_machine = rug["coeff_machine"] * tol["coeff_machine"]
        if coeff_machine != 1.0:
            surcoût_machine = round(cout_base * (coeff_machine - 1.0) * 0.6, 2)
            if config.rugosite != "Aucune":
                lignes_devis.append({"label": f"Rugosité {config.rugosite}", "montant": round(surcoût_machine * 0.5, 2), "detail": f"Passes finition supplémentaires (×{rug['coeff_machine']})"})
                if rug["note"]: notes.append(rug["note"])
            if config.tolerance != "Libre":
                lignes_devis.append({"label": f"Tolérance {config.tolerance}", "montant": round(surcoût_machine * 0.5, 2), "detail": f"Contrôle dimensionnel renforcé (×{tol['coeff_machine']})"})
                if tol["note"]: notes.append(tol["note"])

        if config.traitement != "Aucun":
            surface_cm2 = features.surface_mm2 / 100.0
            cout_trait  = (trait["cout_fixe"] + trait["cout_cm2"] * surface_cm2) * country["coeff_machine"]
            surcoût_traitement = round(cout_trait, 2)
            lignes_devis.append({"label": trait["label"], "montant": surcoût_traitement, "detail": f"Fixe {trait['cout_fixe']}€ + {surface_cm2:.0f}cm² × {trait['cout_cm2']}€/cm² (pays ×{country['coeff_machine']})"})
            if trait["note"]: notes.append(trait["note"])

    delai_extra = round(trait["delai_j"] + (1.5 if rug["coeff_delai"] > 1.0 else 0) + (1.0 if tol["coeff_delai"] > 1.0 else 0), 1) if compatible else 0.0

    return FinitionImpact(
        compatible=compatible, incompatibilites=incompatibilites,
        surcoût_machine=surcoût_machine, surcoût_traitement=surcoût_traitement,
        surcoût_total=round(surcoût_machine + surcoût_traitement, 2),
        delai_extra_j=delai_extra, lignes_devis=lignes_devis, notes=notes,
    )
