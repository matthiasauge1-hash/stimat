"""
Moteur d'analyse STEP - Reconnaissance de procédé de fabrication
Procédés supportés : FDM, SLA, Découpe laser, Usinage CNC, Tôlerie/Pliage
"""

import cadquery as cq
from cadquery import exporters
import numpy as np
from dataclasses import dataclass, field
from typing import Optional
import traceback


# ─────────────────────────────────────────────
#  Structures de données
# ─────────────────────────────────────────────

@dataclass
class GeometryFeatures:
    """Caractéristiques géométriques extraites du fichier STEP."""
    volume_mm3: float = 0.0
    surface_mm2: float = 0.0
    bbox_x: float = 0.0
    bbox_y: float = 0.0
    bbox_z: float = 0.0
    flatness_ratio: float = 0.0        # min_dim / max_dim  (proche de 0 = pièce plate)
    aspect_ratio: float = 0.0          # max_dim / mid_dim
    solidity: float = 0.0              # volume / volume_bbox (densité de remplissage)
    wall_thickness_min: float = 0.0    # épaisseur minimale estimée (mm)
    face_count: int = 0                # nombre de faces
    planar_face_ratio: float = 0.0     # proportion de faces planes vs courbes
    has_thin_walls: bool = False        # parois < 1.5 mm
    is_flat: bool = False               # pièce essentiellement plate
    is_very_flat: bool = False          # très fine, type tôle
    has_complex_curves: bool = False    # surfaces gauches / organiques
    estimated_overhang: bool = False    # surplombs probables


@dataclass
class ProcessScore:
    """Score d'adéquation pour un procédé donné."""
    name: str
    score: float          # 0.0 à 100.0
    feasible: bool
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class AnalysisResult:
    """Résultat complet de l'analyse."""
    features: GeometryFeatures
    scores: list[ProcessScore]
    recommended: str
    confidence: float       # 0.0 à 1.0
    summary: str


# ─────────────────────────────────────────────
#  Extraction des features géométriques
# ─────────────────────────────────────────────

def extract_features(step_path: str) -> GeometryFeatures:
    """
    Charge un fichier STEP et extrait les caractéristiques géométriques.
    Utilise uniquement l'API CadQuery + OCP (le binding OCC intégré à CadQuery pip).
    """
    shape = cq.importers.importStep(step_path)
    solid = shape.val()

    # ── Volume & surface via OCP (binding intégré dans cadquery pip) ──
    try:
        from OCP.BRepGProp import BRepGProp
        from OCP.GProp import GProp_GProps

        vol_props = GProp_GProps()
        BRepGProp.VolumeProperties_s(solid.wrapped, vol_props)
        volume = vol_props.Mass()

        surf_props = GProp_GProps()
        BRepGProp.SurfaceProperties_s(solid.wrapped, surf_props)
        surface = surf_props.Mass()
    except Exception:
        # Fallback : estimation via bounding box
        bb = solid.BoundingBox()
        volume = bb.xlen * bb.ylen * bb.zlen * 0.5
        surface = 2 * (bb.xlen * bb.ylen + bb.ylen * bb.zlen + bb.xlen * bb.zlen)

    # ── Bounding box ──
    bb = solid.BoundingBox()
    dx, dy, dz = bb.xlen, bb.ylen, bb.zlen
    dims = sorted([dx, dy, dz])
    min_dim, mid_dim, max_dim = dims

    bbox_volume = dx * dy * dz
    solidity = volume / bbox_volume if bbox_volume > 0 else 0

    flatness_ratio = min_dim / max_dim if max_dim > 0 else 0
    aspect_ratio = max_dim / mid_dim if mid_dim > 0 else 1

    # ── Analyse des faces (détection planes via OCP) ──
    faces = shape.faces().vals()
    face_count = len(faces)
    planar_count = 0

    try:
        from OCP.BRepAdaptor import BRepAdaptor_Surface
        from OCP.GeomAbs import GeomAbs_Plane
        for face in faces:
            adaptor = BRepAdaptor_Surface(face.wrapped)
            if adaptor.GetType() == GeomAbs_Plane:
                planar_count += 1
    except Exception:
        # Fallback : estimation via le nombre de faces et la géométrie
        planar_count = int(face_count * 0.7) if flatness_ratio > 0.1 else int(face_count * 0.3)

    planar_face_ratio = planar_count / face_count if face_count > 0 else 0

    # ── Estimation épaisseur minimale ──
    wall_thickness_min = min_dim * max(solidity, 0.3)
    if wall_thickness_min < 0.5:
        wall_thickness_min = min_dim

    # ── Drapeaux booléens ──
    is_very_flat = flatness_ratio < 0.05
    is_flat = flatness_ratio < 0.15
    has_thin_walls = wall_thickness_min < 1.5
    has_complex_curves = planar_face_ratio < 0.4
    estimated_overhang = (
        has_complex_curves and
        not is_flat and
        solidity < 0.45
    )

    return GeometryFeatures(
        volume_mm3=round(volume, 2),
        surface_mm2=round(surface, 2),
        bbox_x=round(dx, 2),
        bbox_y=round(dy, 2),
        bbox_z=round(dz, 2),
        flatness_ratio=round(flatness_ratio, 4),
        aspect_ratio=round(aspect_ratio, 4),
        solidity=round(solidity, 4),
        wall_thickness_min=round(wall_thickness_min, 2),
        face_count=face_count,
        planar_face_ratio=round(planar_face_ratio, 4),
        has_thin_walls=has_thin_walls,
        is_flat=is_flat,
        is_very_flat=is_very_flat,
        has_complex_curves=has_complex_curves,
        estimated_overhang=estimated_overhang,
    )


