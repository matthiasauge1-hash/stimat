"""
API FastAPI - Moteur d'analyse STEP + Devis avec pays
"""

from fastapi import FastAPI, UploadFile, File, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
import tempfile, os, traceback
from dataclasses import asdict

from app.analyzer import analyze_step_file
from app.pricing import calc_devis_complet, calc_delais_complet, calc_finition_impact, FinitionConfig, RUGOSITES, TOLERANCES_ISO, TRAITEMENTS, COUNTRIES, MATERIALS, PROCESS_PARAMS, calc_devis

app = FastAPI(title="STEP Analyzer API", version="2.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as StarletteRequest

class UTF8Middleware(BaseHTTPMiddleware):
    async def dispatch(self, request: StarletteRequest, call_next):
        response = await call_next(request)
        if "text/html" in response.headers.get("content-type", ""):
            response.headers["content-type"] = "text/html; charset=utf-8"
        return response

app.add_middleware(UTF8Middleware)


@app.get("/", response_class=HTMLResponse)
def root():
    """Sert le frontend index.html avec encodage UTF-8 explicite."""
    index_path = os.path.join(os.path.dirname(__file__), "..", "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            html = f.read()
        return HTMLResponse(
            content=html,
            headers={"Content-Type": "text/html; charset=utf-8"}
        )
    return HTMLResponse(content="<h1>Stima API</h1><p>Frontend non trouvé.</p>")


@app.get("/countries")
def get_countries():
    """Retourne la liste des pays disponibles avec leurs coefficients."""
    return {
        key: {
            "label": val["label"],
            "note": val["note"],
            "coeff_machine": val["coeff_machine"],
            "coeff_mdo": val["coeff_mdo"],
            "coeff_matiere": val["coeff_matiere"],
        }
        for key, val in COUNTRIES.items()
    }


@app.post("/analyze")
async def analyze(
    file: UploadFile = File(...),
    quantite: int = Query(default=1, ge=1, le=10000),
    pays: str = Query(default="France"),
):
    filename = file.filename or ""
    if not filename.lower().endswith((".step", ".stp")):
        raise HTTPException(400, "Format non supporté. Envoyez un fichier .step ou .stp")

    if pays not in COUNTRIES:
        raise HTTPException(400, f"Pays non supporté. Valeurs : {list(COUNTRIES.keys())}")

    suffix = ".step" if filename.lower().endswith(".step") else ".stp"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    try:
        result    = analyze_step_file(tmp_path)
        devis_raw = calc_devis_complet(result.features, quantite, pays)

        devis_json = {}
        for procede, liste in devis_raw.items():
            devis_json[procede] = [
                {
                    "materiau":            d.materiau,
                    "pays":                d.pays,
                    "quantite":            d.quantite,
                    "cout_matiere":        d.cout_matiere,
                    "cout_machine":        d.cout_machine,
                    "cout_mdo":            d.cout_mdo,
                    "cout_total_unitaire": d.cout_total_unitaire,
                    "cout_total":          d.cout_total,
                    "temps_fabrication_h": d.temps_fabrication_h,
                    "details":             [asdict(det) for det in d.details],
                    "notes":               d.notes,
                }
                for d in liste
            ]

        # Délais
        delais_raw = calc_delais_complet(result.features, quantite, pays)
        delais_json = {
            procede: {
                "total_j":            d.total_j,
                "total_semaines":     d.total_semaines,
                "temps_fab_h":        d.temps_fab_h,
                "file_attente_j":     d.file_attente_j,
                "postprod_j":         d.postprod_j,
                "livraison_j":        d.livraison_j,
                "douane_j":           d.douane_j,
                "urgence_possible":   d.urgence_possible,
                "urgence_surcoût_pct": d.urgence_surcoût_pct,
                "breakdown":          d.breakdown,
            }
            for procede, d in delais_raw.items()
        }

        return JSONResponse(content={
            "success":           True,
            "filename":          filename,
            "quantite":          quantite,
            "pays":              pays,
            "pays_label":        COUNTRIES[pays]["label"],
            "pays_note":         COUNTRIES[pays]["note"],
            "recommended_process": result.recommended,
            "confidence":        result.confidence,
            "summary":           result.summary,
            "features":          asdict(result.features),
            "scores":            [asdict(s) for s in result.scores],
            "devis":             devis_json,
            "delais":            delais_json,
        })

    except Exception as e:
        raise HTTPException(500, f"Erreur : {str(e)}\n{traceback.format_exc()}")
    finally:
        os.unlink(tmp_path)



@app.get("/finition-options")
def finition_options():
    """Retourne les options de rugosité, tolérance et traitement disponibles."""
    return {
        "rugosites":   {k: {"label": v["label"], "procedes_ok": v["procedes_ok"]} for k,v in RUGOSITES.items()},
        "tolerances":  {k: {"label": v["label"], "procedes_ok": v["procedes_ok"]} for k,v in TOLERANCES_ISO.items()},
        "traitements": {k: {"label": v["label"], "matieres_ok": v["matieres_ok"], "procedes_ok": v["procedes_ok"]} for k,v in TRAITEMENTS.items()},
    }


@app.post("/finition")
async def apply_finition(
    file: UploadFile = File(...),
    quantite:   int = Query(default=1, ge=1),
    pays:       str = Query(default="France"),
    rugosite:   str = Query(default="Aucune"),
    tolerance:  str = Query(default="Libre"),
    traitement: str = Query(default="Aucun"),
):
    """Recalcule le devis avec les paramètres de tolérance et finition."""
    filename = file.filename or ""
    if not filename.lower().endswith((".step", ".stp")):
        raise HTTPException(400, "Format non supporté")

    suffix = ".step" if filename.lower().endswith(".step") else ".stp"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    try:
        from app.analyzer import analyze_step_file
        result  = analyze_step_file(tmp_path)
        config  = FinitionConfig(rugosite=rugosite, tolerance=tolerance, traitement=traitement)
        output  = {}

        for procede in PROCESS_PARAMS:
            matieres = [k for k, m in MATERIALS.items() if procede in m["procedes"]]
            output[procede] = []
            for mat_key in matieres:
                try:
                    d      = calc_devis(procede, mat_key, result.features, quantite, pays)
                    impact = calc_finition_impact(procede, mat_key, result.features, config, d.cout_total_unitaire, pays)
                    output[procede].append({
                        "materiau":           MATERIALS[mat_key]["label"],
                        "cout_base":          d.cout_total_unitaire,
                        "surcoût_total":      impact.surcoût_total,
                        "cout_final":         round(d.cout_total_unitaire + impact.surcoût_total, 2),
                        "cout_total":         round((d.cout_total_unitaire + impact.surcoût_total) * quantite, 2),
                        "delai_extra_j":      impact.delai_extra_j,
                        "compatible":         impact.compatible,
                        "incompatibilites":   impact.incompatibilites,
                        "lignes_devis":       impact.lignes_devis,
                        "notes":              impact.notes,
                    })
                except Exception:
                    pass

        return JSONResponse(content={"success": True, "finition": output})

    except Exception as e:
        raise HTTPException(500, f"Erreur : {str(e)}")
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


# ─────────────────────────────────────────────
#  Endpoint /archimede
# ─────────────────────────────────────────────

from app.archimede import calc_archimede, FLUIDES_PREDEFINIS
from typing import Optional

@app.get("/archimede/fluides")
def get_fluides():
    """Retourne la liste des fluides disponibles."""
    return {k: {"label": v["label"], "densite": v["densite"], "emoji": v["emoji"]} for k, v in FLUIDES_PREDEFINIS.items()}


@app.post("/archimede")
async def archimede(
    file: UploadFile = File(...),
    fluides: str = Query(default="eau_douce,eau_mer"),
    densite_perso: Optional[float] = Query(default=None),
    immersion_mm: Optional[float] = Query(default=None),
):
    """
    Calcule le volume mouillé et la poussée d'Archimède.
    Supporte les pièces simples et assemblages multi-solides.
    """
    filename = file.filename or ""
    if not filename.lower().endswith((".step", ".stp")):
        raise HTTPException(400, "Format non supporté")

    fluides_keys = [f.strip() for f in fluides.split(",") if f.strip()]

    suffix = ".step" if filename.lower().endswith(".step") else ".stp"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    try:
        result = calc_archimede(
            step_path=tmp_path,
            fluides_keys=fluides_keys,
            densite_perso=densite_perso,
            immersion_profondeur_mm=immersion_mm,
        )

        return JSONResponse(content={
            "success": True,
            "nb_solides": result.nb_solides,
            "est_assemblage": result.est_assemblage,
            "union_reussie": result.union_reussie,
            "volumes": {
                "somme_mm3":     result.volume_somme_mm3,
                "enveloppe_mm3": result.volume_enveloppe_mm3,
                "enveloppe_cm3": result.volume_enveloppe_cm3,
                "enveloppe_L":   result.volume_enveloppe_L,
                "enveloppe_m3":  result.volume_enveloppe_m3,
            },
            "bbox": {"x": result.bbox_x, "y": result.bbox_y, "z": result.bbox_z},
            "solides": [
                {
                    "index": s.index,
                    "volume_mm3": s.volume_mm3,
                    "volume_cm3": s.volume_cm3,
                    "volume_L": s.volume_L,
                    "bbox": f"{s.bbox_x:.0f}×{s.bbox_y:.0f}×{s.bbox_z:.0f}",
                }
                for s in result.solides
            ],
            "poussees": [
                {
                    "fluide_key":      p.fluide_key,
                    "fluide_label":    p.fluide_label,
                    "densite_kg_m3":   p.densite_kg_m3,
                    "poussee_N":       p.poussee_N,
                    "poussee_kg_equiv":p.poussee_kg_equiv,
                    "immersion":       p.immersion,
                }
                for p in result.poussees
            ],
            "notes": result.notes,
        })
    except Exception as e:
        raise HTTPException(500, f"Erreur Archimède : {str(e)}\n{traceback.format_exc()}")
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

# ─────────────────────────────────────────────
#  Endpoint /mesh — convertit STEP → STL binaire
#  + calcule la heatmap par face (difficulté usinage)
# ─────────────────────────────────────────────

from fastapi.responses import Response
import struct, math

@app.post("/mesh")
async def get_mesh(file: UploadFile = File(...)):
    """
    Upload un fichier STEP, retourne un JSON contenant :
    - geometry : tableau de triangles {vertices, normals}
    - heatmap  : score de difficulté par triangle (0=facile, 1=difficile)
    """
    filename = file.filename or ""
    if not filename.lower().endswith((".step", ".stp")):
        raise HTTPException(400, "Format non supporté")

    suffix = ".step" if filename.lower().endswith(".step") else ".stp"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    try:
        import cadquery as cq
        import numpy as np

        shape = cq.importers.importStep(tmp_path)

        # Export STL binaire dans un buffer
        stl_path = tmp_path + ".stl"
        cq.exporters.export(shape, stl_path, exportType="STL", tolerance=0.1, angularTolerance=0.3)

        # Parse STL binaire
        with open(stl_path, "rb") as f:
            f.read(80)  # header
            n_triangles = struct.unpack("<I", f.read(4))[0]
            triangles = []
            for _ in range(n_triangles):
                nx, ny, nz = struct.unpack("<fff", f.read(12))
                v1 = struct.unpack("<fff", f.read(12))
                v2 = struct.unpack("<fff", f.read(12))
                v3 = struct.unpack("<fff", f.read(12))
                f.read(2)  # attribut
                triangles.append({
                    "normal": [nx, ny, nz],
                    "v1": list(v1), "v2": list(v2), "v3": list(v3)
                })

        os.unlink(stl_path)

        # ── Calcul heatmap difficulté d'usinage ──
        # Critères :
        #   - Face vers le bas (nz < -0.7)  → surplomb → très difficile (1.0)
        #   - Face très oblique (|nz| < 0.3 et |nx|,|ny| < 0.3) → difficile (0.7)
        #   - Face verticale pure → moyen (0.4)
        #   - Face vers le haut → facile (0.1)

        vertices = []
        normals  = []
        heatmap  = []

        for tri in triangles:
            nx, ny, nz = tri["normal"]
            # Normaliser
            length = math.sqrt(nx*nx + ny*ny + nz*nz) or 1
            nx, ny, nz = nx/length, ny/length, nz/length

            # Score difficulté
            if nz < -0.5:
                score = 0.9 + abs(nz) * 0.1   # surplomb = rouge
            elif abs(nz) < 0.2:
                score = 0.45                    # face verticale = orange
            elif nz > 0.7:
                score = 0.05                    # face vers haut = vert
            else:
                score = 0.3                     # oblique = jaune-vert

            for v in [tri["v1"], tri["v2"], tri["v3"]]:
                vertices.extend(v)
                normals.extend([nx, ny, nz])
            heatmap.extend([score, score, score])

        return JSONResponse(content={
            "success":    True,
            "n_triangles": len(triangles),
            "vertices":  vertices,
            "normals":   normals,
            "heatmap":   heatmap,
        })

    except Exception as e:
        raise HTTPException(500, f"Erreur mesh : {str(e)}\n{traceback.format_exc()}")
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
