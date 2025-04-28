import logging
from datetime import timedelta
import aiohttp
import async_timeout
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.helpers.event import async_track_point_in_time
from homeassistant.util import dt as dt_util
from .const import API_URL, API_TIMEOUT, BUY_ENDPOINT, SELL_ENDPOINT, DOMAIN

_LOGGER = logging.getLogger(__name__)

def convert_price(value):
    try:
        return round(float(str(value).replace(",", ".").strip()), 2)
    except (ValueError, TypeError) as e:
        _LOGGER.warning("Price conversion error: %s", e)
        return None

class PstrykDataUpdateCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, api_key, price_type):
        """Coordinator to fetch both current price and today's table."""
        self.hass = hass
        self.api_key = api_key
        self.price_type = price_type
        self._unsub_hourly = None
        self._unsub_midnight = None

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{price_type}",
            update_interval=None,  # we'll schedule manually
        )

    async def _async_update_data(self):
        """Fetch 48h of frames and extract current + today's list."""
        today_local = dt_util.now().replace(hour=0, minute=0, second=0, microsecond=0)
        window_end_local = today_local + timedelta(days=2)
        start_utc = dt_util.as_utc(today_local).strftime("%Y-%m-%dT%H:%M:%SZ")
        end_utc = dt_util.as_utc(window_end_local).strftime("%Y-%m-%dT%H:%M:%SZ")

        endpoint_tpl = BUY_ENDPOINT if self.price_type == "buy" else SELL_ENDPOINT
        endpoint = endpoint_tpl.format(start=start_utc, end=end_utc)

        try:
            async with aiohttp.ClientSession() as session:
                async with async_timeout.timeout(API_TIMEOUT):
                    resp = await session.get(
                        f"{API_URL}{endpoint}",
                        headers={"Authorization": self.api_key, "Accept": "application/json"}
                    )
                    if resp.status != 200:
                        raise UpdateFailed(f"API error {resp.status}")
                    data = await resp.json()

            frames = data.get("frames", [])
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

            return {
                "prices_today": prices_today,
                "prices": prices,
                "current": current_price,
            }

        except Exception as err:
            raise UpdateFailed(err)

    def schedule_hourly_update(self):
        """Schedule next refresh 1 min after each full hour."""
        if self._unsub_hourly:
            self._unsub_hourly()
        now = dt_util.now()
        next_run = (now.replace(minute=0, second=0, microsecond=0)
                    + timedelta(hours=1, minutes=1))
        self._unsub_hourly = async_track_point_in_time(
            self.hass, self._handle_hourly_update, dt_util.as_utc(next_run)
        )

    async def _handle_hourly_update(self, _):
        await self.async_request_refresh()
        self.schedule_hourly_update()

    def schedule_midnight_update(self):
        """Schedule next refresh 1 min after local midnight."""
        if self._unsub_midnight:
            self._unsub_midnight()
        now = dt_util.now()
        next_mid = (now + timedelta(days=1)).replace(hour=0, minute=1, second=0, microsecond=0)
        self._unsub_midnight = async_track_point_in_time(
            self.hass, self._handle_midnight_update, dt_util.as_utc(next_mid)
        )

    async def _handle_midnight_update(self, _):
        await self.async_request_refresh()
        self.schedule_midnight_update()