# ─────────────────────────────────────────────
#  Moteur de scoring par procédé
# ─────────────────────────────────────────────

def score_fdm(f: GeometryFeatures) -> ProcessScore:
    score = 60.0
    reasons = []
    warnings = []

    if f.has_thin_walls:
        score -= 20
        warnings.append(f"Parois fines ({f.wall_thickness_min:.1f} mm) : risque de fragilité en FDM")
    else:
        score += 10
        reasons.append("Épaisseur de paroi compatible FDM")

    if f.estimated_overhang:
        score -= 15
        warnings.append("Surplombs probables : supports nécessaires, peut dégrader la finition")
    else:
        score += 10
        reasons.append("Géométrie sans surplombs majeurs")

    if f.has_complex_curves:
        score -= 5
        warnings.append("Surfaces complexes : la résolution FDM peut être insuffisante")
    
    if f.is_very_flat:
        score -= 30
        warnings.append("Pièce très plate : FDM inadapté, préférez la découpe laser ou tôlerie")

    if f.volume_mm3 > 500_000:
        score += 10
        reasons.append("Volume important : FDM économiquement avantageux")

    if f.solidity > 0.5:
        score += 10
        reasons.append("Pièce solide (peu creuse) : bonne candidat FDM")

    score = max(0, min(100, score))
    return ProcessScore("Impression 3D FDM", round(score, 1), score >= 30, reasons, warnings)


def score_sla(f: GeometryFeatures) -> ProcessScore:
    score = 50.0
    reasons = []
    warnings = []

    if f.has_complex_curves:
        score += 25
        reasons.append("Surfaces complexes : SLA excelle sur les géométries organiques")

    if f.has_thin_walls:
        score += 15
        reasons.append(f"Parois fines ({f.wall_thickness_min:.1f} mm) : SLA permet des détails fins")

    if f.estimated_overhang:
        score -= 10
        warnings.append("Surplombs : supports résine nécessaires (post-traitement requis)")

    if f.volume_mm3 > 200_000:
        score -= 20
        warnings.append("Volume élevé : coût résine important, temps d'impression long")
    else:
        score += 10
        reasons.append("Volume raisonnable pour la résine")

    if f.is_very_flat:
        score -= 20
        warnings.append("Pièce très plate : procédé 2D plus adapté")

    if f.planar_face_ratio > 0.8:
        score -= 15
        warnings.append("Géométrie très angulaire : SLA moins utile que FDM ou CNC")

    score = max(0, min(100, score))
    return ProcessScore("Impression 3D SLA/Résine", round(score, 1), score >= 30, reasons, warnings)


def score_laser(f: GeometryFeatures) -> ProcessScore:
    score = 20.0
    reasons = []
    warnings = []

    if f.is_very_flat:
        score += 60
        reasons.append(f"Pièce très plate (ratio {f.flatness_ratio:.3f}) : idéale pour découpe laser")
    elif f.is_flat:
        score += 35
        reasons.append("Pièce relativement plate : découpe laser possible")
    else:
        score -= 20
        warnings.append("Pièce trop épaisse/volumineuse pour la découpe laser 2D")

    if f.planar_face_ratio > 0.7:
        score += 15
        reasons.append("Contours principalement plans : compatibles laser")

    if f.has_complex_curves and not f.is_flat:
        score -= 25
        warnings.append("Surfaces 3D complexes non réalisables en découpe laser")

    max_dim = max(f.bbox_x, f.bbox_y, f.bbox_z)
    if max_dim > 1500:
        warnings.append("Pièce grande : vérifier la capacité du banc laser")

    score = max(0, min(100, score))
    return ProcessScore("Découpe laser", round(score, 1), score >= 30, reasons, warnings)


