"""ai_analysis entity — per-host AI analysis stored in the project SQLite DB."""
from sqlalchemy import Column, Integer, String, Text, Float
from db.database import Base


class AiAnalysis(Base):
    __tablename__ = 'ai_analysis'

    id                = Column(Integer, primary_key=True)
    host_id           = Column(Integer, nullable=False)   # FK → hostObj.id
    timestamp         = Column(String,  nullable=False)
    phase1_json       = Column(Text,    nullable=False, default='[]')
    phase2_markdown   = Column(Text,    nullable=False, default='')
    tokens_input      = Column(Integer, nullable=False, default=0)
    tokens_output     = Column(Integer, nullable=False, default=0)
    cost_usd          = Column(Float,   nullable=False, default=0.0)
    history_session_id = Column(Integer, nullable=True)   # FK → ai_history.db
