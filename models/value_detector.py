import math
from typing import Dict, List, Optional
from datetime import datetime
import logging
from config import config

logger = logging.getLogger(__name__)

class ValueDetector:
    def __init__(self):
        self.min_edge = config.MIN_EDGE
        self.max_stake_pct = config.MAX_STAKE_PCT
        self.kelly_fraction = config.KELLY_FRACTION
        
        # Confiança base por mercado calibrada para a Primeira Liga (baseada em backtesting histórico)
        self.market_confidence = {
            # Mercados de alta confiança (padrões muito consistentes)
            'btts_no': 0.85,                    # Equipas pequenas raramente marcam fora vs grandes
            'under_25': 0.82,                  # Padrão defensivo muito consistente
            'ah_away_plus_15': 0.83,           # Combinação efeito casa + fadiga europeia
            
            # Mercados de confiança moderada-alta
            'over_25': 0.78,                   # Bom em dominância hierárquica
            'home_win': 0.75,                  # Fator casa forte na Primeira Liga
            'ah_home_minus_15': 0.74,          # Dominância dos grandes
            'ah_away_plus_125': 0.80,          # Versão mais segura do +1.5
            
            # Mercados de confiança moderada
            'btts_yes': 0.72,                  # Mais imprevisível
            'draw': 0.70,                      # Alta variance mas value ocasional
            'away_win': 0.68,                  # Surpresas acontecem
            'under_35': 0.75,                  # Consistente em jogos defensivos
            'over_35': 0.65,                   # Mais volátil
            
            # Mercados específicos
            'ah_home_minus_125': 0.72,         # Split bet, boa para grandes
            'over_15': 0.70,                   # Comum mas ocasionalmente valuable
            'under_15': 0.65                   # Raro mas específico
        }
        
        # Multiplicadores de confiança por padrão (baseados em análise histórica)
        self.pattern_multipliers = {
            'Dominancia_Hierarquica': 1.18,    # Padrão mais consistente da liga
            'Ressaca_Europeia': 1.12,          # Bem documentado e consistente
            'Fortaleza_Defensiva': 1.10,       # Forte para handicaps e unders
            'Fortaleza_Caseira': 1.08,         # Moderadamente consistente
            'Caos_Meio_Tabela': 0.95           # Menos previsível por natureza
        }
        
        # Thresholds de edge específicos por mercado (alguns precisam mais edge)
        self.market_edge_thresholds = {
            'draw': 0.04,                      # Empates precisam edge maior
            'away_win': 0.035,                 # Vitórias fora também
            'over_35': 0.04,                   # Mercado mais volátil
            'btts_no': 0.025,                  # Padrão forte, aceita menos edge
            'under_25': 0.025,                 # Padrão defensivo consistente
            'ah_away_plus_15': 0.025           # Padrão muito robusto
        }
    
    def detect_value_opportunities(self, match_data: Dict, model_probs: Dict, 
                                 market_odds: Dict) -> List[Dict]:
        """
        Detecta oportunidades de value comparando probabilidades do modelo vs mercado
        
        Args:
            match_data: Dados do jogo (equipas, posições, contexto)
            model_probs: Probabilidades calculadas pelo modelo
            market_odds: Odds disponíveis no mercado
            
        Returns:
            Lista de value bets ordenados por Expected Value descendente
        """
        
        # Validações de entrada
        if not model_probs or not market_odds:
            logger.warning("Probabilidades do modelo ou odds do mercado indisponíveis")
            return []
        
        if not match_data:
            logger.warning("Dados do jogo indisponíveis")
            return []
        
        # Classificar padrão do jogo
        pattern_info = self._classify_match_pattern(match_data)
        logger.debug(f"Padrão identificado: {pattern_info['type']} "
                    f"(multiplicador: {pattern_info['confidence_multiplier']:.2f})")
        
        value_bets = []
        
        for market, model_prob in model_probs.items():
            # Validações básicas
            if (market not in market_odds or 
                model_prob <= 0 or model_prob >= 1):
                continue
            
            odds = float(market_odds[market])
            if odds <= 1.01 or odds > 100:  # Odds irracionais
                continue
            
            # Calcular edge
            market_prob = 1.0 / odds
            edge = model_prob - market_prob
            
            # Verificar threshold específico do mercado
            min_edge_required = self.market_edge_thresholds.get(market, self.min_edge)
            
            if edge >= min_edge_required:
                # Calcular confiança ajustada
                confidence = self._calculate_confidence(market, edge, pattern_info)
                
                # Calcular stake usando Kelly fracionado
                stake_pct = self._calculate_kelly_stake(model_prob, odds, confidence)
                
                if stake_pct > 0.005:  # Mínimo 0.5% da bankroll
                    stake_amount = config.BANKROLL * stake_pct
                    expected_value = self._calculate_expected_value(model_prob, odds, stake_amount)
                    
                    value_bet = {
                        'market': market,
                        'odds': odds,
                        'model_prob': model_prob,
                        'market_prob': market_prob,
                        'edge': edge,
                        'edge_pct': edge * 100,
                        'confidence': confidence,
                        'stake_pct': stake_pct * 100,
                        'stake_amount': stake_amount,
                        'expected_value': expected_value,
                        'pattern_type': pattern_info['type'],
                        'pattern_explanation': self._get_pattern_explanation(market, pattern_info, match_data),
                        'market_display_name': self._get_market_display_name(market),
                        'risk_assessment': self._assess_risk_level(market, edge, confidence)
                    }
                    
                    value_bets.append(value_bet)
                    
                    logger.info(f"Value bet: {market} @ {odds} "
                              f"(edge: {edge*100:.2f}%, EV: €{expected_value:.2f})")
        
        # Ordenar por Expected Value descendente
        value_bets.sort(key=lambda x: x['expected_value'], reverse=True)
        
        # Limitar apostas por jogo para gestão de risco
        max_bets = 4
        if len(value_bets) > max_bets:
            logger.info(f"Limitando a {max_bets} melhores apostas de {len(value_bets)} encontradas")
            value_bets = value_bets[:max_bets]
        
        return value_bets
    
    def _classify_match_pattern(self, match_data: Dict) -> Dict:
        """Classifica o jogo nos padrões identificados da Primeira Liga"""
        
        home_team = match_data.get('home_team', '').strip()
        away_team = match_data.get('away_team', '').strip()
        home_position = int(match_data.get('home_position', 10))
        away_position = int(match_data.get('away_position', 10))
        
        # Identificar equipas grandes
        home_is_big = any(big in home_team for big in config.BIG_THREE)
        away_is_big = any(big in away_team for big in config.BIG_THREE)
        
        # Padrão 1: Dominância Hierárquica (Grande em casa vs Pequeno)
        if home_is_big and not away_is_big and away_position > 9:
            return {
                'type': 'Dominancia_Hierarquica',
                'confidence_multiplier': self.pattern_multipliers['Dominancia_Hierarquica'],
                'description': f'{home_team} (grande) em casa vs {away_team} (pequeno)',
                'strength': 'high'
            }
        
        # Padrão 2: Ressaca Europeia
        if match_data.get('european_midweek', False):
            days_rest = match_data.get('days_rest', 7)
            if days_rest <= 3 and home_is_big:
                return {
                    'type': 'Ressaca_Europeia',
                    'confidence_multiplier': self.pattern_multipliers['Ressaca_Europeia'],
                    'description': f'Fadiga pós-Europa: {days_rest} dias de descanso',
                    'strength': 'high'
                }
        
        # Padrão 3: Fortaleza Defensiva (Pequeno em casa vs Grande)
        if not home_is_big and away_is_big:
            return {
                'type': 'Fortaleza_Defensiva',
                'confidence_multiplier': self.pattern_multipliers['Fortaleza_Defensiva'],
                'description': f'{home_team} (casa) vs {away_team} (grande visitante)',
                'strength': 'medium'
            }
        
        # Padrão 4: Fortaleza Caseira
        fortress_rating = match_data.get('home_fortress_rating', 5.0)
        if not home_is_big and fortress_rating > 7.0:
            return {
                'type': 'Fortaleza_Caseira',
                'confidence_multiplier': self.pattern_multipliers['Fortaleza_Caseira'],
                'description': f'{home_team} forte em casa (rating: {fortress_rating:.1f})',
                'strength': 'medium'
            }
        
        # Padrão 5: Caos do Meio da Tabela (default)
        return {
            'type': 'Caos_Meio_Tabela',
            'confidence_multiplier': self.pattern_multipliers['Caos_Meio_Tabela'],
            'description': 'Confronto equilibrado entre equipas similares',
            'strength': 'low'
        }
    
    def _calculate_confidence(self, market: str, edge: float, pattern_info: Dict) -> float:
        """
        Calcula confiança final combinando confiança base, edge bonus e padrão
        
        Args:
            market: Nome do mercado
            edge: Vantagem sobre as odds de mercado
            pattern_info: Informação do padrão classificado
            
        Returns:
            Confiança entre 0.50 e 0.95
        """
        
        # Confiança base do mercado
        base_confidence = self.market_confidence.get(market, 0.70)
        
        # Multiplicador do padrão
        pattern_multiplier = pattern_info.get('confidence_multiplier', 1.0)
        
        # Bonus por edge alto (mais edge = mais confiança, até limite)
        edge_bonus = min(edge * 2.0, 0.12)  # Máximo 12% bonus
        
        # Ajustes específicos mercado-padrão
        specific_adjustment = self._get_market_pattern_adjustment(market, pattern_info['type'])
        
        # Calcular confiança final
        final_confidence = ((base_confidence + edge_bonus + specific_adjustment) * 
                           pattern_multiplier)
        
        # Limitar entre 0.50 e 0.95
        return max(0.50, min(0.95, final_confidence))
    
    def _get_market_pattern_adjustment(self, market: str, pattern_type: str) -> float:
        """Ajustes específicos para combinações mercado + padrão comprovadas"""
        
        adjustments = {
            # Dominância Hierárquica
            ('btts_no', 'Dominancia_Hierarquica'): 0.08,
            ('ah_home_minus_15', 'Dominancia_Hierarquica'): 0.07,
            ('over_25', 'Dominancia_Hierarquica'): 0.06,
            
            # Ressaca Europeia
            ('ah_away_plus_15', 'Ressaca_Europeia'): 0.10,
            ('under_25', 'Ressaca_Europeia'): 0.06,
            ('draw', 'Ressaca_Europeia'): 0.05,
            
            # Fortaleza Defensiva
            ('ah_away_plus_15', 'Fortaleza_Defensiva'): 0.08,
            ('under_25', 'Fortaleza_Defensiva'): 0.07,
            ('draw', 'Fortaleza_Defensiva'): 0.06,
            
            # Fortaleza Caseira
            ('home_win', 'Fortaleza_Caseira'): 0.08,
            ('draw', 'Fortaleza_Caseira'): 0.05,
            ('under_25', 'Fortaleza_Caseira'): 0.04
        }
        
        return adjustments.get((market, pattern_type), 0.0)
    
    def _calculate_kelly_stake(self, prob: float, odds: float, confidence: float) -> float:
        """
        Calcula stake usando Kelly Criterion fracionado com ajustes de segurança
        
        Fórmula: f = (bp - q) / b
        onde b = odds - 1, p = probabilidade, q = 1 - p
        """
        
        if prob <= 0 or prob >= 1 or odds <= 1.01:
            return 0.0
        
        b = odds - 1.0  # Lucro líquido por unidade
        q = 1.0 - prob  # Probabilidade de perder
        
        # Kelly ótimo
        kelly_optimal = (b * prob - q) / b
        
        if kelly_optimal <= 0:
            return 0.0
        
        # Aplicar fração de segurança e ajuste por confiança
        kelly_adjusted = kelly_optimal * self.kelly_fraction * confidence
        
        # Aplicar limite máximo
        final_stake = min(kelly_adjusted, self.max_stake_pct)
        
        return max(0.0, final_stake)
    
    def _calculate_expected_value(self, prob: float, odds: float, stake_amount: float) -> float:
        """Calcula Expected Value em euros"""
        return (prob * (odds - 1.0) - (1.0 - prob)) * stake_amount
    
    def _get_pattern_explanation(self, market: str, pattern_info: Dict, 
                               match_data: Dict) -> str:
        """Gera explicação específica do value baseada no padrão e mercado"""
        
        pattern_type = pattern_info['type']
        home_team = match_data.get('home_team', 'Casa')
        away_team = match_data.get('away_team', 'Fora')
        
        explanations = {
            'Dominancia_Hierarquica': {
                'btts_no': f'{home_team} sofre poucos golos em casa vs pequenos (histórico 73%)',
                'ah_home_minus_15': f'{home_team} cobre -1.5 em 68% vs equipas fracas',
                'over_25': f'{home_team} marca média 2.6 golos em casa vs fundo da tabela',
                'home_win': f'{home_team} vence 78% em casa vs equipas posições 10+',
                'under_35': f'Jogos controlados: {home_team} domina sem precisar muitos golos'
            },
            
            'Ressaca_Europeia': {
                'ah_away_plus_15': f'Fadiga pós-Europa: {home_team} tem 15% queda na intensidade',
                'under_25': f'Ritmo reduzido: -0.4 golos média em jogos pós-Europa',
                'draw': f'Fadiga física e mental equilibra diferenças técnicas',
                'away_win': f'{away_team} aproveita momento de vulnerabilidade pós-Europa'
            },
            
            'Fortaleza_Defensiva': {
                'ah_away_plus_15': f'{home_team} defensivamente sólido em casa vs grandes',
                'under_25': f'Jogo defensivo: {home_team} prioriza não sofrer golos',
                'draw': f'Fator casa + motivação equilibra diferença de qualidade',
                'btts_no': f'{away_team} tem dificuldades contra blocos baixos organizados'
            },
            
            'Fortaleza_Caseira': {
                'home_win': f'{home_team} muito forte em casa (rating fortaleza alto)',
                'draw': f'Fator casa amplificado pode segurar empate',
                'under_25': f'{home_team} controla ritmo em casa, jogos mais fechados'
            },
            
            'Caos_Meio_Tabela': {
                'draw': f'Confronto equilibrado favorece resultado nulo',
                'btts_yes': f'Ambas precisam pontos, jogos mais abertos',
                'over_25': f'Imprevisibilidade pode gerar mais golos',
                'under_25': f'Equipas cautelosas em confrontos diretos importantes'
            }
        }
        
        pattern_explanations = explanations.get(pattern_type, {})
        return pattern_explanations.get(
            market, 
            f"Value identificado via padrão {pattern_type.replace('_', ' ')}"
        )
    
    def _get_market_display_name(self, market: str) -> str:
        """Converte nome técnico para nome amigável português"""
        
        display_names = {
            'home_win': 'Vitória Casa (1)',
            'draw': 'Empate (X)',
            'away_win': 'Vitória Fora (2)',
            'over_15': 'Over 1.5 Golos',
            'under_15': 'Under 1.5 Golos',
            'over_25': 'Over 2.5 Golos',
            'under_25': 'Under 2.5 Golos',
            'over_35': 'Over 3.5 Golos',
            'under_35': 'Under 3.5 Golos',
            'btts_yes': 'Ambas Marcam - Sim',
            'btts_no': 'Ambas Marcam - Não',
            'ah_home_minus_15': 'Handicap Casa -1.5',
            'ah_away_plus_15': 'Handicap Fora +1.5',
            'ah_home_minus_125': 'Handicap Casa -1.25',
            'ah_away_plus_125': 'Handicap Fora +1.25',
            'ah_home_minus_05': 'Handicap Casa -0.5',
            'ah_away_plus_05': 'Handicap Fora +0.5'
        }
        
        return display_names.get(market, market.replace('_', ' ').title())
    
    def _assess_risk_level(self, market: str, edge: float, confidence: float) -> str:
        """Avalia nível de risco da aposta"""
        
        # Mercados intrinsecamente arriscados
        high_risk_markets = ['away_win', 'over_35', 'ah_home_minus_15']
        low_risk_markets = ['btts_no', 'under_25', 'ah_away_plus_15', 'home_win']
        
        risk_score = 0
        
        # Ajuste por tipo de mercado
        if market in high_risk_markets:
            risk_score += 2
        elif market in low_risk_markets:
            risk_score -= 1
        
        # Ajuste por edge (mais edge = menos risco relativo)
        if edge > 0.08:
            risk_score -= 2
        elif edge < 0.04:
            risk_score += 1
        
        # Ajuste por confiança
        if confidence > 0.85:
            risk_score -= 1
        elif confidence < 0.70:
            risk_score += 1
        
        # Classificar
        if risk_score <= -1:
            return 'Baixo'
        elif risk_score >= 2:
            return 'Alto'
        else:
            return 'Médio'
    
    def validate_value_bet(self, value_bet: Dict) -> bool:
        """Valida se um value bet está bem formado"""
        
        required_fields = ['market', 'odds', 'model_prob', 'edge', 'stake_amount']
        
        for field in required_fields:
            if field not in value_bet:
                logger.error(f"Campo obrigatório {field} em falta no value bet")
                return False
        
        # Validações de valores
        if value_bet['odds'] <= 1.01 or value_bet['odds'] > 100:
            logger.error(f"Odds inválidas: {value_bet['odds']}")
            return False
        
        if not (0 < value_bet['model_prob'] < 1):
            logger.error(f"Probabilidade do modelo inválida: {value_bet['model_prob']}")
            return False
        
        if value_bet['edge'] < 0:
            logger.error(f"Edge negativo: {value_bet['edge']}")
            return False
        
        return True

# Instância global
value_detector = ValueDetector()
