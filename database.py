import os
import logging
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Boolean, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from config import config

logger = logging.getLogger(__name__)

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

def get_writable_database_path():
    """Encontra um caminho gravável para a base de dados SQLite"""
    
    # Tentar caminhos em ordem de preferência
    candidates = [
        "/tmp/primeira_liga.db",                    # Sempre gravável no Railway
        "/app/data/primeira_liga.db",               # Caminho original (se funcionar)
        os.path.join(os.getcwd(), "data", "primeira_liga.db"),  # Diretório atual
        ":memory:"                                  # Fallback: base em memória
    ]
    
    for path in candidates:
        if path == ":memory:":
            logger.info("🔄 Usando base de dados em memória (dados perdidos no restart)")
            return f"sqlite:///{path}"
        
        try:
            # Criar diretório se necessário
            directory = os.path.dirname(path)
            if directory and directory != "/":
                os.makedirs(directory, exist_ok=True)
            
            # Testar escrita criando ficheiro temporário
            test_file = f"{path}.test"
            with open(test_file, "w") as f:
                f.write("test")
            os.remove(test_file)
            
            logger.info(f"✅ Base de dados configurada: {path}")
            return f"sqlite:///{path}"
            
        except Exception as e:
            logger.debug(f"❌ Caminho {path} não disponível: {e}")
            continue
    
    # Se chegou aqui, usar memória como último recurso
    logger.warning("⚠️ Usando base de dados em memória como último recurso")
    return "sqlite:///:memory:"

# Configurar URL da base de dados
try:
    # Se DATABASE_URL está definida explicitamente, usar
    if hasattr(config, 'DATABASE_URL') and config.DATABASE_URL and not config.DATABASE_URL.endswith('primeira_liga.db'):
        DATABASE_URL = config.DATABASE_URL
        logger.info(f"📊 Usando DATABASE_URL configurada: {DATABASE_URL}")
    else:
        # Encontrar caminho automaticamente
        DATABASE_URL = get_writable_database_path()
        
except Exception as e:
    logger.error(f"❌ Erro ao configurar base de dados: {e}")
    DATABASE_URL = "sqlite:///:memory:"
    logger.info("🔄 Fallback para base de dados em memória")

# Configurações de conexão
connect_args = {}
if DATABASE_URL.startswith('sqlite'):
    connect_args = {
        "check_same_thread": False,
        "timeout": 20
    }

# Criar engine e sessão
try:
    engine = create_engine(DATABASE_URL, connect_args=connect_args, echo=False)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    logger.info("✅ Engine da base de dados criada com sucesso")
    
except Exception as e:
    logger.error(f"❌ Erro crítico na base de dados: {e}")
    # Última tentativa: memória
    DATABASE_URL = "sqlite:///:memory:"
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    logger.info("🆘 Usando base de dados em memória como último recurso")

def create_tables():
    """Cria tabelas da base de dados"""
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("✅ Tabelas da base de dados criadas com sucesso")
    except Exception as e:
        logger.error(f"❌ Erro ao criar tabelas: {e}")
        raise

def get_db():
    """Obtém sessão da base de dados"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
