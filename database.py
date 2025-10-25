import os
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Boolean, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
from config import config

# Criar diretório data se não existir
os.makedirs('data', exist_ok=True)

Base = declarative_base()

class Team(Base):
    __tablename__ = 'teams'
    
    id = Column(Integer, primary_key=True)
    api_id = Column(Integer, unique=True, nullable=False, index=True)
    name = Column(String(100), nullable=False)
    elo_rating = Column(Float, default=1500.0)
    attack_home = Column(Float, default=1.0)
    attack_away = Column(Float, default=1.0)
    defense_home = Column(Float, default=1.0)
    defense_away = Column(Float, default=1.0)
    updated_at = Column(DateTime, default=datetime.utcnow)

class Match(Base):
    __tablename__ = 'matches'
    
    id = Column(Integer, primary_key=True)
    api_id = Column(Integer, unique=True, nullable=False, index=True)
    date = Column(DateTime, nullable=False)
    home_team_id = Column(Integer, nullable=False, index=True)
    away_team_id = Column(Integer, nullable=False, index=True)
    home_team_name = Column(String(100))
    away_team_name = Column(String(100))
    home_goals = Column(Integer)
    away_goals = Column(Integer)
    home_xg = Column(Float)
    away_xg = Column(Float)
    status = Column(String(20), index=True)
    analyzed = Column(Boolean, default=False)

class ValueBet(Base):
    __tablename__ = 'value_bets'
    
    id = Column(Integer, primary_key=True)
    match_api_id = Column(Integer, nullable=False, index=True)
    home_team_name = Column(String(100), nullable=False)
    away_team_name = Column(String(100), nullable=False)
    match_date = Column(DateTime, nullable=False)
    market = Column(String(50), nullable=False)
    odds = Column(Float, nullable=False)
    model_prob = Column(Float, nullable=False)
    market_prob = Column(Float, nullable=False)
    edge = Column(Float, nullable=False)
    confidence = Column(Float, nullable=False)
    stake_amount = Column(Float, nullable=False)
    expected_value = Column(Float, nullable=False)
    pattern_type = Column(String(50))
    pattern_explanation = Column(Text)
    sent_telegram = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

# Setup da base de dados com configurações para SQLite
connect_args = {}
if config.DATABASE_URL.startswith('sqlite'):
    connect_args = {"check_same_thread": False}

engine = create_engine(config.DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def create_tables():
    Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
