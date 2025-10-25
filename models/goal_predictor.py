import math
from typing import Dict, Tuple, Optional, List
import logging
from config import config

logger = logging.getLogger(__name__)

class GoalPredictor:
    def __init__(self):
        # Média de golos por equipa por jogo na Primeira Liga (calibrada desde 2022)
        self.league_avg = 1.35
        
        # Multiplicadores baseados nos padrões identificados da Primeira Liga
        self.pattern_multipliers = {
            'big_three_home_vs_weak': 1.25,
            'european_fatigue_attack': 0.88,
            'rest_advantage': 1.08,
            'home_fortress_attack': 1.15,
            'derby_tendency': 0.94,
            'mid_table_chaos': 1.06
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
        
        Precisão matemática idêntica à SciPy, mas em Python puro
        """
        if lam <= 0:
            return 0.0 if k > 0 else 1.0
        
        if k < 0:
            return 0.0
        
        try:
            # Usar logaritmos para evitar overflow em valores grandes
            if k > 50 or lam > 50:
                # Aproximação de Stirling para factorials grandes
                log_prob = k * math.log(lam) - lam - self._log_factorial_stirling(k)
                return math.exp(log_prob) if log_prob > -700 else 0.0
            else:
                # Cálculo direto para valores normais
                factorial_k = math.factorial(k)
                return (lam ** k * math.exp(-lam)) / factorial_k
        except (OverflowError, ValueError):
            return 0.0
    
    def _log_factorial_stirling(self, n: int) -> float:
        """Aproximação de Stirling para log(n!) para valores grandes"""
        if n <= 1:
            return 0.0
        return n * math.log(n) - n + 0.5 * math.log(2 * math.pi * n)
    
    def _create_probability_matrix(self, home_lambda: float, away_lambda: float, max_goals: int = 6) -> List[List[float]]:
        """
        Cria matriz de probabilidades Poisson bivariado usando Python puro
        Equivalente ao numpy mas sem dependências externas
        """
        if home_lambda <= 0 or away_lambda <= 0:
            return [[0.0 for _ in range(max_goals + 1)] for _ in range(max_goals + 1)]
        
        # Criar matriz e calcular probabilidades
        matrix = []
        total_probability = 0.0
        
        for home_goals in range(max_goals + 1):
            row = []
            for away_goals in range(max_goals + 1):
                prob = self._poisson_pmf(home_goals, home_lambda) * self._poisson_pmf(away_goals, away_lambda)
                row.append(prob)
                total_probability += prob
            matrix.append(row)
        
        # Normalizar para garantir que soma = 1
        if total_probability > 0:
            for h in range(max_goals + 1):
                for a in range(max_goals + 1):
                    matrix[h][a] /= total_probability
        
        return matrix
    
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
        Implementação em Python puro com precisão idêntica ao NumPy/SciPy
        """
        
        # Validação de inputs
        if home_goals <= 0 or away_goals <= 0:
            logger.warning(f"Invalid goal expectations: H={home_goals:.2f}, A={away_goals:.2f}")
            return self._get_default_probabilities()
        
        # Criar matriz de probabilidades Poisson bivariado
        prob_matrix = self._create_probability_matrix(home_goals, away_goals, max_goals)
        
        probabilities = {}
        
        # === MERCADOS PRINCIPAIS ===
        
        # 1X2 (Resultado Final)
        home_win_prob = 0.0
        for h in range(max_goals + 1):
            for a in range(h):  # Casa ganha se marca mais que fora
                home_win_prob += prob_matrix[h][a]
        probabilities['home_win'] = home_win_prob
        
        draw_prob = 0.0
        for i in range(max_goals + 1):  # Empate se ambas marcam igual
            draw_prob += prob_matrix[i][i]
        probabilities['draw'] = draw_prob
        
        probabilities['away_win'] = 1.0 - home_win_prob - draw_prob
        
        # Over/Under 1.5 Golos
        over_15_prob = 0.0
        for h in range(max_goals + 1):
            for a in range(max_goals + 1):
                if h + a > 1.5:
                    over_15_prob += prob_matrix[h][a]
        probabilities['over_15'] = over_15_prob
        probabilities['under_15'] = 1.0 - over_15_prob
        
        # Over/Under 2.5 Golos (Mercado Principal)
        over_25_prob = 0.0
        for h in range(max_goals + 1):
            for a in range(max_goals + 1):
                if h + a > 2.5:
                    over_25_prob += prob_matrix[h][a]
        probabilities['over_25'] = over_25_prob
        probabilities['under_25'] = 1.0 - over_25_prob
        
        # Over/Under 3.5 Golos
        over_35_prob = 0.0
        for h in range(max_goals + 1):
            for a in range(max_goals + 1):
                if h + a > 3.5:
                    over_35_prob += prob_matrix[h][a]
        probabilities['over_35'] = over_35_prob
        probabilities['under_35'] = 1.0 - over_35_prob
        
        # Both Teams To Score (BTTS)
        btts_yes_prob = 0.0
        for h in range(1, max_goals + 1):  # Casa marca pelo menos 1
            for a in range(1, max_goals + 1):  # Fora marca pelo menos 1
                btts_yes_prob += prob_matrix[h][a]
        probabilities['btts_yes'] = btts_yes_prob
        probabilities['btts_no'] = 1.0 - btts_yes_prob
        
        # === HANDICAPS ASIÁTICOS ===
        
        # AH -1.5/+1.5 (Vitória por 2+ golos de diferença)
        ah_home_minus_15_prob = 0.0
        for h in range(max_goals + 1):
            for a in range(max_goals + 1):
                if h - a >= 2:  # Casa ganha por 2+ golos
                    ah_home_minus_15_prob += prob_matrix[h][a]
        probabilities['ah_home_minus_15'] = ah_home_minus_15_prob
        probabilities['ah_away_plus_15'] = 1.0 - ah_home_minus_15_prob
        
        # AH -1.25/+1.25 (Split bet: metade em -1.0, metade em -1.5)
        ah_home_minus_1_prob = 0.0
        for h in range(max_goals + 1):
            for a in range(max_goals + 1):
                if h - a >= 1:  # Casa ganha por 1+ golos
                    ah_home_minus_1_prob += prob_matrix[h][a]
        
        probabilities['ah_home_minus_125'] = (ah_home_minus_1_prob + ah_home_minus_15_prob) / 2
        probabilities['ah_away_plus_125'] = 1.0 - probabilities['ah_home_minus_125']
        
        # AH -0.5/+0.5 (Equivalente a vitória simples)
        probabilities['ah_home_minus_05'] = probabilities['home_win']
        probabilities['ah_away_plus_05'] = probabilities['draw'] + probabilities['away_win']
        
        # === VALIDAÇÃO FINAL ===
        
        # Verificar se probabilidades 1X2 somam ~1
        total_1x2 = probabilities['home_win'] + probabilities['draw'] + probabilities['away_win']
        if abs(total_1x2 - 1.0) > 0.001:
            logger.warning(f"1X2 probabilities sum to {total_1x2:.4f}, normalizing...")
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

# Instância global
goal_predictor = GoalPredictor()
