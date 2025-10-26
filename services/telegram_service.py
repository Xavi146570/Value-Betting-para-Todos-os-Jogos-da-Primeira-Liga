import asyncio
import logging
from typing import Dict, List, Optional
import aiohttp
from datetime import datetime
import os

# Importar config com tratamento de erro
try:
    from config import config
except ImportError:
    # Fallback para variáveis de ambiente se config não existir
    class Config:
        TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
        BANKROLL = float(os.environ.get("BANKROLL", "1000"))
    config = Config()

logger = logging.getLogger(__name__)

class TelegramService:
    def __init__(self):
        self.bot_token = getattr(config, 'TELEGRAM_BOT_TOKEN', '') or os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = getattr(config, 'TELEGRAM_CHAT_ID', '') or os.environ.get("TELEGRAM_CHAT_ID", "")
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}"
        self.session = None
        
        # Validar configuração
        if not self.bot_token:
            logger.warning("TELEGRAM_BOT_TOKEN não configurado. Mensagens não serão enviadas.")
        if not self.chat_id:
            logger.warning("TELEGRAM_CHAT_ID não configurado. Mensagens não serão enviadas.")
    
    async def _get_session(self):
        """Obtém sessão HTTP reutilizável"""
        if self.session is None or self.session.closed:
            timeout = aiohttp.ClientTimeout(total=30)
            self.session = aiohttp.ClientSession(timeout=timeout)
        return self.session
    
    async def _send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        """Envia mensagem para o Telegram com tratamento de rate-limiting"""
        if not self.bot_token or not self.chat_id:
            logger.warning("Telegram não configurado. Mensagem não enviada.")
            return False
        
        try:
            session = await self._get_session()
            
            # Truncar mensagem se muito longa (limite Telegram: 4096 caracteres)
            if len(text) > 4000:
                text = text[:3950] + "\n\n... (mensagem truncada)"
            
            payload = {
                'chat_id': self.chat_id,
                'text': text,
                'parse_mode': parse_mode,
                'disable_web_page_preview': True
            }
            
            async with session.post(f"{self.base_url}/sendMessage", json=payload) as response:
                # Tratamento de rate-limiting (HTTP 429)
                if response.status == 429:
                    retry_after = 3
                    try:
                        error_data = await response.json()
                        retry_after = error_data.get('parameters', {}).get('retry_after', 3)
                    except:
                        pass
                    
                    logger.warning(f"Rate limited pelo Telegram. Aguardando {retry_after}s")
                    await asyncio.sleep(retry_after)
                    
                    # Tentar novamente
                    async with session.post(f"{self.base_url}/sendMessage", json=payload) as retry_response:
                        if retry_response.status == 200:
                            logger.info("Mensagem enviada com sucesso após retry")
                            return True
                        else:
                            error_text = await retry_response.text()
                            logger.error(f"Erro após retry: {retry_response.status} - {error_text}")
                            return False
                
                elif response.status == 200:
                    logger.info("Mensagem enviada com sucesso para Telegram")
                    return True
                else:
                    error_text = await response.text()
                    logger.error(f"Erro ao enviar mensagem: {response.status} - {error_text}")
                    return False
                    
        except Exception as e:
            logger.error(f"Erro ao enviar mensagem para Telegram: {e}")
            return False
    
    def _escape_html(self, text: str) -> str:
        """Sanitiza texto para HTML do Telegram"""
        if not text:
            return ""
        return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    
    def _format_percentage(self, value) -> float:
        """Converte valor para percentagem se necessário"""
        if isinstance(value, (int, float)):
            return value * 100 if value <= 1 else value
        return 0.0
    
    async def send_value_bet_alert(self, bet_data: Dict) -> bool:
        """Envia alerta de value bet"""
        try:
            home_team = self._escape_html(bet_data.get('home_team', 'N/A'))
            away_team = self._escape_html(bet_data.get('away_team', 'N/A'))
            market = self._escape_html(bet_data.get('market', 'N/A'))
            
            edge_pct = self._format_percentage(bet_data.get('edge', 0))
            confidence_pct = self._format_percentage(bet_data.get('confidence', 0))
            
            message = f"""🚨 <b>VALUE BET DETECTADO</b> 🚨

⚽ <b>Jogo:</b> {home_team} vs {away_team}
📅 <b>Data:</b> {bet_data.get('match_date', 'N/A')} às {bet_data.get('match_time', 'N/A')}

📊 <b>Mercado:</b> {market}
💰 <b>Odds:</b> {bet_data.get('odds', 0):.2f}
📈 <b>Edge:</b> {edge_pct:.1f}%
🎯 <b>Confiança:</b> {confidence_pct:.0f}%

💵 <b>Stake Sugerido:</b> €{bet_data.get('stake_amount', 0):.0f}
💎 <b>Valor Esperado:</b> €{bet_data.get('expected_value', 0):.2f}

🔍 <b>Padrão:</b> {self._escape_html(bet_data.get('pattern_type', 'Standard'))}
📝 <b>Explicação:</b> {self._escape_html(bet_data.get('pattern_explanation', 'Análise estatística padrão'))}"""
            
            return await self._send_message(message)
            
        except Exception as e:
            logger.error(f"Erro ao enviar alerta de value bet: {e}")
            return False
    
    async def send_daily_summary(self, summary_data: Dict) -> bool:
        """Envia resumo diário da análise"""
        try:
            matches_analyzed = summary_data.get('matches_analyzed', 0)
            value_bets_found = summary_data.get('value_bets_found', 0)
            avg_edge = summary_data.get('avg_edge', 0)
            focus = self._escape_html(summary_data.get('focus', 'Análise geral'))
            
            bankroll = getattr(config, 'BANKROLL', 1000)
            
            if value_bets_found == 0:
                message = f"""📊 <b>RESUMO DIÁRIO - PRIMEIRA LIGA</b>

🔍 <b>Jogos Analisados:</b> {matches_analyzed}
🎯 <b>Value Bets Encontrados:</b> {value_bets_found}
📈 <b>Foco:</b> {focus}

❌ Nenhuma oportunidade encontrada hoje.
🔄 Próxima análise em algumas horas.
💰 Bankroll: €{bankroll:,.0f}"""
            else:
                message = f"""📊 <b>RESUMO DIÁRIO - PRIMEIRA LIGA</b>

🔍 <b>Jogos Analisados:</b> {matches_analyzed}
🎯 <b>Value Bets Encontrados:</b> {value_bets_found}
📈 <b>Edge Médio:</b> {avg_edge:.1f}%
📊 <b>Foco:</b> {focus}

✅ Alertas individuais enviados acima.
💰 Bankroll atual: €{bankroll:,.0f}"""
            
            return await self._send_message(message)
            
        except Exception as e:
            logger.error(f"Erro ao enviar resumo diário: {e}")
            return False
    
    async def send_system_status(self, status: str, message: str) -> bool:
        """Envia status do sistema"""
        try:
            status_emoji = {
                'online': '🟢',
                'offline': '🔴',
                'error': '🟡',
                'maintenance': '🔧'
            }.get(status.lower(), '⚪')
            
            escaped_message = self._escape_html(message)
            
            full_message = f"""{status_emoji} <b>SISTEMA - {status.upper()}</b>

{escaped_message}

⏰ <b>Timestamp:</b> {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"""
            
            return await self._send_message(full_message)
            
        except Exception as e:
            logger.error(f"Erro ao enviar status do sistema: {e}")
            return False
    
    async def send_match_analysis_summary(self, match_data: Dict, opportunities: List[Dict]) -> bool:
        """Envia resumo de análise de um jogo específico"""
        try:
            home_team = self._escape_html(match_data.get('home_team', 'N/A'))
            away_team = self._escape_html(match_data.get('away_team', 'N/A'))
            match_date = match_data.get('match_date', 'N/A')
            match_time = match_data.get('match_time', 'N/A')
            
            message = f"""🏆 <b>ANÁLISE DE JOGO - PRIMEIRA LIGA</b>

⚽ <b>{home_team} vs {away_team}</b>
📅 <b>Data:</b> {match_date} às {match_time}

🎯 <b>Oportunidades Encontradas:</b> {len(opportunities)}"""
            
            # Ordenar por confiança e mostrar as 3 melhores
            sorted_opps = sorted(opportunities, key=lambda x: x.get('confidence', 0), reverse=True)
            
            for i, opp in enumerate(sorted_opps[:3], 1):
                market = self._escape_html(opp.get('market', 'N/A'))
                edge_pct = self._format_percentage(opp.get('edge', 0))
                confidence_pct = self._format_percentage(opp.get('confidence', 0))
                
                message += f"""

{i}. <b>{market}</b>
   Odds: {opp.get('odds', 0):.2f} | Edge: {edge_pct:.1f}% | Confiança: {confidence_pct:.0f}%"""
            
            return await self._send_message(message)
            
        except Exception as e:
            logger.error(f"Erro ao enviar análise de jogo: {e}")
            return False
    
    async def send_fair_odds_alert(self, opportunity: Dict) -> bool:
        """Envia análise de odds justas para jogos dos 3 grandes"""
        try:
            home_team = self._escape_html(opportunity.get('home_team', 'N/A'))
            away_team = self._escape_html(opportunity.get('away_team', 'N/A'))
            market = self._escape_html(opportunity.get('market', 'N/A'))
            
            edge_pct = self._format_percentage(opportunity.get('edge', 0))
            confidence_pct = self._format_percentage(opportunity.get('confidence', 0))
            
            model_prob = opportunity.get('model_prob', 0.5)
            fair_odds = (1 / model_prob) if model_prob > 0 else 0.0
            
            pattern_explanation = self._escape_html(
                opportunity.get('pattern_explanation', 'Odds de mercado acima do valor justo calculado pelo modelo')
            )
            
            message = f"""⭐ <b>ODDS JUSTAS - 3 GRANDES</b> ⭐

⚽ <b>Jogo:</b> {home_team} vs {away_team}
📅 <b>Data:</b> {opportunity.get('match_date', 'N/A')} às {opportunity.get('match_time', 'N/A')}

📊 <b>Mercado:</b> {market}
💰 <b>Odds de Mercado:</b> {opportunity.get('odds', 0):.2f}
🎯 <b>Odds Justas (Modelo):</b> {fair_odds:.2f}
📈 <b>Vantagem:</b> {edge_pct:.1f}%
🔥 <b>Confiança:</b> {confidence_pct:.0f}%

💡 <b>Análise:</b> {pattern_explanation}

💵 <b>Stake Recomendado:</b> €{opportunity.get('stake_amount', 0):.0f}
💎 <b>Retorno Esperado:</b> €{opportunity.get('expected_value', 0):.2f}"""
            
            return await self._send_message(message)
            
        except Exception as e:
            logger.error(f"Erro ao enviar alerta de odds justas: {e}")
            return False
    
    async def send_error_alert(self, error_message: str, context: str = "") -> bool:
        """Envia alerta de erro do sistema"""
        try:
            escaped_error = self._escape_html(error_message)
            escaped_context = self._escape_html(context)
            
            message = f"""🚨 <b>ERRO NO SISTEMA</b> 🚨

❌ <b>Erro:</b> {escaped_error}
📍 <b>Contexto:</b> {escaped_context}
⏰ <b>Timestamp:</b> {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}

🔧 Verificar logs do sistema para mais detalhes."""
            
            return await self._send_message(message)
            
        except Exception as e:
            logger.error(f"Erro ao enviar alerta de erro: {e}")
            return False
    
    async def send_test_message(self) -> bool:
        """Envia mensagem de teste para verificar conectividade"""
        try:
            message = f"""🧪 <b>TESTE DE CONEXÃO</b>

✅ Bot conectado com sucesso!
⏰ {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}

🏆 Primeira Liga Value Bot operacional."""
            
            return await self._send_message(message)
            
        except Exception as e:
            logger.error(f"Erro ao enviar mensagem de teste: {e}")
            return False
    
    async def close(self):
        """Fecha a sessão HTTP"""
        if self.session and not self.session.closed:
            await self.session.close()
            logger.info("Sessão Telegram fechada")

# Instância global do serviço
telegram_service = TelegramService()