def score_cnc(f: GeometryFeatures) -> ProcessScore:
    score = 55.0
    reasons = []
    warnings = []

    if f.planar_face_ratio > 0.6:
        score += 20
        reasons.append("Géométrie angulaire/prismatique : idéale pour usinage CNC")

    if f.has_thin_walls:
        score -= 20
        warnings.append(f"Parois très fines ({f.wall_thickness_min:.1f} mm) : risque de vibration/casse en fraisage")

    if f.has_complex_curves:
        score -= 15
        warnings.append("Surfaces gauches complexes : nécessite CNC 5 axes (coût élevé)")

    if f.estimated_overhang:
        score -= 25
        warnings.append("Surplombs importants : CNC 3 axes insuffisant, 5 axes ou retournement requis")

    if f.is_very_flat:
        score -= 10
        warnings.append("Pièce très plate : découpe laser ou tôlerie souvent plus économique")

    if f.solidity > 0.6:
        score += 10
        reasons.append("Pièce solide : bonne aptitude à l'usinage")

    if f.volume_mm3 < 1000:
        score += 5
        reasons.append("Petite pièce : CNC adapté pour les détails et tolérances serrées")

    score = max(0, min(100, score))
    return ProcessScore("Usinage CNC", round(score, 1), score >= 30, reasons, warnings)


def score_sheet_metal(f: GeometryFeatures) -> ProcessScore:
    score = 15.0
    reasons = []
    warnings = []

    # La tôlerie est idéale si : très plate + surfaces planes + aspect allongé
    if f.is_very_flat and f.planar_face_ratio > 0.65:
        score += 55
        reasons.append("Pièce plate à faces planes : forte compatibilité tôlerie/pliage")
    elif f.is_flat and f.planar_face_ratio > 0.55:
        score += 30
        reasons.append("Pièce relativement plate et angulaire : tôlerie possible")

    if f.wall_thickness_min < 6.0 and f.wall_thickness_min > 0.3:
        score += 15
        reasons.append(f"Épaisseur ({f.wall_thickness_min:.1f} mm) dans la plage standard tôle (0.5–5 mm)")

    if f.has_complex_curves:
        score -= 30
        warnings.append("Surfaces courbes complexes : incompatibles avec le pliage standard")

    if not f.is_flat:
        score -= 20
        warnings.append("Pièce volumineuse : la tôlerie ne convient qu'aux pièces issues de feuilles plates")

    if f.volume_mm3 > 1_000_000:
        warnings.append("Volume important : vérifier si la pièce peut être découpée dans une feuille standard")

    score = max(0, min(100, score))
    return ProcessScore("Tôlerie / Pliage", round(score, 1), score >= 25, reasons, warnings)


# ─────────────────────────────────────────────
#  Point d'entrée principal
# ─────────────────────────────────────────────

def analyze_step_file(step_path: str) -> AnalysisResult:
    """
    Analyse complète d'un fichier STEP.
    Retourne les features + scores + recommandation.
    """
    features = extract_features(step_path)

    scores = [
        score_fdm(features),
        score_sla(features),
        score_laser(features),
        score_cnc(features),
        score_sheet_metal(features),
    ]

    # Trier par score décroissant
    scores.sort(key=lambda s: s.score, reverse=True)

    best = scores[0]
    second = scores[1]

    # Confiance : écart entre 1er et 2ème
    gap = best.score - second.score
    confidence = min(1.0, gap / 40.0)

    # Résumé textuel
    dims = f"{features.bbox_x:.1f} × {features.bbox_y:.1f} × {features.bbox_z:.1f} mm"
    summary = (
        f"Pièce de {dims}, volume {features.volume_mm3:.0f} mm³. "
        f"Procédé recommandé : {best.name} (score {best.score:.0f}/100). "
    )
    if confidence < 0.4:
        summary += f"Attention : {second.name} est aussi pertinent (score {second.score:.0f}/100)."

    return AnalysisResult(
        features=features,
        scores=scores,
        recommended=best.name,
        confidence=round(confidence, 2),
        summary=summary,
    )
