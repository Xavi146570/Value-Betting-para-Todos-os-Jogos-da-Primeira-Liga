import re
import math
import logging
import asyncio
import functools
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Union, Any, Tuple
from config import config

logger = logging.getLogger(__name__)

# ===== MATHEMATICAL UTILITIES =====

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
        # Para valores muito grandes, retornar 0
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

def poisson_matrix(home_lambda: float, away_lambda: float, max_goals: int = 6) -> np.ndarray:
    """Cria matriz de probabilidades Poisson bivariado"""
    if home_lambda <= 0 or away_lambda <= 0:
        return np.zeros((max_goals + 1, max_goals + 1))
    
    mat = np.zeros((max_goals + 1, max_goals + 1), dtype=float)
    for h in range(max_goals + 1):
        for a in range(max_goals + 1):
            mat[h, a] = _poisson_pmf(h, home_lambda) * _poisson_pmf(a, away_lambda)
    
    # Normalizar
    total = mat.sum()
    if total > 0:
        mat /= total
    
    return mat

def calculate_1x2_from_matrix(mat: np.ndarray) -> Dict[str, float]:
    """Extrai probabilidades 1X2 da matriz Poisson"""
    max_goals = mat.shape[0] - 1
    
    home_win = float(sum(mat[h, a] for h in range(max_goals + 1) for a in range(h)))
    draw = float(sum(mat[i, i] for i in range(max_goals + 1)))
    away_win = 1.0 - home_win - draw
    
    # Normalizar para garantir soma = 1
    total = home_win + draw + away_win
    if total > 0:
        return {
            "home_win": home_win / total,
            "draw": draw / total, 
            "away_win": away_win / total
        }
    
    return {"home_win": 1/3, "draw": 1/3, "away_win": 1/3}

def calculate_over_under_from_matrix(mat: np.ndarray, line: float) -> Dict[str, float]:
    """Calcula probabilidades Over/Under da matriz"""
    max_goals = mat.shape[0] - 1
    over_prob = float(sum(mat[h, a] for h in range(max_goals + 1) 
                         for a in range(max_goals + 1) if (h + a) > line))
    
    return {
        f"over_{line}": over_prob,
        f"under_{line}": 1.0 - over_prob
    }

def calculate_btts_from_matrix(mat: np.ndarray) -> Dict[str, float]:
    """Calcula probabilidades BTTS da matriz"""
    max_goals = mat.shape[0] - 1
    btts_yes = float(sum(mat[h, a] for h in range(1, max_goals + 1) 
                        for a in range(1, max_goals + 1)))
    
    return {
        "btts_yes": btts_yes,
        "btts_no": 1.0 - btts_yes
    }

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
    def calculate_overround(odds_list: List[float]) -> float:
        """Calcula overround (margem da casa) de uma lista de odds"""
        if not odds_list:
            return 0.0
        
        total_prob = sum(1/odds for odds in odds_list if odds > 1.0)
        return max(0.0, total_prob - 1.0)
    
    @staticmethod
    def remove_overround(odds_list: List[float]) -> List[float]:
        """Remove overround normalizando probabilidades"""
        if not odds_list:
            return odds_list
        
        # Converter para probabilidades
        probs = [1/odds for odds in odds_list if odds > 1.0]
        if not probs:
            return odds_list
        
        # Normalizar
        total_prob = sum(probs)
        if total_prob <= 0:
            return odds_list
        
        normalized_probs = [prob/total_prob for prob in probs]
        return [max(1.01, 1/prob) for prob in normalized_probs]
    
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
    
    @staticmethod
    def fixed_percentage_stake(bankroll: float, percentage: float) -> float:
        """Stake de percentagem fixa"""
        return bankroll * (percentage / 100.0)
    
    @staticmethod
    def calculate_roi(initial_bankroll: float, current_bankroll: float) -> float:
        """Calcula ROI em percentagem"""
        if initial_bankroll <= 0:
            return 0.0
        return ((current_bankroll - initial_bankroll) / initial_bankroll) * 100.0

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
    def extract_xg_from_statistics(stats_data: List[Dict]) -> Tuple[Optional[float], Optional[float]]:
        """
        Extrai xG (Expected Goals) das estatísticas
        Retorna (home_xg, away_xg)
        """
        if not stats_data or len(stats_data) != 2:
            return None, None
        
        home_xg = None
        away_xg = None
        
        try:
            # Assumir que stats_data[0] = casa, stats_data[1] = fora
            for stat in stats_data[0]['statistics']:
                if stat['type'] == 'Expected Goals':
                    home_xg = float(stat['value']) if stat['value'] else None
                    break
            
            for stat in stats_data[1]['statistics']:
                if stat['type'] == 'Expected Goals':
                    away_xg = float(stat['value']) if stat['value'] else None
                    break
                    
        except (KeyError, TypeError, ValueError) as e:
            logger.error(f"Erro ao extrair xG: {e}")
            return None, None
        
        return home_xg, away_xg
    
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

