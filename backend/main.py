from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .analysis import CATEGORIES, inspect, map_image, report_markdown
from .explain import explain as build_explanation
from .live_api import router as live_router
from .assistant_api import router as assistant_router
from .sample_data import load_communities
from .display_config import display_config

ROOT = Path(__file__).resolve().parents[1]
COMMUNITIES = load_communities()
app = FastAPI(
    title="邻里圈 API",
    version="0.7.0",
    description="生活圈体检与受约束模型工具调用；合成、历史回放和当前百度数据明确分离。",
)
app.include_router(live_router)
app.include_router(assistant_router)


@app.middleware("http")
async def revalidate_public_pages(request, call_next):
    response = await call_next(request)
    if request.url.path in {
        "/",
        "/diagnosis.html",
        "/home.js",
        "/live",
        "/live.html",
        "/app.js",
        "/live.js",
        "/assistant.html",
        "/assistant.js",
        "/assistant-state.js",
        "/workspace-ui.js",
        "/workspace-store.js",
        "/workspace.css",
        "/styles.css",
    }:
        response.headers["Cache-Control"] = "no-cache"
    return response


def community_by_id(community_id):
    if community_id not in COMMUNITIES:
        raise HTTPException(404, "社区样例不存在")
    return COMMUNITIES[community_id]


def categories_from_text(category):
    if not category or category == "全部":
        return list(CATEGORIES)
    values = list(dict.fromkeys(category.split(",")))
    if any(c not in CATEGORIES for c in values):
        raise HTTPException(400, "设施类别无效")
    return [c for c in CATEGORIES if c in values]


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "mode": "synthetic",
        "version": app.version,
        "baidu_connected": False,
        "baidu_adapter": "ready",
        "llm_connected": False,
    }


@app.get("/api/map/display-config")
def browser_map_config():
    from fastapi.responses import JSONResponse

    return JSONResponse(display_config(), headers={"Cache-Control": "no-store"})


@app.get("/geo-map.js", include_in_schema=False)
def geographic_map_script():
    return FileResponse(
        ROOT / "geo-map.js", media_type="application/javascript", headers={"Cache-Control": "no-cache"}
    )


@app.get("/assistant-state.js", include_in_schema=False)
def assistant_state_script():
    return FileResponse(ROOT / "assistant-state.js", media_type="application/javascript")


@app.get("/api/communities")
def list_communities():
    return [{"id": s["id"], "name": s["name"]} for s in COMMUNITIES.values()]


@app.get("/api/communities/{community_id}/inspection")
def inspect_community(
    community_id: str,
    category: str = "全部",
    minutes: Annotated[int, Query(ge=5, le=30)] = 15,
    speed: Annotated[int, Query(ge=40, le=100)] = 80,
    center: str | None = None,
    addition_node: str | None = None,
    addition_category: str | None = None,
):
    if bool(addition_node) != bool(addition_category):
        raise HTTPException(400, "候选点和设施类别需同时提供")
    addition = {"node": addition_node, "category": addition_category} if addition_node else None
    try:
        return inspect(
            community_by_id(community_id), categories_from_text(category), minutes, speed, center, addition
        )
    except ValueError as error:
        raise HTTPException(400, str(error)) from error


@app.get("/api/communities/{community_id}/map.png")
def community_map(community_id: str):
    return Response(map_image(community_by_id(community_id)), media_type="image/png")


class AgentRequest(BaseModel):
    community_id: str = "bridge-demo"
    request: str = Field(min_length=1, max_length=500)
    minutes: int = Field(default=15, ge=5, le=30)
    speed: int = Field(default=80, ge=40, le=100)
    center: str | None = None


@app.post("/api/agent/inspect")
def agent_inspect(payload: AgentRequest):
    if not payload.request.strip():
        raise HTTPException(400, "需求不能为空")
    categories = [c for c in CATEGORIES if c in payload.request]
    if not categories:
        raise HTTPException(400, "未识别到设施类别；支持医疗、养老、教育、购物。未执行体检。")
    result = inspect_community(
        payload.community_id, ",".join(categories), payload.minutes, payload.speed, payload.center
    )
    explanation = build_explanation(result)
    result["intent"] = {"mode": "keyword_rules", "categories": categories, "llm_called": False}
    result["explanation"] = explanation
    return result


class ReportRequest(BaseModel):
    community_id: str
    category: str = "全部"
    minutes: int = Field(default=15, ge=5, le=30)
    speed: int = Field(default=80, ge=40, le=100)
    center: str | None = None
    addition_node: str | None = None
    addition_category: str | None = None


@app.post("/api/report")
def export_report(payload: ReportRequest):
    result = inspect_community(**payload.model_dump())
    return Response(
        report_markdown(result),
        media_type="text/markdown",
        headers={"Content-Disposition": f"attachment; filename=inspection-{result['evidence_id']}.md"},
    )


# Only explicitly public assets are served; never mount the repository root.
@app.get("/")
def index():
    return FileResponse(ROOT / "home.html")


@app.get("/diagnosis.html")
def synthetic_workspace():
    return FileResponse(ROOT / "index.html")


@app.get("/home.js")
def home_script():
    return FileResponse(ROOT / "home.js", media_type="application/javascript")


@app.get("/workspace.css")
def workspace_styles():
    return FileResponse(ROOT / "workspace.css", media_type="text/css")


@app.get("/workspace-ui.js")
def workspace_ui_script():
    return FileResponse(ROOT / "workspace-ui.js", media_type="application/javascript")


@app.get("/workspace-store.js")
def workspace_store_script():
    return FileResponse(ROOT / "workspace-store.js", media_type="application/javascript")


@app.get("/app.js")
def javascript():
    return FileResponse(ROOT / "app.js", media_type="text/javascript")


@app.get("/live")
@app.get("/live.html")
def live_page():
    return FileResponse(ROOT / "live.html")


@app.get("/live.js")
def live_javascript():
    return FileResponse(ROOT / "live.js", media_type="text/javascript")


@app.get("/styles.css")
def stylesheet():
    return FileResponse(ROOT / "styles.css", media_type="text/css")


@app.get("/assistant.html")
def assistant_page():
    return FileResponse(ROOT / "assistant.html")


@app.get("/assistant.js")
def assistant_javascript():
    return FileResponse(ROOT / "assistant.js", media_type="text/javascript")


app.mount("/assets", StaticFiles(directory=ROOT / "assets", check_dir=False), name="assets")
