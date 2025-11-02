import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # API Football
    API_FOOTBALL_KEY = os.getenv('API_FOOTBALL_KEY')
    API_FOOTBALL_URL = 'https://v3.football.api-sports.io'
    # Timezone para scheduler
    TIMEZONE = os.getenv('TZ', 'Europe/Lisbon')
    
    # Telegram
    TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
    TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
    
    # Liga e Época
    LEAGUE_ID = int(os.getenv('LEAGUE_ID', 94))  # Primeira Liga
    SEASON = int(os.getenv('SEASON', 2024))
    
    # Trading
    MIN_EDGE = float(os.getenv('MIN_EDGE', 0.03))
    BANKROLL = float(os.getenv('BANKROLL', 10000))
    MAX_STAKE_PCT = 0.04
    KELLY_FRACTION = 0.25
    
    # Base de dados
    DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///data/primeira_liga.db')
    
    # Padrões da Primeira Liga
    BIG_THREE = ['Benfica', 'Porto', 'Sporting CP', 'SL Benfica', 'FC Porto']
    HOME_ADVANTAGE = 100  # Pontos ELO
    
    # Logging
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()

config = Config()
