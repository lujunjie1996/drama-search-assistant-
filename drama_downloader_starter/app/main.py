# sqlite3打包修复补丁
__import__('pysqlite3')
import sys
sys.modules['sqlite3'] = sys.modules.pop('pysqlite3')
import os, re, uuid, json, asyncio, sqlite3, hashlib, shutil
from pathlib import Path
from urllib.parse import urlparse
from datetime import datetime, timezone
import aiohttp
from fastapi import FastAPI, Header, HTTPException, Depends, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, HttpUrl, field_validator

DATA = Path(os.getenv("DATA_DIR", "./data")).resolve()
DATA.mkdir(parents=True, exist_ok=True)
DB = DATA / "tasks.sqlite3"
HOSTS = {x.strip().lower() for x in os.getenv("ALLOWED_DOWNLOAD_HOSTS","").split(",") if x.strip()}
API_KEY = os.getenv("API_KEY","").strip()
CONCURRENCY = max(1, int(os.getenv("MAX_CONCURRENT_DOWNLOADS","3")))
RETRIES = max(0, int(os.getenv("MAX_RETRIES","4")))
FFMPEG = os.getenv("FFMPEG_BIN","ffmpeg")
CHUNK = 1024 * 1024
sem = asyncio.Semaphore(CONCURRENCY)
cancelled = set()
tasks = set()
app = FastAPI(title="短剧搜索助手 · 全集下载 API", version="0.1.0")


@app.get("/", include_in_schema=False)
async def home():
    return FileResponse(Path(__file__).parent / "static" / "index.html")


class Episode(BaseModel):
    episode_number: int = Field(ge=1, le=10000)
    title: str = ""
    download_url: HttpUrl
    referer: HttpUrl | None = None
    expected_size: int | None = Field(default=None, ge=0)
    sha256: str | None = Field(default=None, pattern=r"^[a-fA-F0-9]{64}$")

class SeriesIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    provider: str = "authorized-json"
    episodes: list[Episode] = Field(min_length=1, max_length=3000)
    @field_validator("episodes")
    @classmethod
    def unique_eps(cls, v):
        nums=[e.episode_number for e in v]
        if len(nums)!=len(set(nums)): raise ValueError("episode_number must be unique")
        return sorted(v,key=lambda e:e.episode_number)

class DownloadIn(BaseModel):
    merge_after_download: bool = False


class CatalogItemIn(BaseModel):
    """A series record supplied by an owned or explicitly authorized catalog."""
    title: str = Field(min_length=1, max_length=200)
    provider: str = Field(default="authorized-catalog", min_length=1, max_length=80)
    keywords: list[str] = Field(default_factory=list, max_length=50)
    episodes: list[Episode] = Field(min_length=1, max_length=3000)
    rights_note: str = Field(min_length=3, max_length=500)

    @field_validator("episodes")
    @classmethod
    def unique_catalog_eps(cls, v):
        nums = [e.episode_number for e in v]
        if len(nums) != len(set(nums)):
            raise ValueError("episode_number must be unique")
        return sorted(v, key=lambda e: e.episode_number)

def db():
    c=sqlite3.connect(DB, timeout=30); c.row_factory=sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c

