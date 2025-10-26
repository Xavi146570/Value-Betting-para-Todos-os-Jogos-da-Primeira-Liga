import asyncio
from telegram import Bot
from telegram.error import TelegramError, NetworkError, RetryAfter
from config import config
import logging
from typing import Dict, List, Optional
from datetime import datetime
import traceback

logger = logging.getLogger(__name__)

class TelegramService:
    def __init__(self):
        if not config.TELEGRAM_BOT_TOKEN:
            logger.error("TELEGRAM_BOT_TOKEN não configurado")
            self.bot = None
            self.chat_id = None
            return
        
        if not config.TELEGRAM_CHAT_ID:
            logger.error("TELEGRAM_CHAT_ID não configurado")
            self.bot = None
            self.chat_id = None
            return
            
        self.bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
        self.chat_id = str(config.TELEGRAM_CHAT_ID)
        self.max_retries = 3
        self.retry_delay = 5
        
        logger.info(f"Telegram service initialized for chat {self.chat_id}")
    
    async def _send_with_retry(self, send_func) -> bool:
        """Envia mensagem com retry logic e tratamento de erros"""
        if not self.bot or not self.chat_id:
            logger.error("Telegram não configurado corretamente")
            return False
        
        for attempt in range(self.max_retries):
            try:
                await send_func()
                logger.info("Mensagem Telegram enviada com sucesso")
                return True
                
            except RetryAfter as e:
                wait_time = e.retry_after + 1
                logger.warning(f"Rate limit Telegram, aguardando {wait_time}s")
                await asyncio.sleep(wait_time)
                continue
                
            except NetworkError as e:
                logger.error(f"Erro de rede Telegram (tentativa {attempt + 1}): {e}")
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self.retry_delay * (attempt + 1))
                    continue
                return False
                
            except TelegramError as e:
                if "message is too long" in str(e).lower():
                    logger.error("Mensagem muito longa para Telegram")
                    return False
                elif "chat not found" in str(e).lower():
                    logger.error(f"Chat ID {self.chat_id} não encontrado")
                    return False
                else:
                    logger.error(f"Erro Telegram (tentativa {attempt + 1}): {e}")
                    if attempt < self.max_retries - 1:
                        await asyncio.sleep(self.retry_delay)
                        continue
                    return False
                    
            except Exception as e:
                logger.error(f"Erro inesperado Telegram (tentativa {attempt + 1}): {e}")
                logger.error(traceback.format_exc())
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self.retry_delay)
                    continue
                return False
        
        logger.error("Todas as tentativas de envio falharam")
        return False
    
    async def send_message(self, text: str, parse_mode: str = 'HTML') -> bool:
        """Envia mensagem básica para o Telegram"""
        if not text or not text.strip():
            logger.warning("Tentativa de enviar mensagem vazia")
            return False
        
        # Truncar mensagem se muito longa
        if len(text) > 4000:
            text = text[:3900] + "\n\n⚠️ <i>Mensagem truncada...</i>"
        
        async def send_func():
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=text,
                parse_mode=parse_mode,
                disable_web_page_preview=True
            )
        
        return await self._send_with_retry(send_func)
    
    async def send_fair_odds_alert(self, opportunity: Dict) -> bool:
    """Envia análise de odds justas para jogos dos 3 grandes"""
    
    pattern_emojis = {
        'Dominancia_Hierarquica': '👑',
        'Ressaca_Europeia': '😴', 
        'Fortaleza_Defensiva': '🛡️',
        'Fortaleza_Caseira': '🏠',
        'Caos_Meio_Tabela': '⚡'
    }
    
    emoji = pattern_emojis.get(opportunity.get('pattern_type', ''), '🎯')
    
    # Identificar qual grande está a jogar
    home_team = opportunity.get('home_team', '')
    away_team = opportunity.get('away_team', '')
    
    big_team = "N/A"
    for big in ['Benfica', 'Porto', 'Sporting']:
        if any(big_name in home_team for big_name in [big, f'SL {big}', f'FC {big}', f'{big} CP']):
            big_team = big
            break
        elif any(big_name in away_team for big_name in [big, f'SL {big}', f'FC {big}', f'{big} CP']):
            big_team = big
            break
    
    message = f"""
{emoji} <b>ANÁLISE DOS 3 GRANDES</b> 🏆

⚽ <b>{home_team} vs {away_team}</b>
📅 <b>Data:</b> {opportunity.get('match_date', 'N/A')} às {opportunity.get('match_time', 'N/A')}
⭐ <b>Grande:</b> {big_team}

💡 <b>MERCADO ANALISADO</b>
💰 <b>Mercado:</b> {opportunity['market_name']}
🎯 <b>Probabilidade Modelo:</b> {opportunity['probability_pct']}%
📊 <b>Odd Justa:</b> {opportunity['fair_odds']}
🔥 <b>Confiança:</b> {opportunity['confidence']*100:.0f}%

🔍 <b>Padrão:</b> {opportunity['pattern_type'].replace('_', ' ')}
💡 <b>Explicação:</b> {opportunity.get('pattern_explanation', '')[:120]}

⚠️ <b>INSTRUÇÕES DE TRADING:</b>
{opportunity.get('bet_instruction', 'Verificar odds de mercado')}
📊 <b>Referência:</b> Odd Justa = {opportunity['fair_odds']}

🤖 <i>Bot Primeira Liga - Foco nos Grandes</i>
        """
    
    return await self.send_message(message.strip())

