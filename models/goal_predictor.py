import numpy as np
import math
from typing import Dict, Tuple, Optional
import logging
from config import config

logger = logging.getLogger(__name__)

class GoalPredictor:
    def __init__(self):
        # Média de golos por equipa por jogo na Primeira Liga (calibrada desde 2022)
        self.league_avg = 1.35
        
        # Multiplicadores baseados nos padrões identificados da Primeira Liga
        self.pattern_multipliers = {
            # Dominância Hierárquica
            'big_three_home_vs_weak': 1.25,     # Grandes em casa vs equipas posições 10+
            'big_three_defensive_home': 0.75,   # Defesa dos grandes em casa
            
            # Ressaca Europeia
            'european_fatigue_attack': 0.88,    # Fadiga ofensiva pós-Europa (≤3 dias)
            'european_fatigue_defense': 1.12,   # Defesa mais vulnerável pós-Europa
            
            # Vantagem de Descanso
            'rest_advantage': 1.08,             # Vantagem de 2+ dias de descanso
            'rest_disadvantage': 0.92,          # Desvantagem de 2+ dias
            
            # Fortaleza Caseira
            'home_fortress_attack': 1.15,       # Equipas com forte fator casa (rating > 7)
            'home_fortress_defense': 0.88,      # Defesa reforçada em fortalezas caseiras
            
            # Contextos Específicos
            'derby_tendency': 0.94,             # Clássicos tendem a menos golos
            'mid_table_chaos': 1.06             # Confrontos meio da tabela mais imprevisíveis
        }
        
        # Ratings padrão por categoria de equipa
        self.default_ratings = {
            'big_three': {'attack_home': 1.45, 'attack_away': 1.25, 'defense_home': 0.68, 'defense_away': 0.85},
            'top_half': {'attack_home': 1.15, 'attack_away': 0.95, 'defense_home': 0.88, 'defense_away': 1.05},
            'bottom_half': {'attack_home': 0.92, 'attack_away': 0.75, 'defense_home': 1.12, 'defense_away': 1.28}
        }
    
    def _poisson_pmf(self, k: int, lam: float) -> float:
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
            # Para valores muito grandes, usar aproximação ou retornar 0
            return 0.0
    
    def classify_team_tier(self, team_name: str, league_position: Optional[int] = None) -> str:
        """Classifica equipa em tier baseado no nome e posição na tabela"""
        
        # Verificar se é uma das três grandes
        if any(big_team in team_name for big_team in config.BIG_THREE):
            return 'big_three'
        
        # Classificar por posição na tabela se disponível
        if league_position:
            if league_position <= 9:
                return 'top_half'
            else:
                return 'bottom_half'
        
        # Default para equipas desconhecidas
        return 'bottom_half'
    
    def get_team_ratings(self, team_data: Dict, team_tier: str) -> Dict[str, float]:
        """Obtém ratings da equipa, usando defaults se necessário"""
        
        defaults = self.default_ratings[team_tier]
        
        return {
            'attack_home': float(team_data.get('attack_home', defaults['attack_home'])),
            'attack_away': float(team_data.get('attack_away', defaults['attack_away'])),
            'defense_home': float(team_data.get('defense_home', defaults['defense_home'])),
            'defense_away': float(team_data.get('defense_away', defaults['defense_away']))
        }
    
    def calculate_expected_goals(self, home_team: Dict, away_team: Dict, 
                               context: Dict) -> Tuple[float, float]:
        """
        Calcula golos esperados para cada equipa aplicando padrões da Primeira Liga
        
        Args:
            home_team: Dados da equipa da casa (nome, ratings)
            away_team: Dados da equipa visitante (nome, ratings)  
            context: Contexto do jogo (posições, Europa, descanso, etc.)
        
        Returns:
            Tuple com (golos_esperados_casa, golos_esperados_fora)
        """
        
        # Classificar equipas por tier
        home_tier = self.classify_team_tier(home_team['name'], context.get('home_position'))
        away_tier = self.classify_team_tier(away_team['name'], context.get('away_position'))
        
        # Obter ratings (usar defaults se não disponíveis)
        home_ratings = self.get_team_ratings(home_team, home_tier)
        away_ratings = self.get_team_ratings(away_team, away_tier)
        
        # Cálculo base: Ataque × Defesa × Média Liga
        home_goals_base = home_ratings['attack_home'] * away_ratings['defense_away'] * self.league_avg
        away_goals_base = away_ratings['attack_away'] * home_ratings['defense_home'] * self.league_avg
        
        logger.debug(f"Base expected goals: {home_team['name']} {home_goals_base:.2f}, "
                    f"{away_team['name']} {away_goals_base:.2f}")
        
        # Aplicar ajustes contextuais
        home_goals_adj = self._apply_contextual_adjustments(
            home_goals_base, home_team, away_team, context, 'home', home_tier, away_tier
        )
        
        away_goals_adj = self._apply_contextual_adjustments(
            away_goals_base, away_team, home_team, context, 'away', away_tier, home_tier
        )
        
        # Garantir limites realistas
        home_goals_final = max(0.15, min(4.0, home_goals_adj))
        away_goals_final = max(0.10, min(3.5, away_goals_adj))
        
        logger.info(f"Final expected goals: {home_team['name']} {home_goals_final:.2f}, "
                   f"{away_team['name']} {away_goals_final:.2f}")
        
        return home_goals_final, away_goals_final
    
    def _apply_contextual_adjustments(self, base_goals: float, team: Dict, opponent: Dict,
                                    context: Dict, venue: str, team_tier: str, 
                                    opponent_tier: str) -> float:
        """Aplica ajustes baseados nos padrões identificados da Primeira Liga"""
        
        adjusted = base_goals
        adjustments = []
        
        # Padrão 1: Dominância Hierárquica
        if team_tier == 'big_three' and venue == 'home' and opponent_tier == 'bottom_half':
            multiplier = self.pattern_multipliers['big_three_home_vs_weak']
            adjusted *= multiplier
            adjustments.append(f"Big3 home dominance: {multiplier:.3f}")
        
        # Padrão 2: Ressaca Europeia
        if context.get('european_midweek', False):
            # Verificar se esta equipa jogou na Europa
            if team['name'] in config.BIG_THREE:
                days_rest = context.get('days_rest', 7)
                if days_rest <= 3:
                    multiplier = self.pattern_multipliers['european_fatigue_attack']
                    adjusted *= multiplier
                    adjustments.append(f"European fatigue: {multiplier:.3f}")
        
        # Padrão 3: Vantagem/Desvantagem de Descanso
        rest_diff = context.get('rest_difference', 0)
        if venue == 'home' and rest_diff >= 2:
            multiplier = self.pattern_multipliers['rest_advantage']
            adjusted *= multiplier
            adjustments.append(f"Rest advantage: {multiplier:.3f}")
        elif venue == 'home' and rest_diff <= -2:
            multiplier = self.pattern_multipliers['rest_disadvantage']
            adjusted *= multiplier
            adjustments.append(f"Rest disadvantage: {multiplier:.3f}")
        
        # Padrão 4: Fortaleza Caseira (equipas não-grandes)
        if team_tier != 'big_three' and venue == 'home':
            fortress_rating = context.get('home_fortress_rating', 5.0)
            if fortress_rating > 7.0:
                multiplier = self.pattern_multipliers['home_fortress_attack']
                adjusted *= multiplier
                adjustments.append(f"Home fortress: {multiplier:.3f}")
        
        # Padrão 5: Contextos Específicos
        if context.get('is_derby', False):
            multiplier = self.pattern_multipliers['derby_tendency']
            adjusted *= multiplier
            adjustments.append(f"Derby effect: {multiplier:.3f}")
        
        if team_tier in ['top_half', 'bottom_half'] and opponent_tier in ['top_half', 'bottom_half']:
            multiplier = self.pattern_multipliers['mid_table_chaos']
            adjusted *= multiplier
            adjustments.append(f"Mid-table chaos: {multiplier:.3f}")
        
        # Log ajustes aplicados
        if adjustments and logger.isEnabledFor(logging.DEBUG):
            logger.debug(f"{team['name']} ({venue}): {base_goals:.2f} -> {adjusted:.2f} "
                        f"[{', '.join(adjustments)}]")
        
        return adjusted
    
    def calculate_market_probabilities(self, home_goals: float, away_goals: float,
                                     max_goals: int = 6) -> Dict[str, float]:
        """
        Converte golos esperados em probabilidades de mercado usando Poisson bivariado
        
        Args:
            home_goals: Golos esperados da equipa da casa
            away_goals: Golos esperados da equipa visitante
            max_goals: Número máximo de golos a considerar na matriz
        
        Returns:
            Dicionário com probabilidades para todos os mercados principais
        """
        
        # Validação de inputs
        if home_goals <= 0 or away_goals <= 0:
            logger.warning(f"Invalid goal expectations: H={home_goals:.2f}, A={away_goals:.2f}")
            return self._get_default_probabilities()
        
        # Criar matriz de probabilidades Poisson bivariado
        prob_matrix = np.zeros((max_goals + 1, max_goals + 1))
        
        for h in range(max_goals + 1):
            for a in range(max_goals + 1):
                prob_matrix[h, a] = self._poisson_pmf(h, home_goals) * self._poisson_pmf(a, away_goals)
        
        # Normalizar para garantir soma = 1
        total_prob = np.sum(prob_matrix)
        if total_prob > 0:
            prob_matrix /= total_prob
        else:
            logger.error("Zero total probability in matrix")
            return self._get_default_probabilities()
        
        probabilities = {}
        
        # === MERCADOS PRINCIPAIS ===
        
        # 1X2
        probabilities['home_win'] = float(np.sum([prob_matrix[h, a] 
                                                for h in range(max_goals + 1) 
                                                for a in range(h)]))
        
        probabilities['draw'] = float(np.sum([prob_matrix[i, i] 
                                            for i in range(max_goals + 1)]))
        
        probabilities['away_win'] = float(np.sum([prob_matrix[h, a] 
                                                for h in range(max_goals + 1) 
                                                for a in range(h + 1, max_goals + 1)]))
        
        # Over/Under 1.5
        probabilities['over_15'] = float(np.sum([prob_matrix[h, a] 
                                               for h in range(max_goals + 1) 
                                               for a in range(max_goals + 1) 
                                               if h + a > 1.5]))
        probabilities['under_15'] = 1.0 - probabilities['over_15']
        
        # Over/Under 2.5 (mercado principal)
        probabilities['over_25'] = float(np.sum([prob_matrix[h, a] 
                                               for h in range(max_goals + 1) 
                                               for a in range(max_goals + 1) 
                                               if h + a > 2.5]))
        probabilities['under_25'] = 1.0 - probabilities['over_25']
        
        # Over/Under 3.5
        probabilities['over_35'] = float(np.sum([prob_matrix[h, a] 
                                               for h in range(max_goals + 1) 
                                               for a in range(max_goals + 1) 
                                               if h + a > 3.5]))
        probabilities['under_35'] = 1.0 - probabilities['over_35']
        
        # Both Teams To Score (BTTS)
        probabilities['btts_yes'] = float(np.sum([prob_matrix[h, a] 
                                                for h in range(1, max_goals + 1) 
                                                for a in range(1, max_goals + 1)]))
        probabilities['btts_no'] = 1.0 - probabilities['btts_yes']
        
        # === HANDICAPS ASIÁTICOS ===
        
        # AH -1.5/+1.5 (vitória por 2+ golos)
        probabilities['ah_home_minus_15'] = float(np.sum([prob_matrix[h, a] 
                                                        for h in range(max_goals + 1) 
                                                        for a in range(max_goals + 1) 
                                                        if h - a >= 2]))
        probabilities['ah_away_plus_15'] = 1.0 - probabilities['ah_home_minus_15']
        
        # AH -1.25/+1.25 (split bet: metade em -1.0, metade em -1.5)
        ah_minus_1 = float(np.sum([prob_matrix[h, a] 
                                 for h in range(max_goals + 1) 
                                 for a in range(max_goals + 1) 
                                 if h - a >= 1]))
        probabilities['ah_home_minus_125'] = (ah_minus_1 + probabilities['ah_home_minus_15']) / 2
        probabilities['ah_away_plus_125'] = 1.0 - probabilities['ah_home_minus_125']
        
        # AH -0.5/+0.5 (equivale a vitória)
        probabilities['ah_home_minus_05'] = probabilities['home_win']
        probabilities['ah_away_plus_05'] = probabilities['draw'] + probabilities['away_win']
        
        # === VALIDAÇÃO FINAL ===
        
        # Verificar se probabilidades 1X2 somam 1
        total_1x2 = probabilities['home_win'] + probabilities['draw'] + probabilities['away_win']
        if abs(total_1x2 - 1.0) > 0.001:
            logger.warning(f"1X2 probabilities sum to {total_1x2:.4f}, adjusting...")
            # Normalizar 1X2
            probabilities['home_win'] /= total_1x2
            probabilities['draw'] /= total_1x2
            probabilities['away_win'] /= total_1x2
        
        logger.debug(f"Market probabilities: 1={probabilities['home_win']:.3f}, "
                    f"X={probabilities['draw']:.3f}, 2={probabilities['away_win']:.3f}, "
                    f"O2.5={probabilities['over_25']:.3f}, BTTS={probabilities['btts_yes']:.3f}")
        
        return probabilities
    
    def _get_default_probabilities(self) -> Dict[str, float]:
        """Retorna probabilidades padrão em caso de erro nos cálculos"""
        logger.warning("Using default probabilities due to calculation error")
        return {
            'home_win': 0.45, 'draw': 0.27, 'away_win': 0.28,
            'over_15': 0.75, 'under_15': 0.25,
            'over_25': 0.50, 'under_25': 0.50,
            'over_35': 0.25, 'under_35': 0.75,
            'btts_yes': 0.45, 'btts_no': 0.55,
            'ah_home_minus_15': 0.35, 'ah_away_plus_15': 0.65,
            'ah_home_minus_125': 0.40, 'ah_away_plus_125': 0.60,
            'ah_home_minus_05': 0.45, 'ah_away_plus_05': 0.55
        }
    
    def validate_probabilities(self, probabilities: Dict[str, float]) -> bool:
        """Valida se as probabilidades calculadas são consistentes"""
        
        # Verificar limites (0-1)
        for market, prob in probabilities.items():
            if prob < 0 or prob > 1:
                logger.error(f"Invalid probability for {market}: {prob}")
                return False
        
        # Verificar se mercados complementares somam 1
        complementary_pairs = [
            ('over_25', 'under_25'),
            ('btts_yes', 'btts_no'),
            ('ah_home_minus_15', 'ah_away_plus_15')
        ]
        
        for market1, market2 in complementary_pairs:
            if market1 in probabilities and market2 in probabilities:
                total = probabilities[market1] + probabilities[market2]
                if abs(total - 1.0) > 0.001:
                    logger.warning(f"Complementary markets {market1}/{market2} sum to {total:.4f}")
        
        return True
    
    def get_goal_distribution(self, expected_goals: float, max_goals: int = 6) -> Dict[int, float]:
        """Retorna distribuição de probabilidade por número de golos"""
        distribution = {}
        total_prob = 0
        
        for goals in range(max_goals + 1):
            prob = self._poisson_pmf(goals, expected_goals)
            distribution[goals] = float(prob)
            total_prob += prob
        
        # Adicionar probabilidade de mais golos
        distribution[f'{max_goals}+'] = float(1 - total_prob)
        
        return distribution

# Instância global
goal_predictor = GoalPredictor()
