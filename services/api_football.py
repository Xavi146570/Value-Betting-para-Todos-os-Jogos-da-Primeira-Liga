import aiohttp
import asyncio
import logging
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from config import config

logger = logging.getLogger(__name__)

class APIFootballClient:
    def __init__(self):
        self.base_url = config.API_FOOTBALL_URL.rstrip('/')
        
        # Headers para RapidAPI (mais comum) - altere se usar API direta
        self.headers = {
            'x-rapidapi-key': config.API_FOOTBALL_KEY,
            'x-rapidapi-host': 'v3.football.api-sports.io'
        }
        
        # Para API direta, descomente e comente as linhas acima:
        # self.headers = {
        #     'x-apisports-key': config.API_FOOTBALL_KEY
        # }
        
        self.rate_limit_delay = 2.0  # Ajuste conforme seu plano API
        self.session = None
        self.timeout = aiohttp.ClientTimeout(total=30)
        self.max_retries = 3
    
    async def _get_session(self):
        """Obtém sessão HTTP reutilizável"""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(timeout=self.timeout)
        return self.session
    
    async def _make_request(self, endpoint: str, params: Optional[Dict] = None) -> List[Dict]:
        """Faz requisição à API com controlo de rate limit e retry logic"""
        if not config.API_FOOTBALL_KEY:
            logger.error("API_FOOTBALL_KEY não configurada")
            return []
        
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        
        for attempt in range(self.max_retries):
            try:
                # Rate limiting
                await asyncio.sleep(self.rate_limit_delay)
                
                session = await self._get_session()
                async with session.get(url, headers=self.headers, params=params) as response:
                    
                    if response.status == 200:
                        data = await response.json()
                        
                        # Verificar erros na resposta
                        if isinstance(data, dict):
                            if data.get('errors'):
                                logger.error(f"API returned errors for {endpoint}: {data['errors']}")
                                return []
                            
                            response_data = data.get('response', [])
                            logger.info(f"API Success: {endpoint} - {len(response_data)} items")
                            return response_data
                        
                        return []
                    
                    elif response.status == 429:
                        # Rate limit exceeded
                        wait_time = 60 * (attempt + 1)  # Backoff exponencial
                        logger.warning(f"Rate limit hit for {endpoint}, waiting {wait_time}s (attempt {attempt + 1})")
                        await asyncio.sleep(wait_time)
                        continue
                    
                    elif response.status == 403:
                        logger.error(f"API Key inválida ou sem permissões para {endpoint}")
                        return []
                    
                    else:
                        error_text = await response.text()
                        logger.error(f"API Error {response.status} for {endpoint}: {error_text}")
                        
                        if attempt < self.max_retries - 1:
                            await asyncio.sleep(5 * (attempt + 1))
                            continue
                        return []
                        
            except asyncio.TimeoutError:
                logger.error(f"Timeout for {endpoint} (attempt {attempt + 1})")
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(10)
                    continue
                return []
                
            except aiohttp.ClientError as e:
                logger.error(f"Client error for {endpoint}: {e} (attempt {attempt + 1})")
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(5)
                    continue
                return []
                
            except Exception as e:
                logger.error(f"Unexpected error for {endpoint}: {e} (attempt {attempt + 1})")
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(5)
                    continue
                return []
        
        logger.error(f"All retry attempts failed for {endpoint}")
        return []
    
    async def validate_api_key(self) -> bool:
        """Valida se a chave API está funcionando"""
        try:
            logger.info("Validating API key...")
            data = await self._make_request('status')
            
            if data or isinstance(data, list):  # Resposta válida
                logger.info("API key validation successful")
                return True
            else:
                logger.error("API key validation failed - no valid response")
                return False
                
        except Exception as e:
            logger.error(f"API key validation error: {e}")
            return False
    
    async def get_fixtures(self, date: Optional[str] = None, 
                          status: Optional[str] = None, 
                          fixture_id: Optional[int] = None) -> List[Dict]:
        """
        Obtém fixtures da Primeira Liga
        date: 'YYYY-MM-DD' (opcional)
        status: 'NS' (Not Started), 'FT' (Full Time), etc. (opcional)
        fixture_id: ID específico do jogo (opcional)
        """
        params = {
            'league': config.LEAGUE_ID,
            'season': config.SEASON
        }
        
        if date:
            params['date'] = date
        if status:
            params['status'] = status
        if fixture_id:
            params['id'] = fixture_id
        
        logger.info(f"Fetching fixtures with params: {params}")
        return await self._make_request('fixtures', params)
    
    async def get_fixture_statistics(self, fixture_id: int) -> List[Dict]:
        """Obtém estatísticas detalhadas de um jogo"""
        params = {'fixture': fixture_id}
        logger.info(f"Fetching statistics for fixture {fixture_id}")
        return await self._make_request('fixtures/statistics', params)
    
    async def get_fixture_events(self, fixture_id: int) -> List[Dict]:
        """Obtém eventos de um jogo (golos, cartões, substituições)"""
        params = {'fixture': fixture_id}
        return await self._make_request('fixtures/events', params)
    
    async def get_teams(self) -> List[Dict]:
        """Obtém todas as equipas da Primeira Liga"""
        params = {
            'league': config.LEAGUE_ID,
            'season': config.SEASON
        }
        logger.info("Fetching teams from Primeira Liga")
        return await self._make_request('teams', params)
    
    async def get_standings(self) -> List[Dict]:
        """Obtém classificação atual da liga"""
        params = {
            'league': config.LEAGUE_ID,
            'season': config.SEASON
        }
        
        logger.info("Fetching league standings")
        data = await self._make_request('standings', params)
        
        if data and len(data) > 0:
            league_data = data[0].get('league', {})
            standings = league_data.get('standings', [])
            if standings and len(standings) > 0 and isinstance(standings[0], list):
                logger.info(f"Retrieved standings with {len(standings[0])} teams")
                return standings[0]
        
        logger.warning("No standings data found")
        return []
    
    async def get_team_fixtures(self, team_id: int, last: int = 5, 
                               status: str = 'FT') -> List[Dict]:
        """Obtém últimos jogos de uma equipa"""
        params = {
            'team': team_id,
            'league': config.LEAGUE_ID,
            'season': config.SEASON,
            'last': last,
            'status': status
        }
        
        logger.info(f"Fetching last {last} fixtures for team {team_id}")
        return await self._make_request('fixtures', params)
    
    async def get_team_statistics(self, team_id: int) -> Dict:
        """Obtém estatísticas da época de uma equipa"""
        params = {
            'team': team_id,
            'league': config.LEAGUE_ID,
            'season': config.SEASON
        }
        
        data = await self._make_request('teams/statistics', params)
        return data[0] if data else {}
    
    async def get_head_to_head(self, team1_id: int, team2_id: int, 
                              last: int = 10) -> List[Dict]:
        """Obtém histórico de confrontos diretos entre duas equipas"""
        params = {
            'h2h': f"{team1_id}-{team2_id}",
            'last': last
        }
        
        logger.info(f"Fetching H2H: {team1_id} vs {team2_id}")
        return await self._make_request('fixtures/headtohead', params)
    
    async def get_injuries(self, team_id: Optional[int] = None) -> List[Dict]:
        """Obtém lesões das equipas da liga"""
        params = {
            'league': config.LEAGUE_ID,
            'season': config.SEASON
        }
        
        if team_id:
            params['team'] = team_id
        
        return await self._make_request('injuries', params)
    
    async def close(self):
        """Fecha a sessão HTTP"""
        if self.session and not self.session.closed:
            await self.session.close()
            logger.info("HTTP session closed")

# Instância global
api_client = APIFootballClient()