# ===== VALIDATION UTILITIES =====

class ValidationHelper:
    """Utilitários para validação de dados"""
    
    @staticmethod
    def validate_probability(prob: float, field_name: str = "probabilidade") -> bool:
        """Valida probabilidade (0-1)"""
        if not isinstance(prob, (int, float)):
            logger.error(f"{field_name} deve ser numérico: {prob}")
            return False
        
        if not (0.0 <= prob <= 1.0):
            logger.error(f"{field_name} deve estar entre 0 e 1: {prob}")
            return False
        
        return True
    
    @staticmethod
    def validate_odds(odds: float, field_name: str = "odds") -> bool:
        """Valida odds (>1.0)"""
        if not isinstance(odds, (int, float)):
            logger.error(f"{field_name} devem ser numéricas: {odds}")
            return False
        
        if odds <= 1.0:
            logger.error(f"{field_name} devem ser > 1.0: {odds}")
            return False
        
        if odds > 1000:
            logger.warning(f"{field_name} muito altas: {odds}")
        
        return True
    
    @staticmethod
    def validate_match_data(match_data: Dict) -> List[str]:
        """Valida dados de jogo e retorna lista de erros"""
        errors = []
        
        required_fields = ['home_team', 'away_team', 'match_date']
        for field in required_fields:
            if field not in match_data or not match_data[field]:
                errors.append(f"Campo obrigatório em falta: {field}")
        
        # Validar equipas diferentes
        if (match_data.get('home_team') and match_data.get('away_team') and
            match_data['home_team'] == match_data['away_team']):
            errors.append("Equipas da casa e visitante devem ser diferentes")
        
        return errors

# ===== FORMATTING UTILITIES =====

def format_percentage(value: float, decimal_places: int = 1) -> str:
    """Formata valor como percentagem"""
    return f"{value * 100:.{decimal_places}f}%"

def format_currency(value: float, symbol: str = "€") -> str:
    """Formata valor como moeda"""
    return f"{symbol}{value:,.2f}"

def clamp(value: float, min_val: float, max_val: float) -> float:
    """Limita valor entre mínimo e máximo"""
    return max(min_val, min(max_val, value))

def safe_divide(numerator: float, denominator: float, default: float = 0.0) -> float:
    """Divisão segura com valor default"""
    return numerator / denominator if denominator != 0 else default

def truncate_text(text: str, max_length: int = 200, suffix: str = "...") -> str:
    """Trunca texto se exceder comprimento máximo"""
    if not text:
        return ""
    return text if len(text) <= max_length else text[:max_length - len(suffix)] + suffix

# ===== ASYNC UTILITIES =====

def async_retry(max_retries: int = 3, delay: float = 1.0, exponential_backoff: bool = True):
    """Decorator para retry automático de funções assíncronas"""
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            last_exception = None
            
            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    
                    if attempt < max_retries - 1:
                        wait_time = delay * (2 ** attempt if exponential_backoff else 1)
                        logger.warning(f"Tentativa {attempt + 1} falhou para {func.__name__}: {e}. "
                                     f"Retry em {wait_time}s")
                        await asyncio.sleep(wait_time)
                    else:
                        logger.error(f"Todas as {max_retries} tentativas falharam para {func.__name__}")
            
            raise last_exception
        return wrapper
    return decorator

# ===== INSTÂNCIAS GLOBAIS =====

# Instâncias para uso direto
team_normalizer = TeamNameNormalizer()
datetime_helper = DateTimeHelper()
odds_helper = OddsHelper()
stake_calculator = StakeCalculator()
api_processor = APIDataProcessor()
validation_helper = ValidationHelper()

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
