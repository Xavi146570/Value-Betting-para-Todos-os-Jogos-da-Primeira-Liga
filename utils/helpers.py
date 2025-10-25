import re
import math
import logging
import asyncio
import functools
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Union, Any, Tuple
from config import config

logger = logging.getLogger(__name__)

# ===== MATHEMATICAL UTILITIES (Python Puro) =====

def _poisson_pmf(k: int, lam: float) -> float:
    """
    Implementação manual da Probability Mass Function de Poisson
    P(X = k) = (λ^k * e^(-λ)) / k!
    """
    if lam <= 0:
        return 0.0 if k > 0 else 1.0
    
    if k < 0:
        return 0.0
    
    try:
        factorial_k = math.factorial(k)
        return (lam ** k * math.exp(-lam)) / factorial_k
    except (OverflowError, ValueError):
        return 0.0

def kelly_fraction(prob: float, odds: float) -> float:
    """
    Calcula fração Kelly ótima
    Fórmula: f = (bp - q) / b onde b = odds - 1, q = 1 - p
    """
    if odds <= 1.01 or prob <= 0 or prob >= 1:
        return 0.0
    
    b = odds - 1.0
    q = 1.0 - prob
    f = (b * prob - q) / b
    return max(0.0, f)

def expected_value(prob: float, odds: float, stake_amount: float) -> float:
    """Calcula Expected Value em euros"""
    if prob <= 0 or odds <= 1.0:
        return 0.0
    return (prob * (odds - 1.0) - (1.0 - prob)) * stake_amount

# ===== TEAM NORMALIZATION =====

class TeamNameNormalizer:
    """Normalização robusta de nomes de equipas da Primeira Liga"""
    
    def __init__(self):
        # Mapeamento completo para Primeira Liga 2024
        self.team_mappings = {
            # Os Três Grandes
            'benfica': ['sl benfica', 'sport lisboa e benfica', 'sport lisboa benfica', 'slb'],
            'porto': ['fc porto', 'futebol clube do porto', 'fc do porto', 'fcp'],
            'sporting': ['sporting cp', 'sporting clube de portugal', 'sporting lisboa', 'scp'],
            
            # Outras equipas principais
            'braga': ['sc braga', 'sporting clube de braga', 'sporting braga', 'scb'],
            'vitoria sc': ['vitoria guimaraes', 'vitória de guimarães', 'vitoria de guimaraes', 
                          'vitória sc', 'vitoria sport clube', 'vsc'],
            'boavista': ['boavista fc', 'boavista futebol clube', 'bfc'],
            'gil vicente': ['gil vicente fc', 'gvfc'],
            'famalicao': ['fc famalicao', 'fc famalicão', 'fcf'],
            'moreirense': ['moreirense fc', 'mfc'],
            'santa clara': ['cd santa clara', 'clube desportivo santa clara', 'cdsc'],
            'casa pia': ['casa pia ac', 'casa pia atlético clube', 'cpac'],
            'arouca': ['fc arouca', 'futebol clube de arouca', 'fca'],
            'estoril': ['estoril praia', 'gd estoril praia', 'grupo desportivo estoril praia', 'gdep'],
            'rio ave': ['rio ave fc', 'rafc'],
            'chaves': ['gd chaves', 'grupo desportivo chaves', 'gdc'],
            'vizela': ['fc vizela', 'fcv'],
            'portimonense': ['portimonense sc', 'psc'],
            'farense': ['sc farense', 'sporting clube farense', 'scf'],
            'estrela': ['estrela da amadora', 'cf estrela da amadora', 'cfea']
        }
    
    def normalize_team_name(self, team_name: str) -> str:
        """Normaliza nome da equipa para formato padrão"""
        if not team_name:
            return ""
        
        # Limpar e normalizar
        clean_name = re.sub(r'[^\w\s]', '', team_name.lower().strip())
        clean_name = re.sub(r'\s+', ' ', clean_name)
        
        # Procurar correspondência exata primeiro
        for standard_name, alternatives in self.team_mappings.items():
            if clean_name == standard_name or clean_name in alternatives:
                return standard_name.title()
        
        # Procurar correspondência parcial (palavras-chave)
        for standard_name, alternatives in self.team_mappings.items():
            all_variants = [standard_name] + alternatives
            for variant in all_variants:
                if any(word in clean_name for word in variant.split() if len(word) > 3):
                    return standard_name.title()
        
        # Retornar nome limpo se não encontrou correspondência
        return clean_name.title()
    
    def are_same_team(self, team1: str, team2: str) -> bool:
        """Verifica se dois nomes se referem à mesma equipa"""
        return self.normalize_team_name(team1) == self.normalize_team_name(team2)
    
    def is_big_three(self, team_name: str) -> bool:
        """Verifica se é uma das três grandes"""
        normalized = self.normalize_team_name(team_name).lower()
        return normalized in ['benfica', 'porto', 'sporting']

