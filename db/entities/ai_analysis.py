"""
LEGION (https://github.com/ThereAreSomeWhoCallMeTimAtViasat/legion)
Author: Tim McLean (Viasat, Inc.)
Copyright (c) 2025-2026 Viasat, Inc.
Copyright (c) 2025 Shane William Scott (original Legion)

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful, but
    WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
    General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program. If not, see <http://www.gnu.org/licenses/>.

THIS SOFTWARE IS PROVIDED BY VIASAT, INC. "AS IS" AND ANY EXPRESS OR
IMPLIED WARRANTIES ARE DISCLAIMED. IN NO EVENT SHALL VIASAT, INC. BE
LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
CONSEQUENTIAL DAMAGES ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE.
"""

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
    gap_analysis_json  = Column(Text,    nullable=True)
    enum_actions_json  = Column(Text,    nullable=True)
