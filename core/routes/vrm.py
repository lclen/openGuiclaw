"""VRM model management + Store download routes."""
import os
import json
from typing import Optional

import httpx
from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile
from pydantic import BaseModel

from core.state import _APP_BASE, logger

router = APIRouter(tags=["vrm"])

_MODELS_DIR = _APP_BASE / "static" / "models"
_ANIM_DIR = _APP_BASE / "static" / "vrm" / "animation"


# ── VRM model CRUD ────────────────────────────────────────────────────────────

@router.get("/api/vrm/models")
async def list_vrm_models():
    """List all available VRM models in static/models."""
    os.makedirs(_MODELS_DIR, exist_ok=True)
    models = [
        {"name": f, "path": f"/static/models/{f}"}
        for f in os.listdir(_MODELS_DIR)
        if f.lower().endswith(".vrm")
    ]
    return {"models": models}


@router.get("/api/vrm/animations")
async def list_vrm_animations():
    """List all available VRMA animations in static/vrm/animation."""
    os.makedirs(_ANIM_DIR, exist_ok=True)
    animations = [
        {"name": os.path.splitext(f)[0], "path": f"/static/vrm/animation/{f}"}
        for f in os.listdir(_ANIM_DIR)
        if f.lower().endswith(".vrma")
    ]
    return {"animations": animations}


@router.post("/api/vrm/upload")
async def upload_vrm_model(file: UploadFile = File(...)):
    """Upload a new VRM model to static/models."""
    if not file.filename.lower().endswith(".vrm"):
        raise HTTPException(status_code=400, detail="Only .vrm files are allowed.")
    os.makedirs(_MODELS_DIR, exist_ok=True)
    file_path = os.path.join(_MODELS_DIR, file.filename)
    try:
        content = await file.read()
        with open(file_path, "wb") as f:
            f.write(content)
        return {"status": "ok", "filename": file.filename, "path": f"/static/models/{file.filename}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/api/vrm/models/{filename}")
async def delete_vrm_model(filename: str):
    """Delete a VRM model from static/models (path-traversal safe)."""
    models_dir = str(_MODELS_DIR.resolve())
    file_path = os.path.realpath(os.path.join(models_dir, filename))
    if not file_path.startswith(models_dir + os.sep):
        raise HTTPException(status_code=400, detail="Invalid path")
    if not filename.lower().endswith(".vrm"):
        raise HTTPException(status_code=400, detail="Invalid file type")
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Model file not found")
    try:
        os.remove(file_path)
        logger.info(f"Deleted model file: {file_path}")
        return {"status": "ok", "message": f"Model {filename} deleted successfully"}
    except Exception as e:
        logger.error(f"Error deleting model {filename}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete model: {str(e)}")


# ── Store ─────────────────────────────────────────────────────────────────────

class StoreDownloadRequest(BaseModel):
    url: str
    type: str   # "model" or "animation"
    name: str


@router.get("/api/store/list")
async def get_store_index():
    """Fetch the store index JSON from local mock file."""
    index_path = str(_APP_BASE / "data" / "store_index.json")
    if not os.path.exists(index_path):
        return {"models": [], "animations": []}
    with open(index_path, "r", encoding="utf-8") as f:
        return json.load(f)


@router.post("/api/store/download")
async def download_store_item(req: StoreDownloadRequest, background_tasks: BackgroundTasks):
    """Asynchronously download a model or animation from the store URL."""
    if req.type == "model":
        target_dir = os.path.join("static", "models")
        filename = f"{req.name}.vrm"
    elif req.type == "animation":
        target_dir = os.path.join("static", "vrm", "animation")
        filename = f"{req.name}.vrma"
    else:
        raise HTTPException(status_code=400, detail="Invalid resource type")

    os.makedirs(target_dir, exist_ok=True)
    file_path = os.path.join(target_dir, filename)

    async def _download_task():
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=60.0) as client:
                async with client.stream("GET", req.url) as response:
                    response.raise_for_status()
                    with open(file_path, "wb") as f:
                        async for chunk in response.aiter_bytes():
                            f.write(chunk)
            logger.info(f"Downloaded {req.type} to {file_path}")
        except Exception as e:
            logger.error(f"Failed to download {req.url}: {e}")
            if os.path.exists(file_path):
                os.remove(file_path)

    background_tasks.add_task(_download_task)
    return {"status": "started", "message": f"Downloading {req.name} in background..."}
