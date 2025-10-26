import logging
from typing import Dict, List, Optional
from datetime import datetime
import math

# Importar config com fallback robusto
try:
    from config import config
except ImportError:
    import os
    class Config:
        MIN_EDGE = float(os.environ.get("MIN_EDGE", "0.03"))          # 3%
        MAX_STAKE_PCT = float(os.environ.get("MAX_STAKE_PCT", "0.02")) # 2%
        KELLY_FRACTION = float(os.environ.get("KELLY_FRACTION", "0.25")) # 25%
        BANKROLL = float(os.environ.get("BANKROLL", "10000"))
        MIN_CONFIDENCE = float(os.environ.get("MIN_CONFIDENCE", "0.15")) # 15%
    config = Config()

logger = logging.getLogger(__name__)

class ValueDetector:
    def __init__(self):
        """Inicializa o detector de value bets com configurações da Primeira Liga"""
        # Parâmetros principais
        self.min_edge = getattr(config, 'MIN_EDGE', 0.03)  # 3% edge mínimo
        self.max_stake_pct = getattr(config, 'MAX_STAKE_PCT', 0.02)  # 2% bankroll máximo
        self.kelly_fraction = getattr(config, 'KELLY_FRACTION', 0.25)  # 25% Kelly fracionário
        self.bankroll = getattr(config, 'BANKROLL', 10000.0)
        self.min_confidence = getattr(config, 'MIN_CONFIDENCE', 0.15)  # 15% confiança mínima
        
        # Limites de segurança
        self.min_odds = 1.2   # Odds mínimas aceites
        self.max_odds = 15.0  # Odds máximas aceites
        self.min_stake = 5.0  # Stake mínimo em euros
        
        logger.info(
            f"💎 ValueDetector inicializado - "
            f"Min Edge: {self.min_edge*100:.1f}%, "
            f"Max Stake: {self.max_stake_pct*100:.1f}%, "
            f"Bankroll: €{self.bankroll:,.0f}, "
            f"Kelly Fraction: {self.kelly_fraction:.0%}"
        )
    
    def find_value_bets(self, model_probs: Dict[str, float], market_odds: Dict[str, float], 
                       fixture_data: Dict) -> List[Dict]:
        """
        Encontra value bets comparando probabilidades do modelo com odds de mercado
        
        Args:
            model_probs: Probabilidades calculadas pelo modelo {'home_win': 0.45, ...}
            market_odds: Odds de mercado {'home_win': 2.10, ...}
            fixture_data: Dados do jogo (id, equipas, data, etc.)
        
        Returns:
            Lista de value bets encontrados
        """
        try:
            value_bets = []
            
            if not model_probs or not market_odds:
                logger.warning("📊 Probabilidades ou odds vazias - nenhuma análise possível")
                return value_bets
            
            home_team = fixture_data.get('home_team', 'N/A')
            away_team = fixture_data.get('away_team', 'N/A')
            
            logger.info(f"🔍 Analisando {len(model_probs)} mercados para {home_team} vs {away_team}")
            
            for market, model_prob in model_probs.items():
                if market not in market_odds:
                    logger.debug(f"❌ Mercado {market} não encontrado nas odds")
                    continue
                
                market_odd = market_odds[market]
                
                # Validações de segurança
                if not self._is_valid_market(model_prob, market_odd, market):
                    continue
                
                # Calcular métricas de value betting
                metrics = self._calculate_value_metrics(model_prob, market_odd)
                
                # Verificar se é value bet
                if metrics['edge'] >= self.min_edge and metrics['confidence'] >= self.min_confidence:
                    # Calcular stake usando Kelly Criterion
                    stake_data = self._calculate_optimal_stake(metrics['edge'], model_prob, market_odd)
                    
                    # Identificar padrão de betting
                    pattern_info = self._identify_betting_pattern(market, market_odd, metrics['edge'], fixture_data)
                    
                    # Construir value bet
                    value_bet = {
                        # Dados do jogo
                        'fixture_id': fixture_data.get('fixture_id'),
                        'home_team': home_team,
                        'away_team': away_team,
                        'match_date': fixture_data.get('match_date'),
                        'match_time': fixture_data.get('match_time'),
                        
                        # Dados da aposta
                        'market': market,
                        'odds': round(market_odd, 2),
                        'model_prob': round(model_prob, 4),
                        'market_prob': round(metrics['implied_prob'], 4),
                        
                        # Métricas de value
                        'edge': round(metrics['edge'], 4),
                        'edge_pct': round(metrics['edge'] * 100, 2),  # Para compatibilidade
                        'confidence': round(metrics['confidence'], 3),
                        
                        # Gestão de bankroll
                        'stake_amount': stake_data['stake'],
                        'expected_value': stake_data['expected_value'],
                        'kelly_percentage': stake_data['kelly_pct'],
                        
                        # Contexto e padrões
                        'pattern_type': pattern_info['type'],
                        'pattern_explanation': pattern_info['explanation'],
                        'risk_level': self._assess_risk_level(metrics['edge'], market_odd),
                        
                        # Metadados
                        'created_at': datetime.now()
                    }
                    
                    value_bets.append(value_bet)
                    
                    logger.info(
                        f"💎 VALUE BET ENCONTRADO: {market} @ {market_odd:.2f} | "
                        f"Edge: {metrics['edge']*100:.1f}% | "
                        f"Confiança: {metrics['confidence']*100:.0f}% | "
                        f"Stake: €{stake_data['stake']:.0f} | "
                        f"EV: €{stake_data['expected_value']:.2f}"
                    )
                else:
                    logger.debug(
                        f"❌ Sem value: {market} @ {market_odd:.2f} "
                        f"(Edge: {metrics['edge']*100:.1f}%, Conf: {metrics['confidence']*100:.0f}%)"
                    )
            
            # Ordenar por expected value descendente
            value_bets.sort(key=lambda x: x['expected_value'], reverse=True)
            
            if value_bets:
                logger.info(f"✅ Encontrados {len(value_bets)} value bets para {home_team} vs {away_team}")
            else:
                logger.info(f"📊 Nenhum value bet encontrado para {home_team} vs {away_team}")
            
            return value_bets
            
        except Exception as e:
            logger.error(f"❌ Erro ao encontrar value bets: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return []
    
    def _is_valid_market(self, model_prob: float, market_odd: float, market: str) -> bool:
        """Valida se o mercado é elegível para análise"""
        try:
            # Validar tipos
            if not isinstance(model_prob, (int, float)) or not isinstance(market_odd, (int, float)):
                logger.debug(f"❌ Tipos inválidos para {market}: prob={type(model_prob)}, odd={type(market_odd)}")
                return False
            
            # Validar probabilidade
            if model_prob <= 0 or model_prob >= 1:
                logger.debug(f"❌ Probabilidade inválida para {market}: {model_prob}")
                return False
            
            # Validar odds
            if market_odd < self.min_odds or market_odd > self.max_odds:
                logger.debug(f"❌ Odds fora dos limites para {market}: {market_odd} (limites: {self.min_odds}-{self.max_odds})")
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Erro na validação do mercado {market}: {e}")
            return False
    
    def _calculate_value_metrics(self, model_prob: float, market_odd: float) -> Dict:
        """Calcula métricas de value betting"""
        try:
            # Probabilidade implícita das odds de mercado
            implied_prob = 1.0 / market_odd
            
            # Edge: retorno esperado por euro apostado - 1
            # Fórmula padrão: Edge = (P_modelo × Odd_mercado) - 1
            edge = (model_prob * market_odd) - 1.0
            
            # Confiança baseada na diferença de probabilidades
            prob_difference = abs(model_prob - implied_prob)
            
            # Confiança escalada: maior diferença = maior confiança
            base_confidence = min(1.0, prob_difference * 4.0)  # Escalar 0-0.25 para 0-1
            
            # Ajuste por magnitude do edge
            if edge > 0.10:  # Edge > 10%
                confidence_multiplier = 1.2
            elif edge > 0.05:  # Edge > 5%
                confidence_multiplier = 1.1
            else:
                confidence_multiplier = 1.0
            
            final_confidence = min(1.0, base_confidence * confidence_multiplier)
            
            return {
                'edge': edge,
                'implied_prob': implied_prob,
                'confidence': final_confidence,
                'prob_difference': prob_difference
            }
            
        except Exception as e:
            logger.error(f"❌ Erro no cálculo de métricas: {e}")
            return {
                'edge': 0.0,
                'implied_prob': 0.5,
                'confidence': 0.0,
                'prob_difference': 0.0
            }
    
    def _calculate_optimal_stake(self, edge: float, model_prob: float, market_odd: float) -> Dict:
        """Calcula stake optimal usando Kelly Criterion fracionário"""
        try:
            # Kelly Criterion: f* = (bp - q) / b
            # onde: b = odds - 1, p = prob_modelo, q = 1 - p
            b = market_odd - 1.0
            p = model_prob
            q = 1.0 - p
            
            if b <= 0:  # Odds inválidas
                kelly_pct = 0.0
            else:
                kelly_optimal = (b * p - q) / b
                kelly_pct = max(0.0, kelly_optimal)
            
            # Aplicar fração de Kelly para reduzir risco
            fractional_kelly = kelly_pct * self.kelly_fraction
            
            # Limitar por percentagem máxima do bankroll
            final_kelly_pct = min(fractional_kelly, self.max_stake_pct)
            
            # Calcular stake em euros
            stake = self.bankroll * final_kelly_pct
            
            # Aplicar stake mínimo
            if final_kelly_pct > 0:
                stake = max(self.min_stake, stake)
            else:
                stake = 0.0
            
            # Expected Value: EV = Stake × Edge
            expected_value = stake * edge
            
            return {
                'kelly_pct': round(final_kelly_pct * 100, 2),
                'stake': round(stake, 0),
                'expected_value': round(expected_value, 2)
            }
            
        except Exception as e:
            logger.error(f"❌ Erro no cálculo de stake: {e}")
            return {
                'kelly_pct': 0.0,
                'stake': 0.0,
                'expected_value': 0.0
            }
    
    def _identify_betting_pattern(self, market: str, odds: float, edge: float, fixture_data: Dict) -> Dict:
        """Identifica padrão de value betting"""
        try:
            # Contexto do jogo
            context = fixture_data.get('context', {})
            home_team = fixture_data.get('home_team', '')
            away_team = fixture_data.get('away_team', '')
            
            # Padrão Favorito (odds baixas)
            if odds <= 1.8:
                return {
                    'type': 'Favorito com Value',
                    'explanation': f'Favorito ({odds:.2f}) com edge de {edge*100:.1f}% - modelo encontra valor em odds baixas'
                }
            
            # Padrão Underdog (odds altas)
            elif odds >= 4.0:
                return {
                    'type': 'Underdog Value',
                    'explanation': f'Underdog ({odds:.2f}) com edge de {edge*100:.1f}% - mercado pode estar a subestimar'
                }
            
            # Padrão Mercados de Golos
            elif market in ['over_25', 'under_25']:
                total_expected = context.get('total_goals', 2.5)
                return {
                    'type': 'Value em Totais',
                    'explanation': f'Mercado de golos ({market}) com edge de {edge*100:.1f}% - xG total: {total_expected:.1f}'
                }
            
            # Padrão BTTS
            elif market in ['btts_yes', 'btts_no']:
                return {
                    'type': 'BTTS Value',
                    'explanation': f'Both Teams To Score ({market}) com edge de {edge*100:.1f}% - análise ofensiva favorável'
                }
            
            # Padrão dos 3 Grandes
            elif any(big in home_team or big in away_team for big in ['Benfica', 'Porto', 'Sporting']):
                return {
                    'type': '3 Grandes Value',
                    'explanation': f'Jogo dos 3 grandes com edge de {edge*100:.1f}% - vantagem competitiva identificada'
                }
            
            # Padrão Standard
            else:
                return {
                    'type': 'Value Padrão',
                    'explanation': f'Value bet em {market} com edge de {edge*100:.1f}% - análise estatística padrão'
                }
                
        except Exception as e:
            logger.error(f"❌ Erro na identificação de padrão: {e}")
            return {
                'type': 'Padrão Desconhecido',
                'explanation': f'Edge de {edge*100:.1f}% detectado'
            }
    
    def _assess_risk_level(self, edge: float, odds: float) -> str:
        """Avalia nível de risco da aposta"""
        try:
            # Matriz de risco baseada em edge e odds
            if edge >= 0.15:  # Edge >= 15%
                if odds <= 3.0:
                    return 'Baixo'
                else:
                    return 'Médio'
            elif edge >= 0.08:  # Edge >= 8%
                if odds <= 4.0:
                    return 'Médio'
                else:
                    return 'Alto'
            elif edge >= 0.05:  # Edge >= 5%
                return 'Alto'
            else:
                return 'Muito Alto'
                
        except Exception as e:
            logger.error(f"❌ Erro na avaliação de risco: {e}")
            return 'Desconhecido'
    
    def get_market_explanation(self, market: str) -> str:
        """Retorna explicação detalhada do mercado"""
        explanations = {
            'home_win': 'Vitória da equipa da casa (1)',
            'draw': 'Empate (X)', 
            'away_win': 'Vitória da equipa visitante (2)',
            'over_25': 'Mais de 2.5 golos no jogo',
            'under_25': 'Menos de 2.5 golos no jogo',
            'btts_yes': 'Ambas as equipas marcam',
            'btts_no': 'Pelo menos uma equipa não marca',
            'ah_home_minus_15': 'Handicap Asiático Casa -1.5',
            'ah_away_plus_15': 'Handicap Asiático Fora +1.5'
        }
        return explanations.get(market, f'Mercado: {market}')

# Instância global do detector
value_detector = ValueDetector()
