"""Skills management, marketplace, install/uninstall routes."""
import time
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.state import app_state, _APP_BASE, logger

router = APIRouter(tags=["skills"])

# Marketplace cache: query → (timestamp, data)
_marketplace_cache: dict = {}
_MARKETPLACE_CACHE_TTL = 60  # seconds


# ── Pydantic models ───────────────────────────────────────────────────────────

class SkillToggleRequest(BaseModel):
    name: str
    enabled: bool
    tools: Optional[list[str]] = None  # None=not provided, []=catalog-only entry


class SkillConfigRequest(BaseModel):
    name: str
    config: Dict[str, Any]


class SkillInstallRequest(BaseModel):
    url: str
    name: str = ""


class SkillUninstallRequest(BaseModel):
    name: str


# ── Helpers ───────────────────────────────────────────────────────────────────

def _require_agent():
    agent = app_state.get("agent")
    if not agent:
        raise HTTPException(status_code=500, detail="Agent not initialized")
    return agent


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/api/skills/list")
async def list_skills():
    """Return unified skill list merging registry categories and local catalog."""
    agent = _require_agent()

    # category → [tools]
    category_map: dict = {}
    for skill in agent.skills._registry.values():
        cat = skill.category or "general"
        category_map.setdefault(cat, []).append(skill)

    local_catalog = getattr(agent, "_local_skills_catalog", {})
    final_skills = []
    seen_categories: set = set()

    catalog_alias_map = {"agent-browser": "browser", "file-manager": "filesystem"}

    for name, info in local_catalog.items():
        cat_key = catalog_alias_map.get(name, name)
        if cat_key not in category_map:
            cat_key = name
        tools = category_map.get(cat_key, [])
        description = info.get("description", "") or (tools[0].description if tools else "")
        final_skills.append({
            "id": name, "name": name, "description": description,
            "category": "agent_skill", "registry_category": cat_key,
            "tools": [t.name for t in tools],
            "enabled": any(t.enabled for t in tools) if tools else True,
        })
        seen_categories.add(cat_key)
        seen_categories.add(name)

    for cat_name, tools in category_map.items():
        if cat_name not in seen_categories:
            final_skills.append({
                "id": cat_name, "name": cat_name,
                "description": tools[0].description if tools else "",
                "category": "system_skill", "registry_category": cat_name,
                "tools": [t.name for t in tools],
                "enabled": all(t.enabled for t in tools),
            })

    return {"skills": final_skills}


@router.post("/api/skills/config")
async def config_skill(request: SkillConfigRequest):
    """Update a skill's configuration values."""
    agent = _require_agent()
    skill = agent.skills.get(request.name)
    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill '{request.name}' not found")
    agent.skills.update_config(request.name, request.config)
    return {"status": "success", "name": request.name, "config_values": skill.config_values}


@router.post("/api/skills/toggle")
async def toggle_skill(request: SkillToggleRequest):
    """Enable or disable a skill by tool name, category, or tools list."""
    agent = _require_agent()

    def _apply(names):
        for n in names:
            agent.skills.enable(n) if request.enabled else agent.skills.disable(n)

    # 1. Explicit tools list
    if request.tools is not None:
        valid = [t for t in request.tools if agent.skills.get(t)]
        if valid:
            _apply(valid)
        return {"status": "success", "name": request.name, "enabled": request.enabled, "affected": len(valid)}

    # 2. Direct tool name
    if agent.skills.get(request.name):
        _apply([request.name])
        return {"status": "success", "name": request.name, "enabled": request.enabled, "affected": 1}

    # 3. Category match
    matched = [s for s in agent.skills._registry.values() if (s.category or "general") == request.name]
    if matched:
        _apply([s.name for s in matched])
        return {"status": "success", "name": request.name, "enabled": request.enabled, "affected": len(matched)}

    # 4. Catalog alias → category
    alias_map = {"agent-browser": "browser", "file-manager": "file_manager"}
    cat_key = alias_map.get(request.name, request.name)
    if cat_key != request.name:
        matched = [s for s in agent.skills._registry.values() if (s.category or "general") == cat_key]
        if matched:
            _apply([s.name for s in matched])
            return {"status": "success", "name": request.name, "enabled": request.enabled, "affected": len(matched)}

    all_categories = sorted(set(s.category or "general" for s in agent.skills._registry.values()))
    raise HTTPException(
        status_code=404,
        detail=f"Skill or category '{request.name}' not found. Available: {all_categories}",
    )


