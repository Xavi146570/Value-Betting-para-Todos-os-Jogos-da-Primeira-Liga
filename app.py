from fastapi import FastAPI, BackgroundTasks
from fastapi.responses import HTMLResponse
import asyncio
import logging
from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from typing import Dict, List
import traceback

# Imports locais
from config import config
from database import create_tables, get_db, Team, Match, ValueBet
from services.api_football import api_client
from services.telegram_service import telegram_service
from models.elo_system import elo_system
from models.goal_predictor import goal_predictor
from models.value_detector import value_detector

# Setup
app = FastAPI(title="Primeira Liga Value Bot", version="1.0.0")
scheduler = AsyncIOScheduler()

# Configurar logging
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Criar tabelas
create_tables()

class PrimeiraLigaBot:
    def __init__(self):
        self.is_running = False
        self.last_analysis = None
        self.analysis_count = 0
    
    async def analyze_matches(self, days_ahead: int = 3):
        """Analisa jogos dos próximos dias"""
        if self.is_running:
            logger.info("Análise já em execução")
            return
        
        self.is_running = True
        self.analysis_count += 1
        logger.info(f"Iniciando análise #{self.analysis_count} para próximos {days_ahead} dias")
        
        try:
            all_value_bets = []
            matches_analyzed = 0
            
            for day_offset in range(days_ahead):
                target_date = (datetime.now() + timedelta(days=day_offset)).strftime('%Y-%m-%d')
                logger.info(f"Analisando jogos de {target_date}")
                
                fixtures = await api_client.get_fixtures(date=target_date, status='NS')
                logger.info(f"Encontrados {len(fixtures)} jogos para {target_date}")
                
                for fixture in fixtures:
                    try:
                        value_bets = await self._analyze_single_match(fixture)
                        if value_bets:
                            all_value_bets.extend(value_bets)
                            logger.info(f"Encontrados {len(value_bets)} value bets no jogo {fixture['teams']['home']['name']} vs {fixture['teams']['away']['name']}")
                        
                        matches_analyzed += 1
                        await asyncio.sleep(2)  # Rate limit
                        
                    except Exception as e:
                        logger.error(f"Erro ao analisar jogo {fixture.get('fixture', {}).get('id')}: {e}")
                        logger.error(traceback.format_exc())
            
            # Enviar resultados
            await self._send_analysis_results(matches_analyzed, all_value_bets)
            
            self.last_analysis = datetime.now()
            logger.info(f"Análise #{self.analysis_count} concluída: {matches_analyzed} jogos, {len(all_value_bets)} value bets")
            
        except Exception as e:
            logger.error(f"Erro crítico na análise: {e}")
            logger.error(traceback.format_exc())
            await telegram_service.send_system_status("erro", f"Erro crítico: {str(e)}")
        
        finally:
            self.is_running = False
    
    async def _analyze_single_match(self, fixture: Dict) -> List[Dict]:
        """Analisa um jogo específico"""
        try:
            fixture_data = fixture['fixture']
            teams_data = fixture['teams']
            
            home_team_id = teams_data['home']['id']
            away_team_id = teams_data['away']['id']
            
            # Obter dados das equipas
            home_team = await self._get_team_data(home_team_id, teams_data['home']['name'])
            away_team = await self._get_team_data(away_team_id, teams_data['away']['name'])
            
            # Obter contexto do jogo
            context = await self._get_match_context(home_team_id, away_team_id)
            
            # Calcular golos esperados
            home_goals, away_goals = goal_predictor.calculate_expected_goals(
                home_team, away_team, context
            )
            
            # Calcular probabilidades dos mercados
            model_probs = goal_predictor.calculate_market_probabilities(home_goals, away_goals)
            
            # Simular odds de mercado (substituir por API real)
            market_odds = self._simulate_market_odds(model_probs)
            
            # Preparar dados do jogo
            match_data = {
                'home_team': teams_data['home']['name'],
                'away_team': teams_data['away']['name'],
                'home_position': context.get('home_position', 10),
                'away_position': context.get('away_position', 10),
                'european_midweek': context.get('european_midweek', False),
                'match_date': fixture_data['date'][:10],
                'match_time': fixture_data['date'][11:16],
                'fixture_id': fixture_data['id']
            }
            
            # Detectar value bets
            value_bets = value_detector.detect_value_opportunities(
                match_data, model_probs, market_odds
            )
            
            # Adicionar dados do jogo a cada value bet
            for bet in value_bets:
                bet.update({
                    'home_team': match_data['home_team'],
                    'away_team': match_data['away_team'],
                    'match_date': match_data['match_date'],
                    'match_time': match_data['match_time'],
                    'fixture_id': fixture_data['id']
                })
            
            # Salvar na base de dados
            await self._save_value_bets(value_bets)
            
            return value_bets
            
        except Exception as e:
            logger.error(f"Erro na análise individual do jogo: {e}")
            return []
    
    async def _get_team_data(self, team_id: int, team_name: str) -> Dict:
        """Obtém dados de uma equipa"""
        db = next(get_db())
        try:
            team = db.query(Team).filter(Team.api_id == team_id).first()
            if not team:
                team = Team(
                    api_id=team_id,
                    name=team_name,
                    elo_rating=1500.0,
                    attack_home=1.0,
                    attack_away=1.0,
                    defense_home=1.0,
                    defense_away=1.0
                )
                db.add(team)
                db.commit()
                logger.info(f"Nova equipa criada: {team_name}")
            
            return {
                'id': team.api_id,
                'name': team.name,
                'elo_rating': team.elo_rating,
                'attack_home': team.attack_home,
                'attack_away': team.attack_away,
                'defense_home': team.defense_home,
                'defense_away': team.defense_away
            }
        finally:
            db.close()
    
    async def _get_match_context(self, home_team_id: int, away_team_id: int) -> Dict:
        """Obtém contexto do jogo"""
        context = {
            'home_position': 10,
            'away_position': 10,
            'european_midweek': False,
            'days_rest': 7,
            'rest_difference': 0,
            'opponent_strength': 'medium'
        }
        
        try:
            standings = await api_client.get_standings()
            for team in standings:
                if team['team']['id'] == home_team_id:
                    context['home_position'] = team['rank']
                elif team['team']['id'] == away_team_id:
                    context['away_position'] = team['rank']
            
            # Determinar força do adversário
            if context['away_position'] > 12:
                context['opponent_strength'] = 'weak'
            elif context['away_position'] < 6:
                context['opponent_strength'] = 'strong'
            
            # Verificar se é equipa grande (europeia)
            home_team = await self._get_team_data(home_team_id, "")
            if any(big_team in home_team['name'] for big_team in config.BIG_THREE):
                context['european_midweek'] = True
                context['days_rest'] = 3
            
        except Exception as e:
            logger.error(f"Erro ao obter contexto: {e}")
        
        return context
    
    def _simulate_market_odds(self, model_probs: Dict) -> Dict:
        """Simula odds de mercado com margens realistas"""
        margins = {
            'home_win': 0.08, 'draw': 0.06, 'away_win': 0.08,
            'over_25': 0.05, 'under_25': 0.05,
            'btts_yes': 0.06, 'btts_no': 0.06,
            'ah_home_minus_15': 0.04, 'ah_away_plus_15': 0.04
        }
        
        market_odds = {}
        for market, prob in model_probs.items():
            if prob > 0:
                margin = margins.get(market, 0.05)
                adjusted_prob = min(prob * (1 + margin), 0.95)
                market_odds[market] = round(1 / adjusted_prob, 2)
        
        return market_odds
    
    async def _save_value_bets(self, value_bets: List[Dict]):
        """Salva value bets na base de dados"""
        if not value_bets:
            return
        
        db = next(get_db())
        try:
            for bet in value_bets:
                value_bet = ValueBet(
                    match_api_id=bet['fixture_id'],
                    home_team_name=bet['home_team'],
                    away_team_name=bet['away_team'],
                    match_date=datetime.strptime(bet['match_date'], '%Y-%m-%d'),
                    market=bet['market'],
                    odds=bet['odds'],
                    model_prob=bet['model_prob'],
                    market_prob=bet['market_prob'],
                    edge=bet['edge'],
                    confidence=bet['confidence'],
                    stake_amount=bet['stake_amount'],
                    expected_value=bet['expected_value'],
                    pattern_type=bet.get('pattern_type'),
                    pattern_explanation=bet.get('pattern_explanation<span class="cursor">█</span>
