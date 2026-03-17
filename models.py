from database import Base
from sqlalchemy import Column, Integer, String, ForeignKey
from sqlalchemy.orm import relationship, Mapped, mapped_column
class DBWebsite(Base):
    __tablename__ = "websites"
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    url: Mapped[str] = mapped_column(unique=True)
    status: Mapped[str] = mapped_column(default="Unknown")
    last_checked: Mapped[str | None] = mapped_column( nullable=True)

    logs: Mapped[list["PingLog"]] = relationship(back_populates="owner", cascade="all, delete-orphan")

class PingLog(Base):
    __tablename__ = "ping_logs"
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    timestamp: Mapped[str]
    status_code: Mapped[int]

    website_id: Mapped[int] = mapped_column(ForeignKey("websites.id"))
    owner: Mapped["DBWebsite"] = relationship(back_populates="logs")

