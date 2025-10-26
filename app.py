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
                
                fixtures = await api_client.get_fixtures(date=target_date)
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
    """Analisa APENAS jogos dos 3 grandes com odds justas"""
    try:
        fixture_data = fixture['fixture']
        teams_data = fixture['teams']
        
        home_team_name = teams_data['home']['name']
        away_team_name = teams_data['away']['name']
        
        # 🎯 FILTRO CRÍTICO: APENAS JOGOS DOS 3 GRANDES
        home_is_big = any(big in home_team_name for big in config.BIG_THREE)
        away_is_big = any(big in away_team_name for big in config.BIG_THREE)
        
        if not (home_is_big or away_is_big):
            logger.debug(f"⏭️ Ignorando: {home_team_name} vs {away_team_name} (sem grandes)")
            return []
        
        logger.info(f"🔍 Analisando jogo dos grandes: {home_team_name} vs {away_team_name}")
        
        home_team_id = teams_data['home']['id']
        away_team_id = teams_data['away']['id']
        
        # Obter dados das equipas
        home_team = await self._get_team_data(home_team_id, home_team_name)
        away_team = await self._get_team_data(away_team_id, away_team_name)
        
        # Obter contexto do jogo
        context = await self._get_match_context(home_team_id, away_team_id)
        
        # Calcular golos esperados
        home_goals, away_goals = goal_predictor.calculate_expected_goals(
            home_team, away_team, context
        )
        
        # Calcular probabilidades dos mercados
        model_probs = goal_predictor.calculate_market_probabilities(home_goals, away_goals)
        
        # Preparar dados do jogo
        match_data = {
            'home_team': home_team_name,
            'away_team': away_team_name,
            'home_position': context.get('home_position', 10),
            'away_position': context.get('away_position', 10),
            'european_midweek': context.get('european_midweek', False),
            'match_date': fixture_data['date'][:10],
            'match_time': fixture_data['date'][11:16],
            'fixture_id': fixture_data['id'],
            'home_is_big': home_is_big,
            'away_is_big': away_is_big
        }
        
        # 🎯 NOVO: Gerar oportunidades com odds justas
        fair_opportunities = value_detector.generate_fair_odds_analysis(
            match_data, model_probs
        )
        
        # Adicionar dados do jogo
        for opportunity in fair_opportunities:
            opportunity.update({
                'home_team': match_data['home_team'],
                'away_team': match_data['away_team'],
                'match_date': match_data['match_date'],
                'match_time': match_data['match_time'],
                'fixture_id': fixture_data['id']
            })
        
        return fair_opportunities
        
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
                    pattern_explanation=bet.get('pattern_explanation')
                )
                db.add(value_bet)
            
            db.commit()
            logger.info(f"Salvos {len(value_bets)} value bets na base de dados")
            
        except Exception as e:
            logger.error(f"Erro ao salvar value bets: {e}")
            db.rollback()
        finally:
            db.close()
    
    async def _send_analysis_results(self, matches_analyzed: int, value_bets: List[Dict]):
        """Envia resultados para Telegram"""
        try:
            if not value_bets:
                await telegram_service.send_daily_summary({
                    'matches_analyzed': matches_analyzed,
                    'value_bets_found': 0,
                    'avg_edge': 0
                })
                return
            
            # Enviar resumo
            avg_edge = sum(bet['edge_pct'] for bet in value_bets) / len(value_bets)
            await telegram_service.send_daily_summary({
                'matches_analyzed': matches_analyzed,
                'value_bets_found': len(value_bets),
                'avg_edge': avg_edge
            })
            
            # Enviar alertas individuais (máximo 8)
            for bet in value_bets[:8]:
                success = await telegram_service.send_value_bet_alert(bet)
                if success:
                    # Marcar como enviado na base de dados
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
                
                await asyncio.sleep(3)  # Pausa entre mensagens
                
        except Exception as e:
            logger.error(f"Erro ao enviar resultados: {e}")

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
async def manual_analysis(background_tasks: BackgroundTasks):
    """Trigger análise manual"""
    if bot.is_running:
        return {"message": "Análise já em execução", "status": "running"}
    
    background_tasks.add_task(bot.analyze_matches)
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
@app.on_event("startup")
async def startup():
    """Configurar análises automáticas"""
    
    # Análise diária às 09:00 e 18:00
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
    
    # Enviar mensagem de inicialização
    await telegram_service.send_system_status(
        "online", 
        f"🚀 Bot iniciado com sucesso!\n📊 Análises automáticas: 09:00 e 18:00\n🏆 Liga: {config.LEAGUE_ID} | Época: {config.SEASON}"
    )

@app.on_event("shutdown")
async def shutdown():
    """Cleanup ao desligar"""
    scheduler.shutdown()
    logger.info("Bot desligado")
    await telegram_service.send_system_status("offline", "🔴 Bot desligado")

# ... (todo o código existente do app.py permanece igual) ...

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