# ===== DATE/TIME UTILITIES =====

class DateTimeHelper:
    """Utilitários para manipulação de datas e horários"""
    
    @staticmethod
    def parse_api_datetime(api_datetime: str) -> Optional[datetime]:
        """Converte string datetime da API Football para objeto datetime"""
        if not api_datetime:
            return None
        
        # Formatos da API Football
        formats = [
            '%Y-%m-%dT%H:%M:%S%z',      # ISO com timezone: 2024-01-21T20:15:00+00:00
            '%Y-%m-%dT%H:%M:%SZ',       # ISO com Z: 2024-01-21T20:15:00Z
            '%Y-%m-%dT%H:%M:%S',        # ISO sem timezone: 2024-01-21T20:15:00
            '%Y-%m-%d %H:%M:%S',        # Formato simples: 2024-01-21 20:15:00
            '%Y-%m-%d',                 # Apenas data: 2024-01-21
        ]
        
        # Tratar Z timezone
        datetime_str = api_datetime.replace('Z', '+00:00')
        
        for fmt in formats:
            try:
                return datetime.strptime(datetime_str, fmt)
            except ValueError:
                continue
        
        logger.warning(f"Formato de data não reconhecido: {api_datetime}")
        return None
    
    @staticmethod
    def format_display_date(dt: datetime) -> str:
        """Formata datetime para exibição portuguesa"""
        if not dt:
            return "N/A"
        return dt.strftime('%d/%m/%Y às %H:%M')
    
    @staticmethod
    def format_short_date(dt: datetime) -> str:
        """Formata data curta"""
        if not dt:
            return "N/A"
        return dt.strftime('%d/%m/%Y')
    
    @staticmethod
    def format_time_only(dt: datetime) -> str:
        """Formata apenas hora"""
        if not dt:
            return "N/A"
        return dt.strftime('%H:%M')
    
    @staticmethod
    def calculate_days_rest(last_match: datetime, current_match: datetime) -> int:
        """Calcula dias de descanso entre jogos"""
        if not last_match or not current_match:
            return 7  # Default
        
        delta = current_match - last_match
        return max(0, delta.days)
    
    @staticmethod
    def is_recent_match(match_date: datetime, days_threshold: int = 7) -> bool:
        """Verifica se jogo é recente"""
        if not match_date:
            return False
        
        now = datetime.now()
        if match_date.tzinfo:
            now = now.replace(tzinfo=match_date.tzinfo)
        
        return (now - match_date).days <= days_threshold

# ===== ODDS AND PROBABILITY UTILITIES =====

class OddsHelper:
    """Utilitários para manipulação de odds e probabilidades"""
    
    @staticmethod
    def odds_to_probability(odds: float) -> float:
        """Converte odds para probabilidade implícita"""
        if odds <= 1.0:
            return 0.0
        return 1.0 / odds
    
    @staticmethod
    def probability_to_odds(probability: float, min_odds: float = 1.01) -> float:
        """Converte probabilidade para odds"""
        if probability <= 0 or probability >= 1:
            return min_odds
        return max(min_odds, 1.0 / probability)
    
    @staticmethod
    def calculate_edge(model_prob: float, market_odds: float) -> float:
        """Calcula edge (vantagem) sobre as odds de mercado"""
        if market_odds <= 1.0:
            return 0.0
        
        market_prob = 1.0 / market_odds
        return model_prob - market_prob
    
    @staticmethod
    def format_odds(odds: float, decimal_places: int = 2) -> str:
        """Formata odds para exibição"""
        if odds <= 1.0:
            return "N/A"
        return f"{odds:.{decimal_places}f}"

