import math
from typing import Dict, Tuple, Optional
from datetime import datetime
import logging
from config import config

logger = logging.getLogger(__name__)

class ELOSystem:
    def __init__(self, k_factor: int = 32, home_advantage: int = None):
        self.k_factor = k_factor
        self.home_advantage = home_advantage if home_advantage is not None else config.HOME_ADVANTAGE
        self.initial_rating = 1500.0
        
        # K-factors dinâmicos baseados na importância do jogo
        self.k_factors = {
            'regular': 32,
            'derby': 40,           # Clássicos entre grandes
            'european_race': 45,   # Jogos de qualificação europeia
            'relegation': 38,      # Jogos de manutenção
            'title_race': 42       # Jogos decisivos para o título
        }
        
        # Ratings iniciais realistas baseados no histórico recente da Primeira Liga
        self.initial_ratings = {
            'Benfica': 1850,
            'SL Benfica': 1850,
            'Sport Lisboa e Benfica': 1850,
            'Porto': 1830,
            'FC Porto': 1830,
            'Futebol Clube do Porto': 1830,
            'Sporting': 1800,
            'Sporting CP': 1800,
            'Sporting Clube de Portugal': 1800,
            'Braga': 1650,
            'SC Braga': 1650,
            'Sporting Clube de Braga': 1650,
            'Vitória SC': 1550,
            'Vitória de Guimarães': 1550,
            'Vitória Sport Clube': 1550,
            'Boavista': 1480,
            'Boavista FC': 1480,
            'Gil Vicente': 1470,
            'Famalicão': 1470,
            'FC Famalicão': 1470,
            'Moreirense': 1460,
            'Moreirense FC': 1460,
            'Santa Clara': 1450,
            'CD Santa Clara': 1450,
            'Casa Pia': 1440,
            'Casa Pia AC': 1440,
            'Arouca': 1430,
            'FC Arouca': 1430,
            'Estoril': 1420,
            'Estoril Praia': 1420,
            'GD Estoril Praia': 1420,
            'Rio Ave': 1410,
            'Rio Ave FC': 1410,
            'Chaves': 1400,
            'GD Chaves': 1400,
            'Vizela': 1390,
            'FC Vizela': 1390,
            'Portimonense': 1380,
            'Portimonense SC': 1380
        }
    
    def get_initial_rating(self, team_name: str) -> float:
        """
        Obtém rating inicial baseado no histórico da equipa
        Usa correspondência flexível para nomes de equipas
        """
        if not team_name:
            return self.initial_rating
        
        team_name_clean = team_name.strip()
        
        # Procura exata primeiro
        if team_name_clean in self.initial_ratings:
            logger.info(f"Rating inicial (exato) para {team_name_clean}: {self.initial_ratings[team_name_clean]}")
            return float(self.initial_ratings[team_name_clean])
        
        # Procura por correspondências parciais
        team_lower = team_name_clean.lower()
        for known_team, rating in self.initial_ratings.items():
            known_lower = known_team.lower()
            
            # Verificar se um nome contém o outro
            if (team_lower in known_lower or known_lower in team_lower or
                # Verificar palavras-chave principais
                any(word in known_lower for word in team_lower.split() if len(word) > 3)):
                logger.info(f"Rating inicial (parcial) para {team_name_clean} -> {known_team}: {rating}")
                return float(rating)
        
        logger.info(f"Rating inicial padrão para {team_name_clean}: {self.initial_rating}")
        return self.initial_rating
    
    def expected_result(self, rating_home: float, rating_away: float, 
                       venue_advantage: Optional[float] = None) -> float:
        """
        Calcula resultado esperado baseado nos ratings ELO
        Retorna probabilidade de vitória da equipa da casa (0-1)
        """
        if venue_advantage is None:
            venue_advantage = self.home_advantage
        
        # Fórmula ELO padrão com vantagem de casa
        rating_diff = rating_away - (rating_home + venue_advantage)
        expected = 1 / (1 + math.pow(10, rating_diff / 400))
        
        # Garantir limites razoáveis
        return max(0.01, min(0.99, expected))
    
    def determine_k_factor(self, home_team: str, away_team: str, 
                          context: Optional[Dict] = None) -> int:
        """
        Determina K-factor baseado na importância e contexto do jogo
        """
        if context is None:
            context = {}
        
        # Identificar equipas grandes
        big_teams = ['Benfica', 'Porto', 'Sporting']
        home_is_big = any(big in home_team for big in big_teams)
        away_is_big = any(big in away_team for big in big_teams)
        
        # Derby entre grandes (clássicos)
        if home_is_big and away_is_big:
            logger.debug(f"Derby detected: {home_team} vs {away_team}")
            return self.k_factors['derby']
        
        # Contexto específico do jogo
        if context.get('title_race', False):
            return self.k_factors['title_race']
        
        if context.get('european_qualification', False):
            return self.k_factors['european_race']
        
        if context.get('relegation_battle', False):
            return self.k_factors['relegation']
        
        return self.k_factors['regular']
    
    def update_ratings(self, rating_home: float, rating_away: float, 
                      result: str, home_team: str = "", away_team: str = "",
                      home_xg: Optional[float] = None, away_xg: Optional[float] = None,
                      context: Optional[Dict] = None) -> Tuple[float, float]:
        """
        Atualiza ratings após um jogo com integração sofisticada de xG
        result: 'H' (home win), 'D' (draw), 'A' (away win)
        """
        
        # Calcular resultado esperado
        expected_home = self.expected_result(rating_home, rating_away)
        
        # Mapear resultado real
        actual_results = {'H': 1.0, 'D': 0.5, 'A': 0.0}
        actual_home = actual_results.get(result, 0.5)
        
        # Ajuste sofisticado baseado em xG
        xg_adjustment = 0
        if (home_xg is not None and away_xg is not None and 
            (home_xg + away_xg) > 0.1):  # Evitar divisão por valores muito baixos
            
            total_xg = home_xg + away_xg
            xg_ratio = home_xg / total_xg
            
            # Analisar discrepância entre performance (xG) e resultado
            performance_vs_result = abs(xg_ratio - actual_home)
            
            # Aplicar ajuste apenas se houve discrepância significativa
            if performance_vs_result > 0.2:  # 20% de diferença
                # Peso do ajuste baseado na magnitude da discrepância
                xg_weight = min(0.25, performance_vs_result * 0.6)
                xg_adjustment = (xg_ratio - expected_home) * xg_weight
                
                logger.debug(f"xG adjustment: {xg_adjustment:.3f} "
                           f"(performance vs result: {performance_vs_result:.3f})")
        
        # Determinar K-factor contextual
        k_factor = self.determine_k_factor(home_team, away_team, context)
        
        # Calcular mudança de rating
        base_change = actual_home - expected_home
        total_change = base_change + xg_adjustment
        rating_change = k_factor * total_change
        
        # Aplicar mudanças
        new_rating_home = rating_home + rating_change
        new_rating_away = rating_away - rating_change
        
        # Log detalhado
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(f"ELO Update: {home_team} {rating_home:.1f} -> {new_rating_home:.1f} "
                        f"({rating_change:+.1f}) vs {away_team} {rating_away:.1f} -> "
                        f"{new_rating_away:.1f} ({-rating_change:+.1f}) "
                        f"[K={k_factor}, Expected={expected_home:.3f}, Actual={actual_home}]")
        
        return new_rating_home, new_rating_away
    
    def get_match_probabilities(self, rating_home: float, rating_away: float) -> Dict[str, float]:
        """
        Calcula probabilidades 1X2 calibradas para a Primeira Liga
        Baseado em análise histórica dos padrões da liga
        """
        expected_home = self.expected_result(rating_home, rating_away)
        
        # Calcular diferença de ratings para calibração
        rating_diff = abs((rating_home + self.home_advantage) - rating_away)
        
        # Probabilidade de empate baseada na diferença de força
        if rating_diff < 50:      # Muito equilibrado
            draw_base = 0.28
        elif rating_diff < 100:   # Equilibrado
            draw_base = 0.26
        elif rating_diff < 200:   # Ligeiro favorito
            draw_base = 0.24
        elif rating_diff < 300:   # Favorito claro
            draw_base = 0.22
        else:                     # Grande diferença
            draw_base = 0.20
        
        # Ajuste fino baseado no expected result
        draw_adjustment = 0.04 - abs(expected_home - 0.5) * 0.08
        prob_draw = max(0.15, min(0.32, draw_base + draw_adjustment))
        
        # Distribuir probabilidade restante
        remaining_prob = 1 - prob_draw
        
        # Aplicar fator de correção específico da Primeira Liga
        # (liga com tendência para mais empates que outras ligas top)
        prob_home = expected_home * remaining_prob * 0.96
        prob_away = (1 - expected_home) * remaining_prob * 0.96
        
        # Normalização final
        total = prob_home + prob_draw + prob_away
        
        if total <= 0:  # Proteção contra erro
            logger.warning("Probabilidades totais inválidas, usando distribuição uniforme")
            return {'home_win': 1/3, 'draw': 1/3, 'away_win': 1/3}
        
        probabilities = {
            'home_win': prob_home / total,
            'draw': prob_draw / total,
            'away_win': prob_away / total
        }
        
        # Validação
        prob_sum = sum(probabilities.values())
        if abs(prob_sum - 1.0) > 0.001:
            logger.warning(f"Probabilidades não normalizam corretamente: {prob_sum}")
        
        return probabilities
    
    def get_rating_analysis(self, rating_home: float, rating_away: float) -> Dict[str, float]:
        """
        Fornece análise detalhada da diferença de ratings e suas implicações
        """
        rating_diff = (rating_home + self.home_advantage) - rating_away
        expected_home = self.expected_result(rating_home, rating_away)
        
        # Nível de confiança baseado na diferença
        confidence = min(0.95, abs(expected_home - 0.5) * 2)
        
        # Probabilidade de surpresa
        upset_prob = 1 - expected_home if rating_diff > 0 else expected_home
        
        return {
            'rating_difference': rating_diff,
            'home_advantage_applied': self.home_advantage,
            'expected_home_prob': expected_home,
            'confidence_level': confidence,
            'upset_probability': upset_prob,
            'match_competitiveness': 1 - confidence,  # Inverso da confiança
            'recommended_markets': self._suggest_markets(expected_home, confidence)
        }
    
    def _suggest_markets(self, expected_home: float, confidence: float) -> List[str]:
        """Sugere mercados com base na análise ELO"""
        suggestions = []
        
        if confidence > 0.7:
            if expected_home > 0.65:
                suggestions.extend(['home_win', 'ah_home_minus_1'])
            elif expected_home < 0.35:
                suggestions.extend(['away_win', 'ah_away_plus_1'])
        
        if confidence < 0.6:  # Jogo equilibrado
            suggestions.extend(['draw', 'double_chance'])
        
        return suggestions
    
    def simulate_rating_evolution(self, current_rating: float, 
                                 results_sequence: List[Tuple[str, float]]) -> List[float]:
        """
        Simula evolução do rating baseada numa sequência de resultados
        results_sequence: Lista de (resultado, rating_adversário)
        """
        rating_evolution = [current_rating]
        current = current_rating
        
        for result, opponent_rating in results_sequence:
            expected = self.expected_result(current, opponent_rating)
            actual = {'H': 1.0, 'D': 0.5, 'A': 0.0}.get(result, 0.5)
            
            change = self.k_factors['regular'] * (actual - expected)
            current += change
            rating_evolution.append(current)
        
        return rating_evolution

# Instância global
elo_system = ELOSystem()
