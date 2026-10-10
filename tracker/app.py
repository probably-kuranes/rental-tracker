"""Web app: JSON API plus the single-page front end in tracker/web/.

Everything is behind HTTP Basic auth (APP_USER / APP_PASSWORD): the pages
show tenant names and payment history.
"""
from __future__ import annotations

import os
import secrets
from datetime import date, timedelta
from pathlib import Path
from threading import Lock

from fastapi import APIRouter, Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select

from . import db, views
from .derive import build_world
from .ingest import ingest_pdf_bytes
from .storage import store

WEB = Path(__file__).parent / 'web'
security = HTTPBasic(auto_error=False)


def require_login(creds: HTTPBasicCredentials | None = Depends(security)):
    password = os.getenv('APP_PASSWORD')
    if not password:
        if os.getenv('ALLOW_NO_AUTH') == '1':
            return
        raise HTTPException(503, 'APP_PASSWORD is not set')
    user = os.getenv('APP_USER', 'david')
    if creds is None or not (secrets.compare_digest(creds.username, user)
                             and secrets.compare_digest(creds.password, password)):
        raise HTTPException(401, headers={'WWW-Authenticate': 'Basic realm="Rental Tracker"'})


app = FastAPI(title='Rental Tracker')
api = APIRouter(dependencies=[Depends(require_login)])

_cache = {'key': None, 'world': None}
_lock = Lock()


def world():
    """The derived World, rebuilt only when source data has changed."""
    with db.session() as s:
        key = (s.scalar(select(func.max(db.Statement.id))), s.scalar(select(func.count(db.Statement.id))),
               s.scalar(select(func.max(db.Event.id))), s.scalar(select(func.count(db.Event.id))))
    with _lock:
        if _cache['key'] != key:
            _cache['world'] = build_world()
            _cache['key'] = key
        return _cache['world']


def today() -> date:
    override = os.getenv('TODAY')
    return date.fromisoformat(override) if override else date.today()


@api.get('/api/status')
def api_status():
    return views.status(world(), today())


@api.get('/api/timeline')
def api_timeline():
    return views.timeline(world(), today())


@api.get('/api/analytics')
def api_analytics():
    return views.analytics(world())


@api.get('/api/summary')
def api_summary(month: str | None = None, audience: str = 'owner', refresh: bool = False):
    if audience not in ('owner', 'family'):
        raise HTTPException(400, 'audience must be owner or family')
    if month is None:
        last = date(today().year, today().month, 1) - timedelta(days=1)
        month = f"{last.year:04d}-{last.month:02d}"
    return views.summary(world(), month, audience, refresh)


@api.get('/api/documents')
def api_documents():
    with db.session() as s:
        docs = s.scalars(select(db.Document).order_by(db.Document.id.desc()))
        return [{'id': d.id, 'filename': d.filename, 'source': d.source, 'format': d.format, 'status': d.status,
                 'problems': d.problems, 'received_at': d.received_at.isoformat() if d.received_at else None,
                 'statements': [{'id': st.id, 'portfolio': st.portfolio, 'start': st.period_start.isoformat(),
                                 'end': st.period_end.isoformat(), 'reconciled': st.reconciled}
                                for st in d.statements]} for d in docs]


@api.get('/api/statements/{statement_id}/pdf')
def api_statement_pdf(statement_id: int):
    with db.session() as s:
        st = s.get(db.Statement, statement_id)
        if st is None:
            raise HTTPException(404)
        digest = st.document.sha256
    return Response(store().get(digest), media_type='application/pdf',
                    headers={'Content-Disposition': 'inline; filename="statement.pdf"'})


@api.post('/api/upload')
async def api_upload(file: UploadFile = File(...)):
    data = await file.read()
    if not data.startswith(b'%PDF'):
        raise HTTPException(400, 'Not a PDF')
    doc = ingest_pdf_bytes(data, file.filename or 'upload.pdf', 'upload')
    return {'id': doc.id, 'status': doc.status, 'problems': doc.problems}


@api.get('/api/emails')
def api_emails(limit: int = 100):
    with db.session() as s:
        rows = s.scalars(select(db.Email).order_by(db.Email.date.desc()).limit(limit))
        return [{'id': e.id, 'date': e.date.isoformat() if e.date else None, 'subject': e.subject, 'kind': e.kind,
                 'status': e.status, 'summary': e.summary, 'portfolio': e.portfolio} for e in rows]


@api.get('/')
def index():
    return FileResponse(WEB / 'index.html')


@app.get('/healthz')
def healthz():
    """Unauthenticated liveness check for Railway."""
    with db.session() as s:
        s.scalar(select(func.count(db.Statement.id)))
    return {'ok': True}


app.include_router(api)
app.mount('/static', StaticFiles(directory=WEB), name='static')