# ===== STAKE CALCULATION =====

class StakeCalculator:
    """Calculadora avançada de stakes"""
    
    @staticmethod
    def kelly_stake(probability: float, odds: float, bankroll: float,
                   kelly_fraction: float = 0.25, confidence: float = 1.0,
                   max_stake_pct: float = 0.04) -> Tuple[float, float]:
        """
        Calcula stake usando Kelly Criterion fracionado
        Retorna (stake_amount, stake_percentage)
        """
        if probability <= 0 or probability >= 1 or odds <= 1.0:
            return 0.0, 0.0
        
        # Kelly ótimo
        kelly_optimal = kelly_fraction(probability, odds)
        if kelly_optimal <= 0:
            return 0.0, 0.0
        
        # Aplicar ajustes
        kelly_adjusted = kelly_optimal * kelly_fraction * confidence
        
        # Limitar percentagem máxima
        final_pct = min(kelly_adjusted, max_stake_pct)
        stake_amount = bankroll * final_pct
        
        return stake_amount, final_pct

# ===== API DATA PROCESSING =====

class APIDataProcessor:
    """Processamento de dados da API Football"""
    
    @staticmethod
    def extract_match_result(fixture_data: Dict) -> str:
        """
        Extrai resultado do jogo (H/D/A)
        H = Home win, D = Draw, A = Away win
        """
        try:
            if fixture_data['fixture']['status']['short'] != 'FT':
                return 'N/A'
            
            home_goals = fixture_data['goals']['home']
            away_goals = fixture_data['goals']['away']
            
            if home_goals is None or away_goals is None:
                return 'N/A'
            
            if home_goals > away_goals:
                return 'H'
            elif home_goals == away_goals:
                return 'D'
            else:
                return 'A'
                
        except (KeyError, TypeError):
            logger.error(f"Erro ao extrair resultado do fixture: {fixture_data}")
            return 'N/A'
    
    @staticmethod
    def calculate_team_form(recent_fixtures: List[Dict], team_id: int) -> float:
        """
        Calcula rating de forma baseado nos últimos jogos
        Retorna valor entre 0.0 (péssima forma) e 1.0 (excelente forma)
        """
        if not recent_fixtures:
            return 0.5  # Neutro
        
        form_score = 0.0
        weights = [1.0, 0.8, 0.6, 0.4, 0.2]  # Peso decrescente para jogos mais antigos
        total_weight = 0.0
        
        for i, fixture in enumerate(recent_fixtures):
            if i >= len(weights):
                break
            
            try:
                result = APIDataProcessor.extract_match_result(fixture)
                if result == 'N/A':
                    continue
                
                # Determinar se equipa jogou em casa ou fora
                home_team_id = fixture['teams']['home']['id']
                is_home = (home_team_id == team_id)
                
                # Calcular pontos baseado no resultado
                if (result == 'H' and is_home) or (result == 'A' and not is_home):
                    points = 1.0  # Vitória
                elif result == 'D':
                    points = 0.5  # Empate
                else:
                    points = 0.0  # Derrota
                
                form_score += points * weights[i]
                total_weight += weights[i]
                
            except (KeyError, TypeError):
                continue
        
        return form_score / total_weight if total_weight > 0 else 0.5

# ===== INSTÂNCIAS GLOBAIS =====

# Instâncias para uso direto
team_normalizer = TeamNameNormalizer()
datetime_helper = DateTimeHelper()
odds_helper = OddsHelper()
stake_calculator = StakeCalculator()
api_processor = APIDataProcessor()

# Funções de conveniência
def normalize_team(team_name: str) -> str:
    """Normaliza nome de equipa"""
    return team_normalizer.normalize_team_name(team_name)

def is_big_three(team_name: str) -> bool:
    """Verifica se é uma das três grandes"""
    return team_normalizer.is_big_three(team_name)

def calculate_edge(model_prob: float, market_odds: float) -> float:
    """Calcula edge sobre odds de mercado"""
    return odds_helper.calculate_edge(model_prob, market_odds)

def parse_fixture_date(date_str: str) -> Optional[datetime]:
    """Converte string de data da API"""
    return datetime_helper.parse_api_datetime(date_str)
