"""
Module Archimède — Volume mouillé et poussée d'Archimède
Supporte les pièces simples et assemblages multi-solides STEP

Méthode :
  1. Charger le STEP et détecter tous les solides
  2. Si assemblage (N > 1) → union booléenne pour obtenir l'enveloppe extérieure
  3. Calculer le volume de l'enveloppe (= volume déplacé si totalement immergé)
  4. Calculer la poussée : F = ρ × g × V
"""

from dataclasses import dataclass, field
import cadquery as cq


# ─────────────────────────────────────────────
#  Fluides prédéfinis  (densité en kg/m³)
# ─────────────────────────────────────────────

FLUIDES_PREDEFINIS = {
    "eau_douce":  {"label": "Eau douce",       "densite": 1000.0, "emoji": "💧"},
    "eau_mer":    {"label": "Eau de mer",       "densite": 1025.0, "emoji": "🌊"},
    "huile":      {"label": "Huile minérale",   "densite":  870.0, "emoji": "🛢"},
    "ethanol":    {"label": "Éthanol",           "densite":  789.0, "emoji": "⚗️"},
    "mercure":    {"label": "Mercure",           "densite": 13534.0,"emoji": "🔬"},
    "personnalise": {"label": "Fluide personnalisé", "densite": None, "emoji": "✏️"},
}

G = 9.81  # m/s²


# ─────────────────────────────────────────────
#  Structures de données
# ─────────────────────────────────────────────

@dataclass
class SolideInfo:
    """Informations sur un solide individuel de l'assemblage."""
    index: int
    volume_mm3: float
    volume_cm3: float
    volume_L: float
    bbox_x: float
    bbox_y: float
    bbox_z: float
    masse_estimee_kg: float = 0.0   # si matière connue


@dataclass
class PousseeResult:
    """Résultat pour un fluide donné."""
    fluide_key: str
    fluide_label: str
    densite_kg_m3: float
    poussee_N: float
    poussee_kg_equiv: float   # kg de masse équivalente soulevée
    immersion: str            # "totale" ou "partielle" (si masse fournie)


@dataclass
class ArchimedeResult:
    """Résultat complet de l'analyse Archimède."""
    # Assemblage
    nb_solides: int
    est_assemblage: bool
    union_reussie: bool

    # Volumes
    volumes_individuels_mm3: list        # volume de chaque solide
    volume_somme_mm3: float              # somme brute (peut compter les chevauchements)
    volume_enveloppe_mm3: float          # volume mouillé réel (après union)
    volume_enveloppe_cm3: float
    volume_enveloppe_L: float
    volume_enveloppe_m3: float

    # Bbox enveloppe
    bbox_x: float
    bbox_y: float
    bbox_z: float

    # Détail par solide
    solides: list

    # Poussées
    poussees: list

    # Notes
    notes: list = field(default_factory=list)


# ─────────────────────────────────────────────
#  Analyse principale
# ─────────────────────────────────────────────