@router.post("/api/skills/reload")
async def reload_skills():
    """Reload all skill modules (via PluginManager)."""
    agent = _require_agent()
    try:
        plugin_manager = app_state.get("plugin_manager")
        if plugin_manager:
            reloaded = plugin_manager.reload_all()
            logger.info(f"[SkillReload] Reloaded {len(reloaded)} plugins: {reloaded}")
        if hasattr(agent, "_scan_local_skills"):
            agent._local_skills_catalog = agent._scan_local_skills()
            agent._catalog_dirty = False
        return {"status": "success", "message": f"已重载 {len(reloaded) if plugin_manager else 0} 个插件"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to reload skills: {str(e)}")


@router.get("/api/skills/marketplace")
async def skills_marketplace(q: str = "agent"):
    """Proxy requests to skills.sh with 60s cache per query."""
    try:
        import httpx
    except ImportError:
        import subprocess, sys
        subprocess.run([sys.executable, "-m", "pip", "install", "httpx", "-q"], check=False)
        try:
            import httpx
        except ImportError:
            return {"skills": [], "error": "httpx not available"}

    q = q.strip() or "agent"
    cache_key = q.lower()
    now = time.time()
    if cache_key in _marketplace_cache:
        ts, cached = _marketplace_cache[cache_key]
        if now - ts < _MARKETPLACE_CACHE_TTL:
            return cached

    agent = app_state.get("agent")
    data = None
    timeout_val = 20.0
    url = f"https://skills.sh/api/search?q={q}"
    headers = {"User-Agent": "openGuiclaw/1.0"}

    try:
        async with httpx.AsyncClient(timeout=timeout_val, trust_env=True) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()
    except (httpx.ConnectTimeout, httpx.ConnectError, httpx.HTTPStatusError) as e:
        try:
            from httpx import AsyncHTTPTransport
            transport = AsyncHTTPTransport(local_address="0.0.0.0")
            async with httpx.AsyncClient(timeout=timeout_val + 5, transport=transport, trust_env=True) as client:
                resp = await client.get(url, headers=headers)
                resp.raise_for_status()
                data = resp.json()
        except Exception:
            return {"skills": [], "error": f"连接插件库(skills.sh)失败: {str(e)}"}
    except Exception as e:
        return {"skills": [], "error": f"同步异常: {str(e)}"}

    if not data:
        return {"skills": [], "error": "无法获取插件数据"}

    installed_urls: set = set()
    if agent:
        for skill in agent.skills._registry.values():
            src = getattr(skill, "source_url", None) or getattr(skill, "sourceUrl", None)
            if src:
                installed_urls.add(src)

    enriched = []
    for s in data.get("skills", []):
        source = str(s.get("source", ""))
        skill_id = str(s.get("skillId", s.get("name", "")))
        install_url = f"{source}@{skill_id}" if source else skill_id
        description = s.get("description") or skill_id.replace("-", " ").replace("_", " ").title()
        tags: list = list(s.get("tags", []) or [])
        if not tags:
            if "/" in source:
                author = source.split("/")[0]
                if author not in tags:
                    tags.append(author)
            cat = s.get("category")
            if cat and cat not in tags:
                tags.append(cat.lower())
        enriched.append({
            "id": str(s.get("id", "")), "name": skill_id, "description": str(description),
            "author": source.split("/")[0] if source else "community",
            "url": install_url, "installs": s.get("installs", 0), "stars": s.get("stars", 0),
            "tags": tags, "installed": install_url in installed_urls,
        })

    result = {"skills": enriched}
    _marketplace_cache[cache_key] = (now, result)
    return result


@router.post("/api/skills/install")
async def install_skill(request: SkillInstallRequest):
    """Install a skill from a URL via pip or mirror fallback."""
    import io, os, shutil, subprocess, sys, tempfile, urllib.request, zipfile
    agent = _require_agent()
    url = request.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="URL is required")

    install_ok = False
    install_msg = ""
    error_detail = ""

    base_url = url
    sub_target = ""
    if "@" in url and "git+" not in url:
        base_url, sub_target = url.split("@", 1)

    # Strategy 1: direct pip
    try:
        if base_url.startswith(("http://", "https://")):
            pip_url = f"git+{base_url}"
        elif "/" in base_url and not base_url.startswith("git+"):
            pip_url = f"git+https://github.com/{base_url}"
        else:
            pip_url = base_url
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", pip_url, "--quiet"],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode == 0:
            install_ok = True
            install_msg = f"Skill installed: {request.name or url}"
        else:
            error_detail = result.stderr or "pip install failed"
    except Exception as e:
        error_detail = str(e)

    # Strategy 2: GitHub mirror fallback
    if not install_ok and ("github.com" in base_url or "/" in base_url):
        mirrors = [
            "https://gh-proxy.com/https://github.com/{owner}/{repo}/archive/refs/heads/{branch}.zip",
            "https://mirror.ghproxy.com/https://github.com/{owner}/{repo}/archive/refs/heads/{branch}.zip",
            "https://ghproxy.net/https://github.com/{owner}/{repo}/archive/refs/heads/{branch}.zip",
            "https://github.com/{owner}/{repo}/archive/refs/heads/{branch}.zip",
        ]
        owner = repo = ""
        if "github.com/" in base_url:
            parts = base_url.split("github.com/")[1].split("/")
            if len(parts) >= 2:
                owner, repo = parts[0], parts[1].replace(".git", "")
        elif "/" in base_url:
            parts = base_url.split("/")
            owner, repo = parts[0], parts[1]

        if owner and repo:
            for branch in ["main", "master"]:
                if install_ok:
                    break
                for mirror_tpl in mirrors:
                    download_url = mirror_tpl.format(owner=owner, repo=repo, branch=branch)
                    try:
                        req = urllib.request.Request(download_url, headers={"User-Agent": "Mozilla/5.0"})
                        with urllib.request.urlopen(req, timeout=30) as response:
                            zip_data = response.read()
                        with tempfile.TemporaryDirectory() as tmpdir:
                            with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
                                zf.extractall(tmpdir)
                            items = os.listdir(tmpdir)
                            if not items:
                                continue
                            src_path = os.path.join(tmpdir, items[0])
                            res = subprocess.run(
                                [sys.executable, "-m", "pip", "install", src_path, "--quiet"],
                                capture_output=True, text=True, timeout=60,
                            )
                            if res.returncode == 0:
                                install_ok = True
                                install_msg = f"Skill installed via mirror: {request.name or url}"
                                break
                            potential_dir = src_path
                            if sub_target:
                                candidate = os.path.join(src_path, sub_target)
                                if os.path.isdir(candidate):
                                    potential_dir = candidate
                            if os.path.exists(os.path.join(potential_dir, "SKILL.md")):
                                target_name = request.name or os.path.basename(potential_dir)
                                if target_name in ["archive", "master", "main"]:
                                    target_name = repo or os.path.basename(base_url.rstrip("/"))
                                dest_dir = Path(".agents/skills") / target_name
                                os.makedirs(dest_dir.parent, exist_ok=True)
                                if os.path.exists(dest_dir):
                                    shutil.rmtree(dest_dir)
                                shutil.copytree(potential_dir, dest_dir)
                                install_ok = True
                                install_msg = f"Natively installed skill folder: {target_name}"
                                break
                            else:
                                error_detail = res.stderr or "pip failed and no SKILL.md found"
                    except Exception as e:
                        error_detail = str(e)
                        continue

    if not install_ok:
        raise HTTPException(status_code=504, detail=f"安装失败: {error_detail}")

    # Hot-reload
    try:
        if hasattr(agent, "_catalog_dirty"):
            agent._catalog_dirty = True
            if hasattr(agent, "_scan_local_skills"):
                agent._local_skills_catalog = agent._scan_local_skills()
        if hasattr(agent, "_register_builtins"):
            agent._register_builtins()
        plugin_manager = app_state.get("plugin_manager")
        if plugin_manager:
            plugin_manager.reload_all()
        if hasattr(agent, "skills") and hasattr(agent.skills, "_load_config"):
            agent.skills._load_config()
    except Exception as e:
        logger.warning(f"[SkillInstall] Reload warning: {e}")

    return {"status": "success", "message": install_msg, "source_url": url}


@router.post("/api/skills/uninstall")
async def uninstall_skill(request: SkillUninstallRequest):
    """Uninstall an external skill by name."""
    import subprocess, sys
    agent = _require_agent()
    skill = agent.skills.get(request.name)
    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill '{request.name}' not found")
    if not getattr(skill, "source_url", None):
        raise HTTPException(status_code=400, detail=f"'{request.name}' is a built-in skill and cannot be uninstalled")
    pkg_name = request.name.replace("_", "-")
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "uninstall", pkg_name, "-y", "--quiet"],
            capture_output=True, text=True, timeout=60,
        )
    except Exception as e:
        logger.warning(f"pip uninstall warning for {pkg_name}: {e}")
    try:
        if request.name in agent.skills._registry:
            del agent.skills._registry[request.name]
    except Exception as e:
        logger.warning(f"Failed to remove {request.name} from registry: {e}")
    return {"status": "success", "message": f"Skill '{request.name}' uninstalled"}
