from database import Base
from sqlalchemy import Column, Integer, String, ForeignKey
from sqlalchemy.orm import relationship
class DBWebsite(Base):
    __tablename__ = "websites"
    id = Column(Integer, primary_key=True, index=True)
    url = Column(String, unique=True)
    status = Column(String, default="Unknown")
    last_checked = Column(String, nullable=True)

    logs = relationship("PingLog", back_populates="owner", cascade="all, delete-orphan")

class PingLog(Base):
    __tablename__ = "ping_logs"
    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(String)
    status_code = Column(Integer)

    website_id = Column(Integer, ForeignKey("websites.id"))
    owner = relationship("DBWebsite", back_populates="logs")

