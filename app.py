from fastapi import FastAPI
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
    self.big_three_opportunities: List[Dict] = []  # NOVO
    
    async def analyze_matches(self, days_ahead: int = 3):
    if self.is_running:
        logger.info("Análise já em execução")
        return
    
    self.is_running = True
    self.analysis_count += 1
    self.big_three_opportunities = []  # NOVO - Limpar lista
    logger.info(f"Iniciando análise #{self.analysis_count} para próximos {days_ahead} dias")
    
    # ... resto do método permanece igual
        
        all_value_bets = []
        matches_analyzed = 0
        
        try:
            for day_offset in range(days_ahead):
                target_date = (datetime.now() + timedelta(days=day_offset)).strftime('%Y-%m-%d')
                logger.info(f"Analisando jogos de {target_date}")
                
                fixtures = await api_client.get_fixtures(date=target_date)
                logger.info(f"Encontrados {len(fixtures)} jogos para {target_date}")
                
                for fixture in fixtures:
                    try:
                        value_bets = await self._analyze_single_match(fixture)
                        if value_bets:
                            all_value_bets.extend(value_bets)
                            logger.info(
                                f"Encontrados {len(value_bets)} value bets no jogo "
                                f"{fixture['teams']['home']['name']} vs {fixture['teams']['away']['name']}"
                            )
                        
                        matches_analyzed += 1
                        await asyncio.sleep(2)  # Rate limit
                        
                    except Exception as e:
                        logger.error(f"Erro ao analisar jogo {fixture.get('fixture', {}).get('id')}: {e}")
                        logger.error(traceback.format_exc())
            
            # Salvar e enviar resultados
            await self._save_value_bets(all_value_bets)
            await self._send_analysis_results(matches_analyzed, all_value_bets)
            
        except Exception as e:
            logger.error(f"Erro geral na análise: {e}")
            logger.error(traceback.format_exc())
        finally:
            self.is_running = False
            self.last_analysis = datetime.now()
            logger.info(
                f"Análise concluída: {matches_analyzed} jogos analisados, {len(all_value_bets)} value bets encontrados"
            )
    
    async def _analyze_single_match(self, fixture: Dict) -> List[Dict]:
    try:
        fixture_id = fixture['fixture']['id']
        home_team = fixture['teams']['home']
        away_team = fixture['teams']['away']
        
        logger.info(f"🔍 Analisando: {home_team['name']} vs {away_team['name']}")
        
        # Verificar se é um dos 3 grandes
        big_three = getattr(config, 'BIG_THREE', ['Benfica', 'Porto', 'Sporting'])
        is_big_game = any(
            bt.lower() in home_team['name'].lower() or bt.lower() in away_team['name'].lower()
            for bt in big_three
        )
        
        if not is_big_game:
            logger.info(f"❌ Jogo ignorado (não envolve os 3 grandes)")
            return []
        
        logger.info(f"✅ Jogo dos 3 grandes detectado!")
        
        # Obter dados das equipas
        home_data = await self._get_team_data(home_team['id'], home_team['name'])
        away_data = await self._get_team_data(away_team['id'], away_team['name'])
        context = await self._get_match_context(home_team['id'], away_team['id'])
        
        # Usar goal_predictor para probabilidades mais precisas
        model_probs = goal_predictor.predict_match_probs(home_data, away_data, context)
        market_odds = self._simulate_market_odds(model_probs)
        
        fixture_data = {
            'fixture_id': fixture_id,
            'home_team': home_team['name'],
            'away_team': away_team['name'],
            'match_date': fixture['fixture']['date'][:10],
            'match_time': fixture['fixture']['date'][11:16],
            'context': context
        }
        
        # Encontrar value bets
        value_bets = value_detector.find_value_bets(
            model_probs=model_probs,
            market_odds=market_odds,
            fixture_data=fixture_data
        )
        
        # NOVO: Guardar oportunidade de "odds justas" para 3 grandes (mesmo sem value)
        if is_big_game:
            best_market = max(model_probs.items(), key=lambda x: x[1])
            market_name, prob = best_market
            fair_odd = round(1.0 / max(0.01, prob), 2)
            
            fair_opportunity = {
                'fixture_id': fixture_id,
                'home_team': home_team['name'],
                'away_team': away_team['name'],
                'match_date': fixture['fixture']['date'][:10],
                'match_time': fixture['fixture']['date'][11:16],
                'market': market_name,
                'odds': fair_odd,
                'model_prob': prob,
                'market_prob': prob,
                'edge': 0.0,
                'confidence': prob,
                'stake_amount': 0.0,
                'expected_value': 0.0,
                'pattern_type': 'Análise 3 Grandes',
                'pattern_explanation': f'Odds justas calculadas pelo modelo para {market_name}'
            }
            self.big_three_opportunities.append(fair_opportunity)
        
        logger.info(f"📊 Value bets encontrados: {len(value_bets)}")
        return value_bets or []
        
    except Exception as e:
        logger.error(f"❌ Erro ao analisar jogo: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return []

    
    async def _get_team_data(self, team_id: int, team_name: str) -> Dict:
        """Obtém dados de uma equipa"""
        db = next(get_db())
        try:
            team = db.query(Team).filter(Team.api_id == team_id).first()
            if not team:
                team = Team(
                    api_id=team_id,
                    name=team_name or f"Team {team_id}",
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
        except Exception as e:
            logger.error(f"Erro ao obter dados da equipa {team_id}: {e}")
            # Retornar dados padrão em caso de erro
            return {
                'id': team_id,
                'name': team_name or f"Team {team_id}",
                'elo_rating': 1500.0,
                'attack_home': 1.0,
                'attack_away': 1.0,
                'defense_home': 1.0,
                'defense_away': 1.0
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
            big_three = getattr(config, 'BIG_THREE', ['Benfica', 'Porto', 'Sporting CP'])
            home_team_data = await self._get_team_data(home_team_id, "")
            if any(bt.lower() in home_team_data['name'].lower() for bt in big_three):
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
                # Verificar se já existe para evitar duplicatas
                existing_bet = db.query(ValueBet).filter(
                    ValueBet.match_api_id == bet['fixture_id'],
                    ValueBet.market == bet['market']
                ).first()
                
                if existing_bet:
                    continue
                
                # Tratar diferentes formatos de edge
                edge_value = bet.get('edge', bet.get('edge_pct', 0))
                if isinstance(edge_value, (int, float)) and edge_value > 1:
                    edge_value = edge_value / 100.0  # Converter percentagem para decimal
                
                value_bet = ValueBet(
                    match_api_id=bet['fixture_id'],
                    home_team_name=bet['home_team'],
                    away_team_name=bet['away_team'],
                    match_date=datetime.strptime(bet['match_date'], '%Y-%m-%d'),
                    market=bet['market'],
                    odds=bet.get('odds', 0.0),
                    model_prob=bet.get('model_prob', 0.0),
                    market_prob=bet.get('market_prob', 0.0),
                    edge=edge_value,
                    confidence=bet.get('confidence', 0.0),
                    stake_amount=bet.get('stake_amount', 0.0),
                    expected_value=bet.get('expected_value', 0.0),
                    pattern_type=bet.get('pattern_type'),
                    pattern_explanation=bet.get('pattern_explanation')
                )
                db.add(value_bet)
            
            db.commit()
            logger.info(f"Salvos {len(value_bets)} value bets na base de dados")
            
        except Exception as e:
            logger.error(f"Erro ao salvar value bets: {e}")
            logger.error(traceback.format_exc())
            db.rollback()
        finally:
            db.close()
    
    async def _send_analysis_results(self, matches_analyzed: int, value_bets: List[Dict]):
    """Envia resultados com fallback para odds justas dos 3 grandes"""
    try:
        # Se não há value bets mas há análises dos 3 grandes, enviar essas
        if not value_bets and self.big_three_opportunities:
            logger.info(f"📤 Enviando análise de odds justas para {len(self.big_three_opportunities)} jogos dos 3 grandes")
            
            # Agrupar por jogo
            games = {}
            for opp in self.big_three_opportunities:
                key = f"{opp['home_team']} vs {opp['away_team']}"
                if key not in games:
                    games[key] = []
                games[key].append(opp)
            
            # Enviar máximo 2 jogos
            sent_count = 0
            for game_key, opportunities in games.items():
                if sent_count >= 2:
                    break
                
                # Dados do jogo
                match_data = {
                    'home_team': opportunities[0]['home_team'],
                    'away_team': opportunities[0]['away_team'],
                    'match_date': opportunities[0]['match_date'],
                    'match_time': opportunities[0]['match_time']
                }
                
                # Enviar análise
                await telegram_service.send_match_analysis_summary(match_data, opportunities)
                await asyncio.sleep(2)
                
                # Melhor oportunidade
                best_opp = max(opportunities, key=lambda x: x.get('confidence', 0))
                await telegram_service.send_fair_odds_alert(best_opp)
                await asyncio.sleep(2)
                
                sent_count += 1
            
            # Resumo especial para 3 grandes
            await telegram_service.send_daily_summary({
                'matches_analyzed': len(games),
                'value_bets_found': 0,
                'avg_edge': 0,
                'focus': '3 Grandes - Odds Justas'
            })
            return
        
        # Fluxo original para value bets encontrados
        if not value_bets:
            await telegram_service.send_daily_summary({
                'matches_analyzed': matches_analyzed,
                'value_bets_found': 0,
                'avg_edge': 0
            })
            return
        
        # Calcular edge médio
        edges = []
        for bet in value_bets:
            edge = bet.get('edge', 0)
            if isinstance(edge, (int, float)):
                edges.append(edge if edge <= 1 else edge / 100.0)
        
        avg_edge = (sum(edges) / len(edges) * 100) if edges else 0
        
        # Enviar resumo
        await telegram_service.send_daily_summary({
            'matches_analyzed': matches_analyzed,
            'value_bets_found': len(value_bets),
            'avg_edge': avg_edge
        })
        
        # Enviar alertas individuais (máximo 8)
        for bet in value_bets[:8]:
            success = await telegram_service.send_value_bet_alert(bet)
            if success:
                # Marcar como enviado
                db = next(get_db())
                try:
                    value_bet = db.query(ValueBet).filter(
                        ValueBet.match_api_id == bet['fixture_id'],
                        ValueBet.market == bet['market']
                    ).first()
                    if value_bet:
                        value_bet.sent_telegram = True
                        db.commit()
                except Exception as e:
                    logger.error(f"Erro ao marcar como enviado: {e}")
                finally:
                    db.close()
            
            await asyncio.sleep(3)
            
    except Exception as e:
        logger.error(f"Erro ao enviar resultados: {e}")
        import traceback
        logger.error(traceback.format_exc())


# Instância global do bot
bot = PrimeiraLigaBot()

# Rotas da API
@app.get("/", response_class=HTMLResponse)
async def root():
    status = "🟡 ANALISANDO" if bot.is_running else "🟢 ONLINE"
    last_analysis = bot.last_analysis.strftime("%d/%m/%Y %H:%M") if bot.last_analysis else "Nunca"
    
    return f"""
    <html>
        <head>
            <title>Primeira Liga Value Bot</title>
            <meta charset="UTF-8">
            <style>
                body {{ font-family: Arial, sans-serif; margin: 40px; background: #f5f5f5; }}
                .container {{ max-width: 800px; margin: 0 auto; background: white; padding: 30px; border-radius: 10px; }}
                .status {{ font-size: 24px; margin: 20px 0; padding: 15px; border-radius: 5px; }}
                .online {{ background: #d4edda; color: #155724; }}
                .analyzing {{ background: #fff3cd; color: #856404; }}
                .info {{ background: #f8f9fa; padding: 20px; border-radius: 8px; margin: 20px 0; }}
                .endpoint {{ background: #e9ecef; padding: 10px; margin: 5px 0; border-radius: 5px; }}
                a {{ color: #007bff; text-decoration: none; }}
                a:hover {{ text-decoration: underline; }}
            </style>
        </head>
        <body>
            <div class="container">
                <h1>🏆 Primeira Liga Value Bot</h1>
                <div class="status {'online' if not bot.is_running else 'analyzing'}">
                    Status: {status}
                </div>
                <div class="info">
                    <p><strong>📊 Última Análise:</strong> {last_analysis}</p>
                    <p><strong>🔢 Análises Realizadas:</strong> {bot.analysis_count}</p>
                    <p><strong>🏆 Liga:</strong> Primeira Liga (ID: {config.LEAGUE_ID})</p>
                    <p><strong>📅 Época:</strong> {config.SEASON}</p>
                    <p><strong>📈 Edge Mínimo:</strong> {config.MIN_EDGE*100}%</p>
                    <p><strong>💰 Bankroll:</strong> €{config.BANKROLL:,.0f}</p>
                </div>
                <h2>🔗 Endpoints Disponíveis:</h2>
                <div class="endpoint"><strong>GET</strong> <a href="/analyze">/analyze</a> - Executar análise manual</div>
                <div class="endpoint"><strong>GET</strong> <a href="/status">/status</a> - Status detalhado (JSON)</div>
                <div class="endpoint"><strong>GET</strong> <a href="/health">/health</a> - Health check</div>
                <div class="endpoint"><strong>GET</strong> <a href="/value-bets">/value-bets</a> - Últimos value bets encontrados</div>
            </div>
        </body>
    </html>
    """

@app.get("/analyze")
async def manual_analysis():
    """Trigger análise manual"""
    if bot.is_running:
        return {"message": "Análise já em execução", "status": "running"}
    
    asyncio.create_task(bot.analyze_matches())
    return {"message": "Análise iniciada em background", "status": "started"}

@app.get("/status")
async def get_status():
    """Status detalhado do sistema"""
    return {
        "status": "running" if bot.is_running else "idle",
        "last_analysis": bot.last_analysis,
        "analysis_count": bot.analysis_count,
        "config": {
            "league_id": config.LEAGUE_ID,
            "season": config.SEASON,
            "min_edge": config.MIN_EDGE,
            "bankroll": config.BANKROLL,
            "max_stake_pct": config.MAX_STAKE_PCT,
            "kelly_fraction": config.KELLY_FRACTION
        }
    }

@app.get("/value-bets")
async def get_recent_value_bets(limit: int = 20):
    """Retorna os value bets mais recentes"""
    db = next(get_db())
    try:
        value_bets = db.query(ValueBet).order_by(ValueBet.created_at.desc()).limit(limit).all()
        return [{
            "id": bet.id,
            "match": f"{bet.home_team_name} vs {bet.away_team_name}",
            "match_date": bet.match_date,
            "market": bet.market,
            "odds": bet.odds,
            "edge": f"{bet.edge*100:.2f}%",
            "confidence": f"{bet.confidence*100:.0f}%",
            "stake": f"€{bet.stake_amount:.0f}",
            "expected_value": f"€{bet.expected_value:.2f}",
            "pattern": bet.pattern_type,
            "sent_telegram": bet.sent_telegram,
            "created_at": bet.created_at
        } for bet in value_bets]
    finally:
        db.close()

@app.get("/health")
async def health_check():
    """Health check para Render"""
    return {
        "status": "healthy", 
        "timestamp": datetime.now(),
        "version": "1.0.0",
        "bot_running": bot.is_running
    }

# Configurar scheduler
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Gestão do ciclo de vida da aplicação"""
    # Startup
    logger.info("🚀 Iniciando sistema...")
    
    scheduler.add_job(
        lambda: asyncio.create_task(bot.analyze_matches()),
        CronTrigger(hour=9, minute=0),
        id='morning_analysis',
        misfire_grace_time=300
    )
    
    scheduler.add_job(
        lambda: asyncio.create_task(bot.analyze_matches()),
        CronTrigger(hour=18, minute=0),
        id='evening_analysis',
        misfire_grace_time=300
    )
    
    scheduler.start()
    logger.info("🚀 Bot iniciado com análises automáticas às 09:00 e 18:00")
    
    await telegram_service.send_system_status(
        "online", 
        f"🚀 Bot iniciado com sucesso!\n📊 Análises automáticas: 09:00 e 18:00\n🏆 Liga: {config.LEAGUE_ID} | Época: {config.SEASON}"
    )
    
    yield
    
    # Shutdown
    scheduler.shutdown()
    logger.info("Bot desligado")
    await telegram_service.send_system_status("offline", "🔴 Bot desligado")

# Aplicar lifespan ao FastAPI
app = FastAPI(
    title="Primeira Liga Value Bot", 
    version="1.0.0",
    lifespan=lifespan
)

# REMOVER as antigas funções @app.on_event("startup") e @app.on_event("shutdown")
@app.get("/analyze-today")
async def analyze_today():
    """Análise forçada do dia de hoje"""
    if bot.is_running:
        return {"message": "Análise já em execução", "status": "running"}
    
    asyncio.create_task(bot.analyze_matches(days_ahead=1))
    return {"message": "Análise de hoje iniciada", "status": "started"}

@app.get("/debug-config")
async def debug_config():
    """Mostra configuração para debugging"""
    return {
        "league_id": getattr(config, 'LEAGUE_ID', 'NÃO DEFINIDO'),
        "season": getattr(config, 'SEASON', 'NÃO DEFINIDO'),
        "big_three": getattr(config, 'BIG_THREE', ['Benfica', 'Porto', 'Sporting']),
        "min_edge": getattr(config, 'MIN_EDGE', 'NÃO DEFINIDO'),
        "bankroll": getattr(config, 'BANKROLL', 'NÃO DEFINIDO'),
        "telegram_configured": bool(getattr(config, 'TELEGRAM_BOT_TOKEN', '')),
        "api_configured": bool(getattr(config, 'API_FOOTBALL_KEY', ''))
    }

@app.get("/test-odds-simulation")
async def test_odds_simulation():
    """Testa a simulação de odds"""
    test_probs = {
        'home_win': 0.5,
        'draw': 0.3,
        'away_win': 0.2
    }
    
    simulated_odds = bot._simulate_market_odds(test_probs)
    
    return {
        "model_probabilities": test_probs,
        "fair_odds": {k: round(1/v, 2) for k, v in test_probs.items()},
        "simulated_market_odds": simulated_odds,
        "potential_edges": {
            k: f"{((simulated_odds[k] * test_probs[k]) - 1) * 100:.1f}%"
            for k in test_probs.keys()
        }
    }


if __name__ == "__main__":
    import os
    import uvicorn
    
    # Ler porta do Railway com fallback seguro
    port = int(os.environ.get("PORT", 8000))
    
    print("=" * 60)
    print("🏆 BOT PRIMEIRA LIGA - INICIANDO SISTEMA")
    print("=" * 60)
    print(f"🚀 Porta: {port}")
    print(f"🌐 URL Principal: http://0.0.0.0:{port}")
    print(f"📊 Health Check: http://0.0.0.0:{port}/health")
    print(f"🎯 Status API: http://0.0.0.0:{port}/status")
    print(f"📈 Value Bets: http://0.0.0.0:{port}/value-bets")
    print("=" * 60)
    
    # Iniciar servidor com configuração otimizada
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=port,
        log_level="info",
        access_log=True,
        reload=False
    )
