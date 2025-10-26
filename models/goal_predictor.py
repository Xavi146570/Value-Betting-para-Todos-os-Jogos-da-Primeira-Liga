import math
import logging
from typing import Dict, List, Tuple, Optional
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

class GoalPredictor:
    def __init__(self):
        """Inicializa o preditor de golos com parâmetros da Primeira Liga"""
        # Médias de golos por jogo na Primeira Liga
        self.base_goals = {
            'home': 1.45,  # Média de golos em casa
            'away': 1.15   # Média de golos fora
        }
        
        # Fatores de ajuste
        self.home_advantage = 0.3
        self.form_weight = 0.25
        self.head_to_head_weight = 0.15
        
        # Limites de segurança para xG
        self.min_goals = 0.2
        self.max_goals = 4.0
        self.max_poisson_goals = 8  # Limite para cálculos de Poisson
        
        # Ajustes contextuais
        self.context_adjustments = {
            'european_competition': -0.15,  # Equipas com jogos europeus
            'cup_fixture': 0.1,             # Jogos de taça
            'derby': 0.2,                   # Derbies
            'relegation_battle': 0.15,      # Luta contra descida
            'title_race': -0.1              # Luta pelo título (mais cauteloso)
        }
    
    def predict_goals(self, home_data: Dict, away_data: Dict, context: Dict = None) -> Dict[str, float]:
        """Prediz golos esperados para ambas as equipas"""
        try:
            # Calcular força de ataque e defesa
            home_attack = self._calculate_attack_strength(home_data, is_home=True)
            home_defense = self._calculate_defense_strength(home_data, is_home=True)
            away_attack = self._calculate_attack_strength(away_data, is_home=False)
            away_defense = self._calculate_defense_strength(away_data, is_home=False)
            
            # Golos esperados base usando médias da liga
            home_expected = self.base_goals['home'] * home_attack * away_defense
            away_expected = self.base_goals['away'] * away_attack * home_defense
            
            # Aplicar vantagem de casa
            home_expected *= (1 + self.home_advantage)
            
            # Ajustes contextuais
            if context:
                home_expected, away_expected = self._apply_context_adjustments(
                    home_expected, away_expected, context
                )
            
            # Aplicar limites realistas
            home_expected = max(self.min_goals, min(self.max_goals, home_expected))
            away_expected = max(self.min_goals, min(self.max_goals, away_expected))
            
            logger.info(f"Golos previstos: Casa {home_expected:.2f}, Fora {away_expected:.2f}")
            
            return {
                'home_goals': home_expected,
                'away_goals': away_expected,
                'total_goals': home_expected + away_expected
            }
            
        except Exception as e:
            logger.error(f"Erro na predição de golos: {e}")
            return {
                'home_goals': 1.4,
                'away_goals': 1.1,
                'total_goals': 2.5
            }
    
    def _calculate_attack_strength(self, team_data: Dict, is_home: bool) -> float:
        """Calcula força ofensiva da equipa"""
        try:
            # Base de ataque da equipa
            base_attack = team_data.get('attack_home' if is_home else 'attack_away', 1.0)
            
            # Ajuste por ELO rating
            elo_rating = team_data.get('elo_rating', 1500)
            elo_factor = 0.8 + (elo_rating - 1500) / 2500  # Normalizar entre 0.6-1.2
            elo_factor = max(0.6, min(1.2, elo_factor))
            
            # Forma recente (se disponível)
            recent_form = team_data.get('recent_form', 0.0)  # -1 a 1
            form_factor = 1.0 + (recent_form * self.form_weight)
            form_factor = max(0.7, min(1.3, form_factor))
            
            attack_strength = base_attack * elo_factor * form_factor
            return max(0.4, min(2.0, attack_strength))
            
        except Exception as e:
            logger.error(f"Erro no cálculo de ataque: {e}")
            return 1.0
    
    def _calculate_defense_strength(self, team_data: Dict, is_home: bool) -> float:
        """Calcula força defensiva da equipa (menor = melhor defesa)"""
        try:
            # Base de defesa da equipa
            base_defense = team_data.get('defense_home' if is_home else 'defense_away', 1.0)
            
            # Ajuste por ELO rating (defesa melhora com rating mais alto)
            elo_rating = team_data.get('elo_rating', 1500)
            elo_factor = 1.2 - (elo_rating - 1500) / 2500  # Normalizar entre 0.8-1.4
            elo_factor = max(0.8, min(1.4, elo_factor))
            
            # Forma defensiva recente
            defensive_form = team_data.get('defensive_form', 0.0)
            form_factor = 1.0 - (defensive_form * self.form_weight * 0.5)
            form_factor = max(0.7, min(1.3, form_factor))
            
            defense_strength = base_defense * elo_factor * form_factor
            return max(0.5, min(1.8, defense_strength))
            
        except Exception as e:
            logger.error(f"Erro no cálculo de defesa: {e}")
            return 1.0
    
    def _apply_context_adjustments(self, home_goals: float, away_goals: float, context: Dict) -> Tuple[float, float]:
        """Aplica ajustes contextuais aos golos esperados"""
        try:
            # Competição europeia (equipas mais cansadas)
            if context.get('european_midweek', False):
                adjustment = self.context_adjustments['european_competition']
                home_goals *= (1 + adjustment)
                away_goals *= (1 + adjustment)
            
            # Diferença de descanso
            rest_diff = context.get('rest_difference', 0)
            if abs(rest_diff) >= 2:  # Diferença significativa
                rest_factor = min(0.15, abs(rest_diff) * 0.05)
                if rest_diff > 0:  # Casa descansou mais
                    home_goals *= (1 + rest_factor)
                    away_goals *= (1 - rest_factor * 0.5)
                else:  # Fora descansou mais
                    away_goals *= (1 + rest_factor)
                    home_goals *= (1 - rest_factor * 0.5)
            
            # Força do adversário
            opponent_strength = context.get('opponent_strength', 'medium')
            if opponent_strength == 'weak':
                home_goals *= 1.2
                away_goals *= 0.9
            elif opponent_strength == 'strong':
                home_goals *= 0.85
                away_goals *= 1.1
            
            # Posição na tabela (pressão)
            home_position = context.get('home_position', 10)
            away_position = context.get('away_position', 10)
            
            # Equipas em posições baixas tendem a ser mais defensivas
            if home_position > 15:
                home_goals *= 0.9
                away_goals *= 0.95
            if away_position > 15:
                away_goals *= 0.85
                home_goals *= 1.05
            
            return home_goals, away_goals
            
        except Exception as e:
            logger.error(f"Erro nos ajustes contextuais: {e}")
            return home_goals, away_goals
    
    def _poisson_pmf(self, lam: float, k: int) -> float:
        """Calcula probabilidade de Poisson para k golos com média lam"""
        try:
            if lam <= 0 or k < 0:
                return 0.0
            return math.exp(-lam) * (lam ** k) / math.factorial(k)
        except (OverflowError, ValueError):
            return 0.0
    
    def goals_to_probabilities(self, home_goals: float, away_goals: float) -> Dict[str, float]:
        """Converte golos esperados em probabilidades - FOCO nos mercados solicitados"""
        try:
            logger.info(f"Convertendo golos em probabilidades: Casa={home_goals:.2f}, Fora={away_goals:.2f}")
            
            # Validar inputs
            home_goals = max(self.min_goals, min(self.max_goals, home_goals))
            away_goals = max(self.min_goals, min(self.max_goals, away_goals))
            
            # Inicializar contadores de probabilidade
            prob_home_win = 0.0
            prob_draw = 0.0
            prob_away_win = 0.0
            prob_over_25 = 0.0
            prob_btts_yes = 0.0
            
            # Calcular probabilidades usando Poisson
            for h in range(self.max_poisson_goals + 1):
                prob_h = self._poisson_pmf(home_goals, h)
                
                for a in range(self.max_poisson_goals + 1):
                    prob_a = self._poisson_pmf(away_goals, a)
                    prob_score = prob_h * prob_a
                    
                    # Resultado 1X2
                    if h > a:
                        prob_home_win += prob_score
                    elif h == a:
                        prob_draw += prob_score
                    else:
                        prob_away_win += prob_score
                    
                    # Over 2.5 golos
                    if (h + a) > 2.5:
                        prob_over_25 += prob_score
                    
                    # BTTS Yes
                    if h >= 1 and a >= 1:
                        prob_btts_yes += prob_score
            
            # Calcular probabilidades complementares
            prob_under_25 = 1.0 - prob_over_25
            prob_btts_no = 1.0 - prob_btts_yes
            
            # Normalizar probabilidades 1X2
            total_1x2 = prob_home_win + prob_draw + prob_away_win
            if total_1x2 > 0:
                prob_home_win /= total_1x2
                prob_draw /= total_1x2
                prob_away_win /= total_1x2
            else:
                # Valores padrão em caso de erro
                prob_home_win, prob_draw, prob_away_win = 0.45, 0.27, 0.28
            
            # Calcular Asian Handicap -1.5 Casa
            prob_ah_home_minus_15 = 0.0
            for h in range(self.max_poisson_goals + 1):
                prob_h = self._poisson_pmf(home_goals, h)
                for a in range(self.max_poisson_goals + 1):
                    if h - a >= 2:  # Casa ganha por 2+ golos
                        prob_a = self._poisson_pmf(away_goals, a)
                        prob_ah_home_minus_15 += prob_h * prob_a
            
            prob_ah_away_plus_15 = 1.0 - prob_ah_home_minus_15
            
            # Aplicar limites de segurança
            probabilities = {
                'home_win': max(0.05, min(0.85, prob_home_win)),
                'draw': max(0.05, min(0.6, prob_draw)),
                'away_win': max(0.05, min(0.85, prob_away_win)),
                'over_25': max(0.1, min(0.9, prob_over_25)),
                'under_25': max(0.1, min(0.9, prob_under_25)),
                'btts_yes': max(0.15, min(0.85, prob_btts_yes)),
                'btts_no': max(0.15, min(0.85, prob_btts_no)),
                'ah_home_minus_15': max(0.05, min(0.8, prob_ah_home_minus_15)),
                'ah_away_plus_15': max(0.2, min(0.95, prob_ah_away_plus_15))
            }
            
            logger.info(f"Probabilidades calculadas para {len(probabilities)} mercados")
            return probabilities
            
        except Exception as e:
            logger.error(f"Erro na conversão golos->probabilidades: {e}")
            return self._get_default_probabilities()
    
    def calculate_match_probabilities(self, home_goals: float, away_goals: float) -> Dict[str, float]:
        """Método alternativo para compatibilidade - chama goals_to_probabilities"""
        return self.goals_to_probabilities(home_goals, away_goals)
    
    def predict_match_probs(self, home_team: Dict, away_team: Dict, context: Dict = None) -> Dict[str, float]:
        """Pipeline completo: estima xG e converte para probabilidades"""
        try:
            # Estimar golos esperados
            goals_data = self.predict_goals(home_team, away_team, context)
            
            # Converter para probabilidades
            probabilities = self.goals_to_probabilities(
                goals_data['home_goals'], 
                goals_data['away_goals']
            )
            
            return probabilities
            
        except Exception as e:
            logger.error(f"Erro no pipeline de predição: {e}")
            return self._get_default_probabilities()
    
    def _get_default_probabilities(self) -> Dict[str, float]:
        """Retorna probabilidades padrão em caso de erro"""
        return {
            'home_win': 0.45, 'draw': 0.27, 'away_win': 0.28,
            'over_25': 0.55, 'under_25': 0.45,
            'btts_yes': 0.6, 'btts_no': 0.4,
            'ah_home_minus_15': 0.3, 'ah_away_plus_15': 0.7
        }
    
    def fair_odds_from_probs(self, probs: Dict[str, float]) -> Dict[str, float]:
        """Converte probabilidades em odds justas (1/prob)"""
        fair_odds = {}
        for market, prob in probs.items():
            if isinstance(prob, (int, float)) and 0 < prob <= 1:
                fair_odds[market] = round(1.0 / prob, 2)
            else:
                fair_odds[market] = 2.0  # Odd padrão
        return fair_odds
    
    def get_market_explanation(self, market: str) -> str:
        """Retorna explicação do mercado"""
        explanations = {
            'home_win': 'Vitória da equipa da casa',
            'draw': 'Empate',
            'away_win': 'Vitória da equipa visitante',
            'over_25': 'Mais de 2.5 golos no jogo',
            'under_25': 'Menos de 2.5 golos no jogo',
            'btts_yes': 'Ambas as equipas marcam',
            'btts_no': 'Pelo menos uma equipa não marca',
            'ah_home_minus_15': 'Casa ganha por 2+ golos (AH -1.5)',
            'ah_away_plus_15': 'Fora não perde por 2+ golos (AH +1.5)'
        }
        return explanations.get(market, f'Mercado: {market}')

# Instância global do preditor
goal_predictor = GoalPredictor()
