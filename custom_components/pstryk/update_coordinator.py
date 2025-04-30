"""Data update coordinator for Pstryk Energy integration."""
import logging
from datetime import timedelta
import asyncio
import aiohttp
import async_timeout
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.helpers.event import async_track_point_in_time
from homeassistant.util import dt as dt_util
from .const import API_URL, API_TIMEOUT, BUY_ENDPOINT, SELL_ENDPOINT, DOMAIN

_LOGGER = logging.getLogger(__name__)

def convert_price(value):
    """Convert price string to float."""
    try:
        return round(float(str(value).replace(",", ".").strip()), 2)
    except (ValueError, TypeError) as e:
        _LOGGER.warning("Price conversion error: %s", e)
        return None

class PstrykDataUpdateCoordinator(DataUpdateCoordinator):
    """Coordinator to fetch both current price and today's table."""
    
    def __del__(self):
        """Properly clean up when object is deleted."""
        if hasattr(self, '_unsub_hourly') and self._unsub_hourly:
            self._unsub_hourly()
        if hasattr(self, '_unsub_midnight') and self._unsub_midnight:
            self._unsub_midnight()
            
    def __init__(self, hass, api_key, price_type):
        """Initialize the coordinator."""
        self.hass = hass
        self.api_key = api_key
        self.price_type = price_type
        self._unsub_hourly = None
        self._unsub_midnight = None
        
        # Set a default update interval as a fallback (1 hour)
        # This ensures data is refreshed even if scheduled updates fail
        update_interval = timedelta(hours=1)

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{price_type}",
            update_interval=update_interval,  # Add fallback interval
        )

    async def _async_update_data(self):
        """Fetch 48h of frames and extract current + today's list."""
        _LOGGER.debug("Starting %s price update", self.price_type)
        today_local = dt_util.now().replace(hour=0, minute=0, second=0, microsecond=0)
        window_end_local = today_local + timedelta(days=2)
        start_utc = dt_util.as_utc(today_local).strftime("%Y-%m-%dT%H:%M:%SZ")
        end_utc = dt_util.as_utc(window_end_local).strftime("%Y-%m-%dT%H:%M:%SZ")

        endpoint_tpl = BUY_ENDPOINT if self.price_type == "buy" else SELL_ENDPOINT
        endpoint = endpoint_tpl.format(start=start_utc, end=end_utc)
        url = f"{API_URL}{endpoint}"
        
        _LOGGER.debug("Requesting %s data from %s", self.price_type, url)

        try:
            async with aiohttp.ClientSession() as session:
                try:
                    async with async_timeout.timeout(API_TIMEOUT):
                        resp = await session.get(
                            url,
                            headers={"Authorization": self.api_key, "Accept": "application/json"}
                        )
                        if resp.status != 200:
                            error_text = await resp.text()
                            _LOGGER.error("API error %s for %s: %s", resp.status, self.price_type, error_text)
                            raise UpdateFailed(f"API error {resp.status}: {error_text[:100]}")
                        data = await resp.json()
                except asyncio.TimeoutError:
                    _LOGGER.error("Timeout fetching %s data from API", self.price_type)
                    raise UpdateFailed(f"API timeout after {API_TIMEOUT} seconds")

            frames = data.get("frames", [])
            if not frames:
                _LOGGER.warning("No frames returned for %s prices", self.price_type)
                
            now_utc = dt_util.utcnow()
            prices = []
            current_price = None

            for f in frames:
                val = convert_price(f.get("price_gross"))
                if val is None:
                    continue
                start = dt_util.parse_datetime(f["start"])
                end = dt_util.parse_datetime(f["end"])
                local_start = dt_util.as_local(start).strftime("%Y-%m-%dT%H:%M:%S")
                prices.append({"start": local_start, "price": val})
                if start <= now_utc < end:
                    current_price = val

            # only today's entries
            today_str = today_local.strftime("%Y-%m-%d")
            prices_today = [p for p in prices if p["start"].startswith(today_str)]
            
            _LOGGER.debug("Successfully fetched %s price data: current=%s, today_prices=%d", 
                         self.price_type, current_price, len(prices_today))

            return {
                "prices_today": prices_today,
                "prices": prices,
                "current": current_price,
            }

        except aiohttp.ClientError as err:
            _LOGGER.error("Network error fetching %s data: %s", self.price_type, str(err))
            raise UpdateFailed(f"Network error: {err}")
        except Exception as err:
            _LOGGER.exception("Unexpected error fetching %s data: %s", self.price_type, str(err))
            raise UpdateFailed(f"Error: {err}")

    def schedule_hourly_update(self):
        """Schedule next refresh 1 min after each full hour."""
        if self._unsub_hourly:
            self._unsub_hourly()
            self._unsub_hourly = None
            
        now = dt_util.now()
        # Keep original timing: 1 minute past the hour
        next_run = (now.replace(minute=0, second=0, microsecond=0)
                    + timedelta(hours=1, minutes=1))
        
        _LOGGER.debug("Scheduling next hourly update for %s at %s", 
                     self.price_type, next_run.isoformat())
                     
        self._unsub_hourly = async_track_point_in_time(
            self.hass, self._handle_hourly_update, dt_util.as_utc(next_run)
        )

    async def _handle_hourly_update(self, _):
        """Handle hourly update."""
        _LOGGER.debug("Running scheduled hourly update for %s", self.price_type)
        await self.async_request_refresh()
        self.schedule_hourly_update()

    def schedule_midnight_update(self):
        """Schedule next refresh 1 min after local midnight."""
        if self._unsub_midnight:
            self._unsub_midnight()
            self._unsub_midnight = None
            
        now = dt_util.now()
        # Keep original timing: 1 minute past midnight
        next_mid = (now + timedelta(days=1)).replace(hour=0, minute=1, second=0, microsecond=0)
        
        _LOGGER.debug("Scheduling next midnight update for %s at %s", 
                     self.price_type, next_mid.isoformat())
                     
        self._unsub_midnight = async_track_point_in_time(
            self.hass, self._handle_midnight_update, dt_util.as_utc(next_mid)
        )

    async def _handle_midnight_update(self, _):
        """Handle midnight update."""
        _LOGGER.debug("Running scheduled midnight update for %s", self.price_type)
        await self.async_request_refresh()
        self.schedule_midnight_update()
