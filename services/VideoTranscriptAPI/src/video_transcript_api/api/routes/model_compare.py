from __future__ import annotations

import html
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

from ..context import get_config
from ..services.model_compare import (
    ModelCompareConfigError,
    get_model_compare_job,
    submit_model_compare_job,
)
from ..services.transcription import verify_token

router = APIRouter(tags=["model-compare"])


class ModelCompareRequest(BaseModel):
    url: str = Field(min_length=1)
    enable_thinking: bool = False


@router.post("/api/model-compare", status_code=202)
async def create_model_compare_job(
    payload: ModelCompareRequest,
    user_info: dict = Depends(verify_token),
) -> dict[str, object]:
    try:
        job = submit_model_compare_job(
            payload.url,
            get_config(),
            enable_thinking=payload.enable_thinking,
        )
    except ModelCompareConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "job": _with_file_urls(job)}


@router.get("/api/model-compare/{job_id}")
async def get_model_compare_job_api(
    job_id: str,
    user_info: dict = Depends(verify_token),
) -> dict[str, object]:
    job = get_model_compare_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="model compare job not found")
    return {"ok": True, "job": _with_file_urls(job)}


@router.get("/model-compare/{job_id}", response_class=HTMLResponse)
async def get_model_compare_directory(job_id: str) -> HTMLResponse:
    job = get_model_compare_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="model compare job not found")
    return HTMLResponse(_render_directory_html(_with_file_urls(job)))


@router.get("/model-compare/{job_id}/{filename}")
async def get_model_compare_file(job_id: str, filename: str) -> FileResponse:
    job = get_model_compare_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="model compare job not found")

    output_dir = Path(str(job.get("output_dir") or "")).resolve()
    requested = (output_dir / filename).resolve()
    try:
        requested.relative_to(output_dir)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid filename") from exc

    if not requested.exists() or not requested.is_file():
        raise HTTPException(status_code=404, detail="file not found")
    return FileResponse(str(requested), filename=requested.name)


def _with_file_urls(job: dict) -> dict:
    job = dict(job)
    job["directory_url"] = f"/model-compare/{job['job_id']}"
    links = []
    for item in job.get("file_links") or []:
        link = dict(item)
        if not link.get("url"):
            link["url"] = f"/model-compare/{job['job_id']}/{link['filename']}"
        links.append(link)
    job["file_links"] = links
    return job


def _render_directory_html(job: dict) -> str:
    title = html.escape(job.get("title") or "校对对比结果")
    status = html.escape(job.get("status_label") or job.get("status") or "")
    message = html.escape(job.get("message") or "")
    output_dir = html.escape(job.get("output_dir") or "")
    file_items = []
    for link in job.get("file_links") or []:
        label = html.escape(link.get("label") or link.get("filename") or "file")
        url = html.escape(link.get("url") or "#")
        filename = html.escape(link.get("filename") or "")
        file_items.append(f'<li><a href="{url}">{label}</a><span>{filename}</span></li>')
    if not file_items:
        file_items.append("<li><span>文件还在生成中</span></li>")

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title} - 模型校对对比</title>
  <style>
    body {{ margin: 0; padding: 28px; font-family: "Segoe UI", "Noto Sans SC", sans-serif; color: #172033; background: #f5f7fb; }}
    main {{ max-width: 860px; margin: 0 auto; }}
    section {{ border: 1px solid #d9e2ec; border-radius: 8px; background: #fff; padding: 22px; box-shadow: 0 8px 20px rgba(15, 23, 42, 0.06); }}
    h1 {{ margin: 0 0 10px; font-size: 1.5rem; }}
    p {{ color: #475569; line-height: 1.7; }}
    code {{ word-break: break-all; }}
    ul {{ display: grid; gap: 10px; padding: 0; list-style: none; }}
    li {{ display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1.2fr); gap: 12px; border: 1px solid #d9e2ec; border-radius: 6px; padding: 12px; background: #f8fafc; }}
    a {{ color: #1d4ed8; font-weight: 700; }}
    span {{ color: #64748b; word-break: break-all; }}
  </style>
</head>
<body>
  <main>
    <section>
      <h1>{title}</h1>
      <p>状态：{status}。{message}</p>
      <p>目录：<code>{output_dir}</code></p>
      <ul>
        {''.join(file_items)}
      </ul>
    </section>
  </main>
</body>
</html>"""
