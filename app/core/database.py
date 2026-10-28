from urllib.parse import quote_plus
from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from app.core.config import settings

def to_sqlalchemy_url(url: str, username: str = "", password: str = "") -> str:
    url = url.strip()
    if url.startswith("jdbc:mysql://"):
        url = "mysql+pymysql://" + url[len("jdbc:mysql://"):]
    elif url.startswith("mysql://"):
        url = "mysql+pymysql://" + url[len("mysql://"):]
    if url.startswith("mysql+pymysql://") and username:
        authority = url.split("://", 1)[1].split("/", 1)[0]
        if "@" not in authority:
            url = url.replace("mysql+pymysql://", f"mysql+pymysql://{quote_plus(username)}:{quote_plus(password)}@", 1)
    return url

DATABASE_URL = to_sqlalchemy_url(settings.db_url, settings.db_username, settings.db_password)
engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_size=5, max_overflow=5, pool_recycle=1200, connect_args={"connect_timeout": 10})
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
class Base(DeclarativeBase): pass

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()