async def send_match_analysis_summary(self, match_data: Dict, opportunities: List[Dict]) -> bool:
    """Envia resumo completo do jogo analisado"""
    
    if not opportunities:
        return False
    
    home_team = match_data.get('home_team', '')
    away_team = match_data.get('away_team', '')
    main_pattern = opportunities[0].get('pattern_type', '').replace('_', ' ')
    
    # Separar por tipo de mercado
    result_markets = [opp for opp in opportunities if opp['market'] in ['home_win', 'draw', 'away_win']]
    goal_markets = [opp for opp in opportunities if opp['market'].startswith('over_') or opp['market'].startswith('under_')]
    
    message = f"""
📊 <b>RESUMO - JOGO DOS GRANDES</b>

🏆 <b>{home_team} vs {away_team}</b>
📅 {match_data.get('match_date', 'N/A')} às {match_data.get('match_time', 'N/A')}
🔍 <b>Padrão:</b> {main_pattern}

📈 <b>MERCADOS COM ODDS JUSTAS:</b>
"""
    
    # Resultado final
    if result_markets:
        message += "\n🎯 <b>Resultado Final (1X2):</b>"
        for opp in result_markets:
            message += f"\n• {opp['market_name']}: Fair {opp['fair_odds']} ({opp['probability_pct']}%)"
    
    # Over/Under golos
    if goal_markets:
        message += "\n\n⚽ <b>Totais de Golos:</b>"
        for opp in goal_markets:
            message += f"\n• {opp['market_name']}: Fair {opp['fair_odds']} ({opp['probability_pct']}%)"
    
    message += f"""

💡 <b>Compare odds do mercado com valores Fair indicados</b>
🔥 <b>Confiança Média:</b> {sum(opp['confidence'] for opp in opportunities) / len(opportunities) * 100:.0f}%

🤖 <i>Análise focada nos 3 grandes</i>
    """
    
    return await self.send_message(message.strip())

    
    async def send_error_alert(self, error_type: str, error_message: str, 
                              context: Optional[str] = None) -> bool:
        """Envia alerta de erro crítico"""
        
        message = f"""
🚨 <b>ERRO CRÍTICO DETECTADO</b>

⚠️ <b>Tipo:</b> {error_type}
📝 <b>Mensagem:</b> {error_message[:200]}
📅 <b>Timestamp:</b> {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}
"""
        
        if context:
            message += f"\n🔍 <b>Contexto:</b> {context[:100]}"
        
        message += "\n\n🔧 <i>Verificar logs para mais detalhes</i>"
        message += "\n🤖 <i>Bot Primeira Liga</i>"
        
        return await self.send_message(message.strip())
    
    async def test_connection(self) -> bool:
        """Testa conexão com Telegram"""
        test_message = f"""
🧪 <b>TESTE DE CONEXÃO</b>

✅ Bot conectado com sucesso!
📅 {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}
🏆 Liga: {config.LEAGUE_ID} | Época: {config.SEASON}

🤖 <i>Sistema operacional</i>
        """
        
        result = await self.send_message(test_message.strip())
        
        if result:
            logger.info("Teste de conexão Telegram bem-sucedido")
        else:
            logger.error("Teste de conexão Telegram falhou")
        
        return result

# Instância global
telegram_service = TelegramService()
