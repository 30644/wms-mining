"""
系统数据备份
端点: /api/system/backup | list | download/{filename} | delete/{filename}
"""
import os, shutil, glob
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from app.routes.auth import get_current_user

router = APIRouter()

BACKUP_DIR = Path(__file__).resolve().parent.parent.parent / "backups"
DB_PATH = Path(__file__).resolve().parent.parent.parent / "warehouse.db"


def _ensure_backup_dir():
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)


def _backup_filename():
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"backup_{ts}.db"


@router.post("/create", summary="立即备份数据库")
async def create_backup(_=Depends(get_current_user)):
    _ensure_backup_dir()
    filename = _backup_filename()
    dst = BACKUP_DIR / filename
    shutil.copy2(str(DB_PATH), str(dst))
    size = dst.stat().st_size
    return {"code": 0, "message": "备份成功", "data": {
        "filename": filename, "size": size,
        "created_at": datetime.fromtimestamp(dst.stat().st_mtime).isoformat()
    }}


@router.get("/list", summary="获取备份文件列表")
async def list_backups(_=Depends(get_current_user)):
    _ensure_backup_dir()
    files = []
    for f in sorted(BACKUP_DIR.glob("backup_*.db"), reverse=True):
        stat = f.stat()
        files.append({
            "filename": f.name,
            "size": stat.st_size,
            "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat()
        })
    return {"code": 0, "data": {"list": files}}


@router.get("/download/{filename}", summary="下载备份文件")
async def download_backup(filename: str, _=Depends(get_current_user)):
    _ensure_backup_dir()
    path = BACKUP_DIR / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="备份文件不存在")
    return FileResponse(str(path), filename=filename,
                        media_type="application/octet-stream")


@router.delete("/{filename}", summary="删除备份文件")
async def delete_backup(filename: str, _=Depends(get_current_user)):
    _ensure_backup_dir()
    path = BACKUP_DIR / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="备份文件不存在")
    os.remove(str(path))
    return {"code": 0, "message": "备份文件已删除"}


@router.post("/{filename}/restore", summary="恢复备份")
async def restore_backup(filename: str, _=Depends(get_current_user)):
    _ensure_backup_dir()
    src = BACKUP_DIR / filename
    if not src.exists():
        raise HTTPException(status_code=404, detail="备份文件不存在")
    # 先备份当前数据库
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    pre_restore = BACKUP_DIR / f"pre_restore_{ts}.db"
    shutil.copy2(str(DB_PATH), str(pre_restore))
    # 恢复
    shutil.copy2(str(src), str(DB_PATH))
    return {"code": 0, "message": f"已从 {filename} 恢复数据库，恢复前备份为 {pre_restore.name}"}