def init():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS series(id TEXT PRIMARY KEY,title TEXT,provider TEXT,created TEXT);
        CREATE TABLE IF NOT EXISTS episodes(id TEXT PRIMARY KEY,series_id TEXT,number INTEGER,title TEXT,url TEXT,referer TEXT,expected_size INTEGER,sha256 TEXT,status TEXT DEFAULT 'pending',bytes INTEGER DEFAULT 0,path TEXT,error TEXT,UNIQUE(series_id,number));
        CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,series_id TEXT,status TEXT,merge INTEGER,created TEXT,merged_path TEXT,error TEXT);
        CREATE TABLE IF NOT EXISTS job_eps(job_id TEXT,episode_id TEXT,PRIMARY KEY(job_id,episode_id));
        CREATE TABLE IF NOT EXISTS catalog(
          id TEXT PRIMARY KEY,title TEXT,provider TEXT,keywords TEXT,episodes_json TEXT,
          rights_note TEXT,created TEXT
        );
        """)
def auth(x_api_key: str | None = Header(default=None)):
    if API_KEY and x_api_key != API_KEY: raise HTTPException(401,"Invalid X-API-Key")

def validate_url(url):
    p=urlparse(url); host=(p.hostname or "").lower().rstrip(".")
    if p.scheme!="https": raise ValueError("Only HTTPS source URLs are accepted")
    if not HOSTS: raise ValueError("Configure ALLOWED_DOWNLOAD_HOSTS before queueing downloads")
    if not any(host==h or host.endswith("."+h) for h in HOSTS): raise ValueError("Host not in ALLOWED_DOWNLOAD_HOSTS")

def clean(s):
    s=re.sub(r'[<>:"/\\\\|?*\\x00-\\x1f]',"_",s).strip(" .")
    return (s or "untitled")[:120]

def episode_rows(job_id):
    with db() as c:
        job=c.execute("SELECT j.*,s.title FROM jobs j JOIN series s ON s.id=j.series_id WHERE j.id=?",(job_id,)).fetchone()
        if not job: return None,[]
        eps=c.execute("SELECT e.* FROM episodes e JOIN job_eps je ON je.episode_id=e.id WHERE je.job_id=? ORDER BY e.number",(job_id,)).fetchall()
    return dict(job),[dict(e) for e in eps]

def update_ep(eid, **kw):
    allowed={"status","bytes","path","error"}
    kw={k:v for k,v in kw.items() if k in allowed}
    if kw:
        with db() as c: c.execute("UPDATE episodes SET "+",".join(k+"=?" for k in kw)+" WHERE id=?",(*kw.values(),eid))

async def download_one(jobid, ep, series_title, series_id):
    if jobid in cancelled:
        update_ep(ep["id"],status="cancelled"); return False
    # Idempotency: do not download an episode again if its completed file still exists.
    if ep.get("status") == "completed" and ep.get("path") and Path(ep["path"]).is_file():
        return True
    try: validate_url(ep["url"])
    except Exception as ex:
        update_ep(ep["id"],status="failed",error=str(ex)); return False
    folder=DATA/"downloads"/(clean(series_title)+"_"+series_id[:8]); folder.mkdir(parents=True,exist_ok=True)
    final=folder/f"{clean(series_title)}_E{ep['number']:04d}.mp4"
    part=Path(str(final)+".part")
    timeout=aiohttp.ClientTimeout(total=None,sock_connect=30,sock_read=45)
    headers={"Referer":ep["referer"]} if ep["referer"] else {}
    for attempt in range(RETRIES+1):
        try:
            if jobid in cancelled: update_ep(ep["id"],status="cancelled"); return False
            async with sem:
                size=part.stat().st_size if part.exists() else 0
                h=dict(headers)
                if size: h["Range"]=f"bytes={size}-"
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(ep["url"],headers=h,allow_redirects=True) as r:
                        # Validate the final redirect target too, not only the original URL.
                        validate_url(str(r.url))
                        if size and r.status==200:
                            part.unlink(missing_ok=True); size=0
                        elif r.status not in (200,206): raise RuntimeError(f"HTTP {r.status}")
                        mode="ab" if r.status==206 and size else "wb"
                        update_ep(ep["id"],status="downloading",error=None)
                        with open(part,mode) as f:
                            async for chunk in r.content.iter_chunked(CHUNK):
                                if jobid in cancelled: update_ep(ep["id"],status="cancelled"); return False
                                f.write(chunk); f.flush()
                                update_ep(ep["id"],bytes=part.stat().st_size)
            actual=part.stat().st_size
            if ep["expected_size"] and actual!=ep["expected_size"]: raise RuntimeError("File size mismatch")
            if ep["sha256"]:
                h=hashlib.sha256()
                with open(part,"rb") as f:
                    for chunk in iter(lambda:f.read(CHUNK),b""): h.update(chunk)
                if h.hexdigest().lower()!=ep["sha256"].lower(): raise RuntimeError("SHA-256 mismatch")
            os.replace(part,final)
            update_ep(ep["id"],status="completed",bytes=actual,path=str(final),error=None)
            return True
        except Exception as ex:
            update_ep(ep["id"],status="retrying" if attempt<RETRIES else "failed",error=str(ex))
            if attempt<RETRIES: await asyncio.sleep(min(2**attempt,20))
    return False

async def merge_files(jobid, title, eps):
    if not shutil.which(FFMPEG): raise RuntimeError("FFmpeg not installed")
    folder=Path(eps[0]["path"]).parent
    lst=folder/f"concat_{jobid}.txt"; out=folder/f"{clean(title)}_FULL.mp4"
    def quote(p): return str(Path(p).resolve()).replace("'","'\\\\''")
    with open(lst,"w",encoding="utf-8") as f:
        for ep in eps: f.write("file '"+quote(ep["path"])+"'\n")
    proc=await asyncio.create_subprocess_exec(FFMPEG,"-hide_banner","-loglevel","error","-f","concat","-safe","0","-i",str(lst),"-c","copy","-y",str(out),stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
    _,err=await proc.communicate(); lst.unlink(missing_ok=True)
    if proc.returncode: raise RuntimeError("FFmpeg concat failed: "+err.decode("utf-8","replace")[-1000:])
    return str(out)

async def run_job(jobid):
    job,eps=episode_rows(jobid)
    if not job:return
    with db() as c:c.execute("UPDATE jobs SET status='running' WHERE id=?",(jobid,))
    await asyncio.gather(*(download_one(jobid,e,job["title"],job["series_id"]) for e in eps))
    job,eps=episode_rows(jobid)
    success=bool(eps) and all(e["status"]=="completed" for e in eps)
    merged=None; error=None
    if job["merge"] and success:
        try: merged=await merge_files(jobid,job["title"],eps)
        except Exception as ex:error=str(ex)
    status="cancelled" if jobid in cancelled else ("completed" if success and not error else ("partial" if any(e["status"]=="completed" for e in eps) else "failed"))
    with db() as c:c.execute("UPDATE jobs SET status=?,merged_path=?,error=? WHERE id=?",(status,merged,error,jobid))
    cancelled.discard(jobid)

@app.on_event("startup")
async def startup(): init()

@app.get("/health")
async def health(): return {"status":"ok","concurrency":CONCURRENCY,"download_hosts_configured":bool(HOSTS)}

@app.get("/api/providers",dependencies=[Depends(auth)])
async def providers():
    return {"providers":[
      {"name":"authorized-json","status":"ready","detail":"接受自有 API 或授权素材库提供的剧集清单"},
      {"name":"bilibili","status":"needs_configuration","detail":"需官方/合作 API 或授权素材源；搜索 API 不代表下载授权"},
      {"name":"douyin","status":"needs_configuration","detail":"需已获批开放平台或授权内容接口"},
      {"name":"hongguo","status":"needs_configuration","detail":"需平台或版权方提供适用的授权接口"}]}

@app.get("/api/platform-links", dependencies=[Depends(auth)])
async def platform_links():
    """Official entry points and docs; these are not direct media download URLs."""
    return {
        "notice": "平台入口/开发文档链接，不等于视频直链或全集下载授权。",
        "platforms": [
            {
                "id": "bilibili",
                "name": "哔哩哔哩",
                "site_url": "https://www.bilibili.com/",
                "developer_url": "https://open.bilibili.com/doc",
                "status": "needs_authorized_media_source",
                "download_note": "开放平台文档主要涉及账号授权、稿件管理和数据开放；需确认适用的授权媒体交付能力。"
            },
            {
                "id": "douyin",
                "name": "抖音",
                "site_url": "https://www.douyin.com/",
                "developer_url": "https://developer.open-douyin.com/",
                "status": "needs_authorized_media_source",
                "download_note": "开放平台能力按应用和权限审批；发布/数据接口不代表可下载任意短剧。"
            },
            {
                "id": "hongguo",
                "name": "红果短剧",
                "site_url": "https://www.hongguoduanju.com/",
                "developer_url": None,
                "status": "needs_partner_or_rightsholder_contact",
                "download_note": "未配置可验证的公开全集下载 API；请向平台或版权方确认合作与交付方式。"
            },
            {
                "id": "authorized-catalog",
                "name": "自有/授权素材库",
                "site_url": None,
                "developer_url": None,
                "status": "ready",
                "download_note": "将已授权的 HTTPS 视频直链导入目录，域名需加入 ALLOWED_DOWNLOAD_HOSTS。"
            }
        ]
    }


@app.get("/api/acquisition/providers", dependencies=[Depends(auth)])
async def acquisition_providers():
    """Explain which acquisition paths are actually configured; no platform bypassing."""
    return {
        "strategy": [
            "search imported, rights-cleared catalog",
            "download from configured HTTPS URLs on the host allowlist",
            "retry transient failures and resume partial files when Range is supported",
            "report blocked, invalid, or unavailable sources with a concrete reason",
        ],
        "providers": [
            {"name": "authorized-catalog", "status": "ready",
             "detail": "可导入自有素材库、版权方交付清单或明确获授权的直链"},
            {"name": "bilibili", "status": "needs_configuration",
             "detail": "需官方/合作接口或版权方授权交付；不绕过 DRM、付费或访问控制"},
            {"name": "douyin", "status": "needs_configuration",
             "detail": "需获批开放平台/授权素材接口；公开视频页面不等于下载授权"},
            {"name": "hongguo", "status": "needs_configuration",
             "detail": "需平台或版权方授权接口；不假设存在公开全集下载 API"},
        ],
        "fallback_policy": "仅在用户提供的授权候选源之间回退，不破解保护或规避访问限制",
    }


@app.post("/api/catalog/import", dependencies=[Depends(auth)])
async def import_catalog_item(payload: CatalogItemIn):
    """Import one rights-cleared series into the searchable local catalog."""
    for ep in payload.episodes:
        try:
            validate_url(str(ep.download_url))
            if ep.referer:
                validate_url(str(ep.referer))
        except Exception as ex:
            raise HTTPException(400, f"Invalid authorized source: {ex}")
    catalog_id = str(uuid.uuid4())
    episodes_json = json.dumps(
        [ep.model_dump(mode="json") for ep in payload.episodes],
        ensure_ascii=False,
    )
    keywords = [k.strip() for k in payload.keywords if k.strip()]
    with db() as c:
        c.execute(
            "INSERT INTO catalog VALUES(?,?,?,?,?,?,?)",
            (catalog_id, payload.title, payload.provider,
             json.dumps(keywords, ensure_ascii=False), episodes_json,
             payload.rights_note, datetime.now(timezone.utc).isoformat()),
        )
    return {
        "catalog_id": catalog_id,
        "title": payload.title,
        "provider": payload.provider,
        "episode_count": len(payload.episodes),
        "status": "indexed",
    }


@app.get("/api/catalog/search", dependencies=[Depends(auth)])
async def search_catalog(q: str = Query(min_length=1, max_length=120), limit: int = Query(default=20, ge=1, le=100)):
    """Search only imported authorized catalog entries; never scrapes platform pages."""
    terms = [t.casefold() for t in re.findall(r"[^\\s,，、]+", q) if t.strip()]
    with db() as c:
        rows = c.execute(
            "SELECT id,title,provider,keywords,episodes_json,created FROM catalog ORDER BY created DESC"
        ).fetchall()
    found = []
    for row in rows:
        keys = json.loads(row["keywords"] or "[]")
        haystack = " ".join([row["title"], row["provider"], *keys]).casefold()
        if all(term in haystack for term in terms):
            found.append({
                "catalog_id": row["id"],
                "title": row["title"],
                "provider": row["provider"],
                "keywords": keys,
                "episode_count": len(json.loads(row["episodes_json"])),
                "created": row["created"],
            })
        if len(found) >= limit:
            break
    return {"query": q, "count": len(found), "results": found}




@app.get("/api/search", dependencies=[Depends(auth)])
async def integrated_search(q: str = Query(min_length=1, max_length=120)):
    """Built-in discovery: generate real search URLs for official platform/search pages.

    This does not claim platform API access or download rights. Provider APIs can be
    added later when credentials and a rights-cleared content feed are available.
    """
    from urllib.parse import quote_plus
    keyword = q.strip()
    if not keyword:
        raise HTTPException(400, "请输入短剧名称或关键词")
    encoded = quote_plus(keyword)
    sources = [
        {"id": "bilibili", "name": "哔哩哔哩", "kind": "平台内搜索",
         "url": f"https://search.bilibili.com/all?keyword={encoded}",
         "note": "打开平台搜索结果；是否可观看或下载以平台权限和版权状态为准。"},
        {"id": "douyin", "name": "抖音", "kind": "平台内搜索",
         "url": f"https://www.douyin.com/search/{encoded}?type=general",
         "note": "打开平台搜索结果；公开视频不等于下载授权。"},
        {"id": "iqiyi", "name": "爱奇艺", "kind": "平台搜索",
         "url": f"https://so.iqiyi.com/so/q_{encoded}",
         "note": "通过官方页面查找作品。"},
        {"id": "youku", "name": "优酷", "kind": "平台搜索",
         "url": f"https://so.youku.com/search_video/q_{encoded}",
         "note": "通过官方页面查找作品。"},
        {"id": "web-official", "name": "网页搜索（优先官方来源）", "kind": "官方来源检索",
         "url": f"https://www.google.com/search?q={quote_plus(keyword + ' 短剧 官方')}",
         "note": "用于发现官方作品页或版权方页面；请核实授权后再使用资源。"},
    ]
    return {
        "query": keyword,
        "mode": "official_search_links",
        "count": len(sources),
        "results": sources,
        "notice": "已生成可直接打开的官方/平台搜索入口。当前未接入平台私有 API，因此不会伪造站内结果或宣称所有结果均已授权；下载功能仅适用于明确获授权的直链。",
    }


@app.post("/api/catalog/{catalog_id}/download-all", dependencies=[Depends(auth)])
async def download_catalog_item(catalog_id: str, payload: DownloadIn):
    """Create a download job from an indexed, rights-cleared catalog record."""
    with db() as c:
        row = c.execute("SELECT * FROM catalog WHERE id=?", (catalog_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Catalog item not found")
    raw_eps = json.loads(row["episodes_json"])
    # Revalidate every source at queue time, not only when the catalog was imported.
    for ep in raw_eps:
        try:
            validate_url(str(ep["download_url"]))
        except Exception as ex:
            raise HTTPException(400, f"Authorized source is no longer valid: {ex}")
    sid = str(uuid.uuid4())
    jid = str(uuid.uuid4())
    with db() as c:
        c.execute(
            "INSERT INTO series VALUES(?,?,?,?)",
            (sid, row["title"], row["provider"], datetime.now(timezone.utc).isoformat()),
        )
        for ep in raw_eps:
            c.execute(
                "INSERT INTO episodes(id,series_id,number,title,url,referer,expected_size,sha256) VALUES(?,?,?,?,?,?,?,?)",
                (str(uuid.uuid4()), sid, ep["episode_number"],
                 ep.get("title") or f"第{ep['episode_number']}集",
                 str(ep["download_url"]), str(ep["referer"]) if ep.get("referer") else None,
                 ep.get("expected_size"), ep.get("sha256")),
            )
        eps = c.execute("SELECT * FROM episodes WHERE series_id=? ORDER BY number", (sid,)).fetchall()
        c.execute(
            "INSERT INTO jobs VALUES(?,?,?,?,?,?,?)",
            (jid, sid, "queued", int(payload.merge_after_download),
             datetime.now(timezone.utc).isoformat(), None, None),
        )
        for ep in eps:
            c.execute("INSERT INTO job_eps VALUES(?,?)", (jid, ep["id"]))
    task = asyncio.create_task(run_job(jid))
    tasks.add(task)
    task.add_done_callback(tasks.discard)
    return {
        "catalog_id": catalog_id,
        "series_id": sid,
        "job_id": jid,
        "status": "queued",
        "episode_count": len(raw_eps),
        "merge_after_download": payload.merge_after_download,
        "rights_note": row["rights_note"],
    }


@app.post("/api/series",dependencies=[Depends(auth)])
async def create_series(payload:SeriesIn):
    for e in payload.episodes:
        try: validate_url(str(e.download_url))
        except Exception as ex: raise HTTPException(400,f"Invalid source: {ex}")
    sid=str(uuid.uuid4())
    with db() as c:
        c.execute("INSERT INTO series VALUES(?,?,?,?)",(sid,payload.title,payload.provider,datetime.now(timezone.utc).isoformat()))
        for e in payload.episodes:
            c.execute("INSERT INTO episodes(id,series_id,number,title,url,referer,expected_size,sha256) VALUES(?,?,?,?,?,?,?,?)",
            (str(uuid.uuid4()),sid,e.episode_number,e.title or f"第{e.episode_number}集",str(e.download_url),str(e.referer) if e.referer else None,e.expected_size,e.sha256))
    return {"series_id":sid,"title":payload.title,"episode_count":len(payload.episodes)}

@app.get("/api/series/{sid}/episodes",dependencies=[Depends(auth)])
async def list_episodes(sid:str):
    with db() as c:
        s=c.execute("SELECT * FROM series WHERE id=?",(sid,)).fetchone()
        if not s: raise HTTPException(404,"Series not found")
        eps=c.execute("SELECT number,title,status,bytes,path,error FROM episodes WHERE series_id=? ORDER BY number",(sid,)).fetchall()
    return {"series_id":sid,"title":s["title"],"episodes":[dict(e) for e in eps]}

@app.post("/api/series/{sid}/download-all",dependencies=[Depends(auth)])
async def download_all(sid:str,payload:DownloadIn):
    jid=str(uuid.uuid4())
    with db() as c:
        s=c.execute("SELECT * FROM series WHERE id=?",(sid,)).fetchone()
        if not s: raise HTTPException(404,"Series not found")
        eps=c.execute("SELECT * FROM episodes WHERE series_id=? ORDER BY number",(sid,)).fetchall()
        if not eps: raise HTTPException(400,"No episodes")
        c.execute("INSERT INTO jobs VALUES(?,?,?,?,?,?,?)",(jid,sid,"queued",int(payload.merge_after_download),datetime.now(timezone.utc).isoformat(),None,None))
        for e in eps:
            if e["status"]!="completed": c.execute("UPDATE episodes SET status='pending',error=NULL WHERE id=?",(e["id"],))
            c.execute("INSERT INTO job_eps VALUES(?,?)",(jid,e["id"]))
    t=asyncio.create_task(run_job(jid)); tasks.add(t); t.add_done_callback(tasks.discard)
    return {"job_id":jid,"status":"queued","episode_count":len(eps),"merge_after_download":payload.merge_after_download}

@app.get("/api/jobs/{jid}",dependencies=[Depends(auth)])
async def job_status(jid:str):
    job,eps=episode_rows(jid)
    if not job: raise HTTPException(404,"Job not found")
    total=len(eps); completed=sum(e["status"]=="completed" for e in eps); failed=sum(e["status"]=="failed" for e in eps)
    return {"job_id":jid,"title":job["title"],"status":job["status"],"total":total,"completed":completed,"failed":failed,"running":sum(e["status"] in ("downloading","retrying") for e in eps),"progress":round(100*completed/total,1) if total else 0,"merged_path":job["merged_path"],"error":job["error"],"episodes":[{"episode_number":e["number"],"title":e["title"],"status":e["status"],"bytes_downloaded":e["bytes"],"file_path":e["path"],"error":e["error"]} for e in eps]}

@app.post("/api/jobs/{jid}/cancel",dependencies=[Depends(auth)])
async def cancel(jid:str):
    job,_=episode_rows(jid)
    if not job: raise HTTPException(404,"Job not found")
    cancelled.add(jid)
    return {"job_id":jid,"status":"cancellation_requested"}
