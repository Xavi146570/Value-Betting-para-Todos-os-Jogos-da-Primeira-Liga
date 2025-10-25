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
    
    async def send_value_bet_alert(self, value_bet: Dict) -> bool:
        """Envia alerta de value bet formatado"""
        
        pattern_emojis = {
            'Dominancia_Hierarquica': '👑',
            'Ressaca_Europeia': '😴',
            'Fortaleza_Caseira': '🏠',
            'Caos_Meio_Tabela': '⚡',
            'Fortaleza_Defensiva': '🛡️'
        }
        
        market_names = {
            'home_win': 'Vitória Casa (1)',
            'draw': 'Empate (X)',
            'away_win': 'Vitória Fora (2)',
            'over_25': 'Over 2.5 Golos',
            'under_25': 'Under 2.5 Golos',
            'btts_yes': 'Ambas Marcam - Sim',
            'btts_no': 'Ambas Marcam - Não',
            'ah_home_minus_15': 'AH Casa -1.5',
            'ah_away_plus_15': 'AH Fora +1.5',
            'ah_home_minus_125': 'AH Casa -1.25',
            'ah_away_plus_125': 'AH Fora +1.25'
        }
        
        pattern_emoji = pattern_emojis.get(value_bet.get('pattern_type', ''), '🎯')
        market_display = market_names.get(value_bet.get('market', ''), 
                                        value_bet.get('market', '').replace('_', ' ').title())
        
        # Calcular ROI potencial
        roi_potential = ((value_bet.get('odds', 1) - 1) * value_bet.get('model_prob', 0) - 
                        (1 - value_bet.get('model_prob', 0))) * 100
        
        message = f"""
{pattern_emoji} <b>VALUE BET DETECTADO</b> 🎯

🏆 <b>{value_bet.get('home_team', 'N/A')} vs {value_bet.get('away_team', 'N/A')}</b>
📅 <b>Data:</b> {value_bet.get('match_date', 'N/A')} às {value_bet.get('match_time', 'N/A')}

💰 <b>Mercado:</b> {market_display}
📊 <b>Odds:</b> {value_bet.get('odds', 0):.2f}
📈 <b>Edge:</b> +{value_bet.get('edge_pct', 0):.2f}%
🎯 <b>Confiança:</b> {value_bet.get('confidence', 0)*100:.0f}%

💵 <b>Stake Sugerido:</b> €{value_bet.get('stake_amount', 0):.0f} ({value_bet.get('stake_pct', 0):.2f}%)
💎 <b>Expected Value:</b> €{value_bet.get('expected_value', 0):.2f}
📊 <b>ROI Esperado:</b> {roi_potential:.1f}%

🔍 <b>Padrão:</b> {value_bet.get('pattern_type', 'Análise Estatística').replace('_', ' ')}
💡 <b>Explicação:</b> {value_bet.get('pattern_explanation', 'Value identificado por análise estatística')[:200]}

⚠️ <i>Verificar odds atuais antes de apostar</i>
🤖 <i>Bot Primeira Liga - Análise Automática</i>
        """
        
        return await self.send_message(message.strip())
    
    async def send_daily_summary(self, summary: Dict) -> bool:
        """Envia resumo diário das análises"""
        
        # Emojis baseados no número de value bets
        if summary['value_bets_found'] == 0:
            status_emoji = '😴'
            status_text = 'Nenhuma oportunidade'
        elif summary['value_bets_found'] <= 2:
            status_emoji = '🔍'
            status_text = 'Poucas oportunidades'
        elif summary['value_bets_found'] <= 5:
            status_emoji = '🎯'
            status_text = 'Boas oportunidades'
        else:
            status_emoji = '🚀'
            status_text = 'Muitas oportunidades'
        
        message = f"""
📊 <b>RESUMO DIÁRIO - PRIMEIRA LIGA</b> {status_emoji}

📈 <b>Status:</b> {status_text}
🔍 <b>Jogos Analisados:</b> {summary['matches_analyzed']}
🎯 <b>Value Bets Encontrados:</b> {summary['value_bets_found']}
📊 <b>Edge Médio:</b> +{summary['avg_edge']:.2f}%
📅 <b>Data:</b> {datetime.now().strftime('%d/%m/%Y %H:%M')}

🏆 <b>Liga:</b> Primeira Liga {config.SEASON}
💰 <b>Bankroll:</b> €{config.BANKROLL:,.0f}
📈 <b>Edge Mínimo:</b> {config.MIN_EDGE*100}%

🤖 <i>Bot Primeira Liga - Análise Automática</i>
        """
        
        return await self.send_message(message.strip())
    
    async def send_system_status(self, status: str, details: str = "") -> bool:
        """Envia status do sistema"""
        
        status_emojis = {
            'online': '🟢',
            'offline': '🔴',
            'error': '⚠️',
            'erro': '⚠️',
            'warning': '🟡',
            'analyzing': '🔄'
        }
        
        emoji = status_emojis.get(status.lower(), '📊')
        
        message = f"""
{emoji} <b>STATUS DO SISTEMA</b>

📊 <b>Estado:</b> {status.upper()}
📅 <b>Timestamp:</b> {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}
🏆 <b>Liga:</b> Primeira Liga {config.SEASON}

{details}

🤖 <i>Bot Primeira Liga</i>
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
