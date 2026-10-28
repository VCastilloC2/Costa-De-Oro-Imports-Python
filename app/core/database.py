from urllib.parse import quote_plus, urlsplit, urlunsplit, parse_qsl, urlencode
from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from app.core.config import settings

def to_sqlalchemy_url(url: str, username: str = "", password: str = "") -> str:
    url = url.strip()
    if url.startswith("jdbc:mysql://"):
        url = "mysql+pymysql://" + url[len("jdbc:mysql://"):]
    elif url.startswith("mysql://"):
        url = "mysql+pymysql://" + url[len("mysql://"):]
    if url.startswith("mysql+pymysql://"):
        parts = urlsplit(url)
        # Elimina opciones del driver Java (Connector/J) que PyMySQL no reconoce.
        jdbc_only = {"servertimezone", "usessl", "requiressl", "verifyservercertificate"}
        query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
                 if k.lower() not in jdbc_only]
        netloc = parts.netloc
        if username and "@" not in netloc:
            netloc = f"{quote_plus(username)}:{quote_plus(password)}@{netloc}"
        url = urlunsplit((parts.scheme, netloc, parts.path, urlencode(query), parts.fragment))
    return url

DATABASE_URL = to_sqlalchemy_url(settings.db_url, settings.db_username, settings.db_password)
_db_options = {k.lower(): v.lower() for k, v in parse_qsl(urlsplit(settings.db_url).query, keep_blank_values=True)}
_tls_requested = any(_db_options.get(key) == "true" for key in ("usessl", "requiressl", "verifyservercertificate"))
_connect_args = {"connect_timeout": 10}
if _tls_requested:
    # PyMySQL uses ssl_disabled=False; useSSL/requireSSL are Connector/J options.
    _connect_args["ssl_disabled"] = False

engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_size=5, max_overflow=5,
                       pool_recycle=1200, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
class Base(DeclarativeBase): pass

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()