def calc_archimede(
    step_path: str,
    fluides_keys: list = None,
    densite_perso: float = None,
    immersion_profondeur_mm: float = None,   # None = immersion totale
) -> ArchimedeResult:
    """
    Analyse un fichier STEP (pièce ou assemblage) et calcule la poussée d'Archimède.

    Args:
        step_path           : chemin vers le fichier .step
        fluides_keys        : liste de clés fluide à calculer (ex: ["eau_douce", "eau_mer"])
        densite_perso       : densité personnalisée en kg/m³ (si "personnalise" dans fluides_keys)
        immersion_profondeur_mm : profondeur d'immersion (None = immersion totale)

    Returns:
        ArchimedeResult complet
    """
    if fluides_keys is None:
        fluides_keys = ["eau_douce", "eau_mer"]

    shape = cq.importers.importStep(step_path)
    solids = shape.solids().vals()
    nb_solides = len(solids)
    est_assemblage = nb_solides > 1
    notes = []

    # ── Infos par solide ──
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps

    solides_info = []
    volumes_individuels = []

    for i, s in enumerate(solids):
        props = GProp_GProps()
        BRepGProp.VolumeProperties_s(s.wrapped, props)
        vol = props.Mass()
        bb  = s.BoundingBox()
        volumes_individuels.append(vol)
        solides_info.append(SolideInfo(
            index=i+1,
            volume_mm3=round(vol, 1),
            volume_cm3=round(vol / 1000, 3),
            volume_L=round(vol / 1e6, 6),
            bbox_x=round(bb.xlen, 2),
            bbox_y=round(bb.ylen, 2),
            bbox_z=round(bb.zlen, 2),
        ))

    volume_somme = sum(volumes_individuels)

    # ── Union booléenne pour enveloppe extérieure ──
    union_reussie = False
    volume_enveloppe = volume_somme  # fallback

    if nb_solides == 1:
        volume_enveloppe = volumes_individuels[0]
        union_reussie = True
        notes.append("Pièce simple — volume mouillé = volume du solide unique")
    else:
        notes.append(f"Assemblage de {nb_solides} solides détectés — fusion en cours...")
        try:
            result = cq.Workplane().add(solids[0])
            failed = []
            for i, s in enumerate(solids[1:], 1):
                try:
                    result = result.union(cq.Workplane().add(s))
                except Exception as e:
                    failed.append(i + 1)

            props_union = GProp_GProps()
            BRepGProp.VolumeProperties_s(result.val().wrapped, props_union)
            volume_enveloppe = props_union.Mass()
            union_reussie = True

            if failed:
                notes.append(f"⚠ Solides {failed} ignorés lors de la fusion (géométrie incompatible)")
                notes.append("Volume mouillé basé sur union partielle — légère surestimation possible")
            else:
                notes.append("Union booléenne complète — volume mouillé précis")

            overlap = volume_somme - volume_enveloppe
            if overlap > 0:
                notes.append(f"Chevauchement détecté entre solides : {overlap/1000:.1f} cm³ éliminé")

        except Exception as e:
            # Fallback : bbox englobante de tous les solides
            notes.append(f"⚠ Union booléenne impossible ({str(e)[:60]}) — utilisation bbox englobante")
            xmins = [s.BoundingBox().xmin for s in solids]
            xmaxs = [s.BoundingBox().xmax for s in solids]
            ymins = [s.BoundingBox().ymin for s in solids]
            ymaxs = [s.BoundingBox().ymax for s in solids]
            zmins = [s.BoundingBox().zmin for s in solids]
            zmaxs = [s.BoundingBox().zmax for s in solids]
            volume_enveloppe = (max(xmaxs)-min(xmins)) * (max(ymaxs)-min(ymins)) * (max(zmaxs)-min(zmins))
            notes.append("Volume mouillé = bbox englobante (approximation conservative)")

    # ── Immersion partielle ──
    if immersion_profondeur_mm is not None:
        bb_global = shape.val().BoundingBox()
        hauteur_totale = bb_global.zlen
        if immersion_profondeur_mm >= hauteur_totale:
            notes.append("Profondeur d'immersion ≥ hauteur pièce → immersion totale")
            fraction_immergee = 1.0
        else:
            fraction_immergee = immersion_profondeur_mm / hauteur_totale
            notes.append(f"Immersion partielle : {fraction_immergee*100:.1f}% du volume")
        volume_effectif = volume_enveloppe * fraction_immergee
    else:
        fraction_immergee = 1.0
        volume_effectif = volume_enveloppe

    # ── Bbox globale ──
    try:
        bb_all = shape.val().BoundingBox()
        bbox_x, bbox_y, bbox_z = round(bb_all.xlen, 2), round(bb_all.ylen, 2), round(bb_all.zlen, 2)
    except Exception:
        bbox_x = max(s.BoundingBox().xlen for s in solids)
        bbox_y = max(s.BoundingBox().ylen for s in solids)
        bbox_z = max(s.BoundingBox().zlen for s in solids)

    # ── Poussées ──
    poussees = []
    vol_m3 = volume_effectif / 1e9  # mm³ → m³

    for key in fluides_keys:
        if key == "personnalise":
            if densite_perso is None:
                continue
            densite = densite_perso
            label   = f"Fluide perso ({densite_perso:.0f} kg/m³)"
        else:
            fluide  = FLUIDES_PREDEFINIS.get(key)
            if not fluide:
                continue
            densite = fluide["densite"]
            label   = fluide["label"]

        poussee_N  = densite * G * vol_m3
        poussee_kg = densite * vol_m3

        poussees.append(PousseeResult(
            fluide_key=key,
            fluide_label=label,
            densite_kg_m3=densite,
            poussee_N=round(poussee_N, 3),
            poussee_kg_equiv=round(poussee_kg, 4),
            immersion="totale" if fraction_immergee == 1.0 else f"partielle ({fraction_immergee*100:.1f}%)",
        ))

    return ArchimedeResult(
        nb_solides=nb_solides,
        est_assemblage=est_assemblage,
        union_reussie=union_reussie,
        volumes_individuels_mm3=[round(v, 1) for v in volumes_individuels],
        volume_somme_mm3=round(volume_somme, 1),
        volume_enveloppe_mm3=round(volume_enveloppe, 1),
        volume_enveloppe_cm3=round(volume_enveloppe / 1000, 3),
        volume_enveloppe_L=round(volume_enveloppe / 1e6, 4),
        volume_enveloppe_m3=round(volume_enveloppe / 1e9, 9),
        bbox_x=bbox_x, bbox_y=bbox_y, bbox_z=bbox_z,
        solides=solides_info,
        poussees=poussees,
        notes=notes,
    )
