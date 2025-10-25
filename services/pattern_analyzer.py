import logging
import traceback
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta

from config import config
from services.api_football import api_client
from utils.helpers import datetime_helper, api_processor, team_normalizer

logger = logging.getLogger(__name__)

class PatternAnalyzer:
    """
    Analisador de padrões específicos da Primeira Liga para detecção de contexto
    e construção de features para os modelos de predição.
    """
    
    def __init__(self):
        # Pesos para cálculo do rating de fortaleza caseira (0-10)
        self.fortress_weights = {
            'home_pts_per_game': 0.35,      # Pontos por jogo em casa
            'home_ga_per_game': 0.30,       # Golos sofridos por jogo em casa (invertido)
            'home_clean_sheet_rate': 0.25,  # Taxa de clean sheets em casa
            'recent_form': 0.10             # Forma geral recente
        }
        
        # Thresholds para detecção de padrões
        self.european_fatigue_days = 4      # Máximo de dias para considerar fadiga europeia
        self.rest_advantage_days = 2        # Diferença mínima para vantagem de descanso
        self.fortress_rating_threshold = 7.0 # Rating mínimo para fortaleza caseira
        self.min_matches_analysis = 6       # Mínimo de jogos para análise confiável
        
        # Derby combinations (principais rivalidades)
        self.derby_combinations = [
            ('benfica', 'sporting'), ('sporting', 'benfica'),
            ('benfica', 'porto'), ('porto', 'benfica'),
            ('porto', 'sporting'), ('sporting', 'porto'),
            ('vitoria sc', 'braga'), ('braga', 'vitoria sc')
        ]
    
    async def build_comprehensive_context(self, home_team_id: int, away_team_id: int,
                                        home_team_name: str, away_team_name: str,
                                        fixture_date: datetime) -> Dict:
        """
        Constrói contexto completo do jogo com todos os padrões da Primeira Liga.
        
        Args:
            home_team_id: ID da equipa da casa na API
            away_team_id: ID da equipa visitante na API
            home_team_name: Nome da equipa da casa
            away_team_name: Nome da equipa visitante
            fixture_date: Data e hora do jogo
            
        Returns:
            Dicionário com contexto completo para os modelos
        """
        
        # Contexto base com valores padrão seguros
        context = {
            'home_position': 10,
            'away_position': 10,
            'european_midweek': False,
            'days_rest': 7,
            'home_days_rest': 7,
            'away_days_rest': 7,
            'rest_difference': 0,
            'opponent_strength': 'medium',
            'home_fortress_rating': 5.0,
            'is_derby': False,
            'home_form': 0.5,
            'away_form': 0.5
        }
        
        try:
            logger.info(f"Construindo contexto para {home_team_name} vs {away_team_name}")
            
            # 1. Obter posições na tabela
            await self._get_league_positions(context, home_team_id, away_team_id)
            
            # 2. Analisar forma e descanso das equipas
            await self._analyze_team_rest_and_form(
                context, home_team_id, away_team_id, fixture_date
            )
            
            # 3. Detectar ressaca europeia
            self._detect_european_fatigue(context, home_team_name)
            
            # 4. Calcular fortaleza caseira
            context['home_fortress_rating'] = await self._calculate_home_fortress_rating(
                home_team_id, home_team_name
            )
            
            # 5. Determinar força do adversário
            self._assess_opponent_strength(context)
            
            # 6. Detectar derbies
            self._detect_derby(context, home_team_name, away_team_name)
            
            logger.debug(f"Contexto final: {context}")
            
        except Exception as e:
            logger.error(f"Erro ao construir contexto: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            # Continuar com contexto padrão em caso de erro
        
        return context
    
    async def _get_league_positions(self, context: Dict, home_team_id: int, away_team_id: int):
        """Obtém posições atuais na tabela da liga"""
        try:
            standings = await api_client.get_standings()
            if not standings:
                logger.warning("Não foi possível obter classificação da liga")
                return
            
            for team_data in standings:
                team_id = team_data['team']['id']
                position = team_data['rank']
                
                if team_id == home_team_id:
                    context['home_position'] = position
                    logger.debug(f"Posição casa: {position}")
                elif team_id == away_team_id:
                    context['away_position'] = position
                    logger.debug(f"Posição fora: {position}")
                    
        except Exception as e:
            logger.error(f"Erro ao obter posições: {e}")
    
    async def _analyze_team_rest_and_form(self, context: Dict, home_team_id: int, 
                                        away_team_id: int, fixture_date: datetime):
        """Analisa descanso e forma das equipas"""
        try:
            # Últimos jogos de cada equipa
            home_fixtures = await api_client.get_team_fixtures(home_team_id, last=7, status='FT')
            away_fixtures = await api_client.get_team_fixtures(away_team_id, last=7, status='FT')
            
            # Calcular forma usando helper
            if home_fixtures:
                context['home_form'] = api_processor.calculate_team_form(home_fixtures, home_team_id)
            
            if away_fixtures:
                context['away_form'] = api_processor.calculate_team_form(away_fixtures, away_team_id)
            
            # Calcular dias de descanso
            home_rest = self._calculate_days_rest(home_fixtures, fixture_date)
            away_rest = self._calculate_days_rest(away_fixtures, fixture_date)
            
            context['home_days_rest'] = home_rest
            context['away_days_rest'] = away_rest
            context['days_rest'] = home_rest  # Para compatibilidade
            context['rest_difference'] = home_rest - away_rest
            
            logger.debug(f"Descanso: Casa {home_rest} dias, Fora {away_rest} dias")
            
        except Exception as e:
            logger.error(f"Erro ao analisar descanso e forma: {e}")
    
    def _calculate_days_rest(self, fixtures: List[Dict], fixture_date: datetime) -> int:
        """Calcula dias de descanso desde o último jogo"""
        if not fixtures:
            return 7  # Default
        
        try:
            last_match_date = datetime_helper.parse_api_datetime(
                fixtures[0]['fixture']['date']
            )
            if last_match_date and fixture_date:
                return datetime_helper.calculate_days_rest(last_match_date, fixture_date)
        except Exception as e:
            logger.error(f"Erro ao calcular dias de descanso: {e}")
        
        return 7  # Default seguro
    
    def _detect_european_fatigue(self, context: Dict, home_team_name: str):
        """Detecta fadiga pós-jogos europeus"""
        try:
            # Verificar se é equipa grande (joga na Europa)
            if team_normalizer.is_big_three(home_team_name):
                days_rest = context['home_days_rest']
                
                # Se jogou há pouco tempo, assumir que foi na Europa
                if days_rest <= self.european_fatigue_days:
                    context['european_midweek'] = True
                    logger.info(f"Fadiga europeia detectada: {home_team_name} com {days_rest} dias")
                    
        except Exception as e:
            logger.error(f"Erro ao detectar fadiga europeia: {e}")
    
    async def _calculate_home_fortress_rating(self, team_id: int, team_name: str) -> float:
        """
        Calcula rating de fortaleza caseira (0-10) baseado em métricas específicas
        """
        try:
            # Não calcular para equipas grandes (elas já são favoritas por padrão)
            if team_normalizer.is_big_three(team_name):
                return 6.0  # Rating médio-alto para grandes
            
            # Obter jogos recentes
            recent_fixtures = await api_client.get_team_fixtures(
                team_id, last=self.min_matches_analysis * 2, status='FT'
            )
            
            if not recent_fixtures:
                return 5.0  # Neutro se não há dados
            
            # Filtrar apenas jogos em casa
            home_games = []
            for fixture in recent_fixtures:
                if len(home_games) >= self.min_matches_analysis:
                    break
                try:
                    if fixture['teams']['home']['id'] == team_id:
                        home_games.append(fixture)
                except (KeyError, TypeError):
                    continue
            
            if len(home_games) < 3:  # Mínimo absoluto
                return 5.0
            
            # Calcular métricas
            metrics = self._calculate_home_metrics(home_games)
            
            # Obter forma recente geral
            recent_form = await self._get_recent_form_score(team_id)
            
            # Aplicar pesos e calcular score final
            weighted_score = (
                metrics['points_per_game'] * self.fortress_weights['home_pts_per_game'] +
                metrics['defensive_score'] * self.fortress_weights['home_ga_per_game'] +
                metrics['clean_sheet_rate'] * self.fortress_weights['home_clean_sheet_rate'] +
                recent_form * self.fortress_weights['recent_form']
            )
            
            # Converter para escala 0-10
            rating = round(weighted_score * 10.0, 1)
            rating = max(0.0, min(10.0, rating))
            
            logger.debug(f"Fortaleza caseira {team_name}: {rating}/10")
            return float(rating)
            
        except Exception as e:
            logger.error(f"Erro ao calcular fortaleza caseira: {e}")
            return 5.0
    
    def _calculate_home_metrics(self, home_games: List[Dict]) -> Dict[str, float]:
        """Calcula métricas específicas dos jogos em casa"""
        total_points = 0
        total_goals_against = 0
        clean_sheets = 0
        games_count = len(home_games)
        
        for game in home_games:
            try:
                result = api_processor.extract_match_result(game)
                home_goals = game['goals']['home'] or 0
                away_goals = game['goals']['away'] or 0
                
                # Pontos
                if result == 'H':  # Vitória casa
                    total_points += 3
                elif result == 'D':  # Empate
                    total_points += 1
                
                # Golos sofridos
                total_goals_against += away_goals
                
                # Clean sheets
                if away_goals == 0:
                    clean_sheets += 1
                    
            except (KeyError, TypeError):
                continue
        
        # Normalizar métricas (0-1)
        points_per_game = total_points / (games_count * 3.0)  # 0-1
        goals_against_per_game = total_goals_against / games_count
        defensive_score = max(0.0, min(1.0, 1.0 - (goals_against_per_game / 2.5)))  # 0-1
        clean_sheet_rate = clean_sheets / games_count  # 0-1
        
        return {
            'points_per_game': points_per_game,
            'defensive_score': defensive_score,
            'clean_sheet_rate': clean_sheet_rate
        }
    
    async def _get_recent_form_score(self, team_id: int) -> float:
        """Calcula score de forma recente (0-1) com pesos decrescentes"""
        try:
            recent_fixtures = await api_client.get_team_fixtures(team_id, last=5, status='FT')
            if not recent_fixtures:
                return 0.5
            
            form_score = 0.0
            weights = [1.0, 0.85, 0.7, 0.55, 0.4]  # Pesos decrescentes
            total_weight = 0.0
            
            for i, fixture in enumerate(recent_fixtures[:5]):
                try:
                    result = api_processor.extract_match_result(fixture)
                    is_home = (fixture['teams']['home']['id'] == team_id)
                    
                    # Determinar pontos baseado no resultado
                    if (result == 'H' and is_home) or (result == 'A' and not is_home):
                        points = 1.0  # Vitória
                    elif result == 'D':
                        points = 0.5  # Empate
                    else:
                        points = 0.0  # Derrota
                    
                    weight = weights[i]
                    form_score += points * weight
                    total_weight += weight
                    
                except (KeyError, TypeError):
                    continue
            
            return form_score / total_weight if total_weight > 0 else 0.5
            
        except Exception as e:
            logger.error(f"Erro ao calcular forma recente: {e}")
            return 0.5
    
    def _assess_opponent_strength(self, context: Dict):
        """Determina força do adversário baseado na posição"""
        away_position = context['away_position']
        
        if away_position <= 4:  # Top 4
            context['opponent_strength'] = 'strong'
        elif away_position >= 13:  # Bottom 6
            context['opponent_strength'] = 'weak'
        else:  # Meio da tabela
            context['opponent_strength'] = 'medium'
    
    def _detect_derby(self, context: Dict, home_team: str, away_team: str):
        """Detecta se é um derby/clássico"""
        try:
            home_normalized = team_normalizer.normalize_team_name(home_team).lower()
            away_normalized = team_normalizer.normalize_team_name(away_team).lower()
            
            # Verificar combinações de derby
            for home_derby, away_derby in self.derby_combinations:
                if (home_derby in home_normalized and away_derby in away_normalized):
                    context['is_derby'] = True
                    logger.info(f"Derby detectado: {home_team} vs {away_team}")
                    return
                    
        except Exception as e:
            logger.error(f"Erro ao detectar derby: {e}")
    
    def get_pattern_summary(self, context: Dict) -> Dict[str, str]:
        """Retorna resumo dos padrões detectados para logging/debug"""
        patterns = []
        
        if context.get('european_midweek'):
            patterns.append("Ressaca Europeia")
        
        if context.get('home_fortress_rating', 0) > self.fortress_rating_threshold:
            patterns.append("Fortaleza Caseira")
        
        if context.get('opponent_strength') == 'weak' and context.get('home_position', 20) <= 6:
            patterns.append("Dominância Hierárquica")
        
        if context.get('is_derby'):
            patterns.append("Derby/Clássico")
        
        if abs(context.get('rest_difference', 0)) >= self.rest_advantage_days:
            patterns.append("Vantagem de Descanso")
        
        return {
            'detected_patterns': patterns,
            'primary_pattern': patterns[0] if patterns else "Caos Meio da Tabela",
            'pattern_count': len(patterns)
        }

# Instância global
pattern_analyzer = PatternAnalyzer()
