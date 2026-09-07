from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, Response


router = APIRouter(tags=["dashboard"])

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'none'; "
        "script-src 'self'; "
        "style-src 'self'; "
        "connect-src 'self'; "
        "img-src 'self'; "
        "font-src 'self'; "
        "object-src 'none'; "
        "base-uri 'none'; "
        "form-action 'none'; "
        "frame-ancestors 'none'"
    ),
    "Cross-Origin-Opener-Policy": "same-origin",
    "Permissions-Policy": "camera=(), geolocation=(), microphone=(), payment=(), usb=()",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
}


INDEX_DOCUMENT = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
STYLESHEET = (STATIC_DIR / "styles.css").read_text(encoding="utf-8")
APPLICATION_SCRIPT = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
MASCOT_ASSET = (STATIC_DIR / "assets" / "booruradar-mascot.png").read_bytes()
WORDMARK_ASSET = (STATIC_DIR / "assets" / "booruradar-wordmark.svg").read_bytes()
ICON_ASSET = (STATIC_DIR / "assets" / "booruradar-icon.svg").read_bytes()
FONT_ASSET = (STATIC_DIR / "assets" / "manrope-latin.woff2").read_bytes()


def _asset_response(content: str | bytes, media_type: str) -> Response:
    return Response(
        content=content,
        media_type=media_type,
        headers={
            **SECURITY_HEADERS,
            "Cache-Control": "public, max-age=3600",
        },
    )


@router.get("/assets/styles.css", include_in_schema=False)
async def stylesheet() -> Response:
    return _asset_response(STYLESHEET, "text/css")


@router.get("/assets/app.js", include_in_schema=False)
async def application_script() -> Response:
    return _asset_response(APPLICATION_SCRIPT, "text/javascript")


@router.get("/assets/booruradar-mascot.png", include_in_schema=False)
async def mascot_asset() -> Response:
    return Response(
        content=MASCOT_ASSET,
        media_type="image/png",
        headers={
            **SECURITY_HEADERS,
            "Cache-Control": "public, max-age=86400",
        },
    )


@router.get("/assets/booruradar-wordmark.svg", include_in_schema=False)
async def wordmark_asset() -> Response:
    return _asset_response(WORDMARK_ASSET, "image/svg+xml")


@router.get("/assets/booruradar-icon.svg", include_in_schema=False)
async def icon_asset() -> Response:
    return _asset_response(ICON_ASSET, "image/svg+xml")


@router.get("/assets/manrope-latin.woff2", include_in_schema=False)
async def font_asset() -> Response:
    return _asset_response(FONT_ASSET, "font/woff2")


@router.get("/", include_in_schema=False, response_class=HTMLResponse)
async def dashboard() -> HTMLResponse:
    return HTMLResponse(
        content=INDEX_DOCUMENT,
        headers={
            **SECURITY_HEADERS,
            "Cache-Control": "no-cache",
        },
    )
