"""Files API routes — provides a shared filesystem for agents"""
import os
import shutil
import mimetypes
from pathlib import Path
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from typing import Optional
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/files", tags=["files"])

FILES_ROOT = os.environ.get("AGENT_FILES_ROOT", "/agent-files")


def _safe_path(user_path: str) -> Path:
    """Resolve user path inside FILES_ROOT, reject traversal attempts."""
    base = Path(FILES_ROOT).resolve()
    target = (base / user_path.lstrip("/")).resolve()
    if not str(target).startswith(str(base)):
        raise HTTPException(status_code=400, detail="Path traversal not allowed")
    return target


class FileInfo(BaseModel):
    name: str
    path: str
    is_dir: bool
    size: int | None = None
    modified: str | None = None
    mime_type: str | None = None


class WriteRequest(BaseModel):
    content: str
    path: str


@router.get("/")
async def list_files(prefix: str = ""):
    """List files and directories at the given prefix."""
    target = _safe_path(prefix)
    if not target.exists():
        return {"path": prefix, "files": []}
    if not target.is_dir():
        raise HTTPException(status_code=400, detail="Path is not a directory")

    entries = []
    for entry in sorted(target.iterdir()):
        rel = str(entry.relative_to(Path(FILES_ROOT).resolve()))
        info = FileInfo(name=entry.name, path=rel, is_dir=entry.is_dir())
        if entry.is_file():
            stat = entry.stat()
            info.size = stat.st_size
            info.modified = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
            info.mime_type = mimetypes.guess_type(entry.name)[0]
        entries.append(info)

    return {"path": prefix, "files": [e.model_dump() for e in entries]}


@router.get("/read/{file_path:path}")
async def read_file(file_path: str):
    """Read a file. Returns text content for text files, download for binary."""
    target = _safe_path(file_path)
    if not target.exists():
        raise HTTPException(status_code=404, detail="File not found")
    if target.is_dir():
        raise HTTPException(status_code=400, detail="Path is a directory, use list endpoint")

    mime = mimetypes.guess_type(target.name)[0] or "application/octet-stream"

    if mime.startswith("text/") or mime in ("application/json", "application/xml", "application/yaml"):
        try:
            content = target.read_text(encoding="utf-8")
            return {
                "path": file_path,
                "content": content,
                "size": target.stat().st_size,
                "mime_type": mime,
            }
        except UnicodeDecodeError:
            pass

    return FileResponse(
        path=str(target),
        media_type=mime,
        filename=target.name,
    )


@router.post("/write")
async def write_text_file(req: WriteRequest):
    """Write text content to a file. Creates parent directories as needed."""
    target = _safe_path(req.path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(req.content, encoding="utf-8")
    logger.info(f"File written: {req.path} ({len(req.content)} chars)")
    return {
        "path": req.path,
        "size": target.stat().st_size,
        "message": "File written successfully",
    }


@router.post("/upload/{file_path:path}")
async def upload_file(file_path: str, file: UploadFile = File(...)):
    """Upload a binary file (images, media, etc). Creates parent directories."""
    target = _safe_path(file_path)
    target.parent.mkdir(parents=True, exist_ok=True)

    with open(target, "wb") as f:
        shutil.copyfileobj(file.file, f)

    size = target.stat().st_size
    logger.info(f"File uploaded: {file_path} ({size} bytes)")
    return {
        "path": file_path,
        "size": size,
        "mime_type": mimetypes.guess_type(target.name)[0],
        "message": "File uploaded successfully",
    }


@router.delete("/{file_path:path}")
async def delete_file(file_path: str):
    """Delete a file or empty directory."""
    target = _safe_path(file_path)
    if not target.exists():
        raise HTTPException(status_code=404, detail="File not found")

    if target.is_dir():
        if any(target.iterdir()):
            raise HTTPException(status_code=400, detail="Directory is not empty")
        target.rmdir()
    else:
        target.unlink()

    logger.info(f"File deleted: {file_path}")
    return {"path": file_path, "message": "Deleted successfully"}


@router.get("/info/{file_path:path}")
async def file_info(file_path: str):
    """Get metadata about a file or directory."""
    target = _safe_path(file_path)
    if not target.exists():
        raise HTTPException(status_code=404, detail="File not found")

    stat = target.stat()
    return FileInfo(
        name=target.name,
        path=file_path,
        is_dir=target.is_dir(),
        size=stat.st_size if target.is_file() else None,
        modified=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        mime_type=mimetypes.guess_type(target.name)[0] if target.is_file() else None,
    ).model_dump()


@router.post("/mkdir/{dir_path:path}")
async def make_directory(dir_path: str):
    """Create a directory (and parents)."""
    target = _safe_path(dir_path)
    target.mkdir(parents=True, exist_ok=True)
    return {"path": dir_path, "message": "Directory created"}
