import logging
from datetime import timedelta
from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.event import async_track_point_in_time
from homeassistant.util import dt as dt_util
import aiohttp
import async_timeout
import asyncio

from .const import API_URL, DOMAIN

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(minutes=30)

def convert_price(value):
    try:
        return float(str(value).replace(",", ".").strip())
    except (ValueError, TypeError) as e:
        _LOGGER.warning("Price conversion error: %s", str(e))
        return None

async def async_setup_entry(hass, config_entry, async_add_entities):
    config = config_entry.data
    sensors = [
        PstrykCurrentPriceSensor(config["api_key"], "buy"),
        PstrykCurrentPriceSensor(config["api_key"], "sell"),
        PstrykPriceTableSensor(config["api_key"], "buy", config.get("buy_top", 5)),
        PstrykPriceTableSensor(config["api_key"], "sell", config.get("sell_top", 5))
    ]
    async_add_entities(sensors, True)

class PstrykCurrentPriceSensor(SensorEntity):
    def __init__(self, api_key, price_type):
        self._api_key = api_key
        self._price_type = price_type
        self._state = None
        self._available = True
        self._unsub_update = None

    @property
    def name(self): return f"Pstryk Current {self._price_type.title()} Price"
    
    @property
    def unique_id(self): return f"pstryk_current_{self._price_type}_price"
    
    @property
    def native_value(self): return self._state
    
    @property
    def native_unit_of_measurement(self): return "PLN/kWh"
    
    @property
    def available(self): return self._available

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self._schedule_next_update()

    def _schedule_next_update(self):
        if self._unsub_update:
            self._unsub_update()
        
        now_local = dt_util.now()
        next_midnight_local = (now_local + timedelta(days=1)).replace(
            hour=0, minute=1, second=0, microsecond=0
        )
        next_midnight_utc = dt_util.as_utc(next_midnight_local)

        self._unsub_update = async_track_point_in_time(
            self.hass, 
            self._async_update_task, 
            next_midnight_utc
        )
        
        _LOGGER.debug(
            "Następna aktualizacja %s: %s (Twoja strefa)",
            self._price_type,
            dt_util.as_local(next_midnight_utc).strftime("%Y-%m-%d %H:%M:%S")
        )

    async def _async_update_task(self, _):
        try:
            await self.async_update(no_throttle=True)
            self.async_write_ha_state()
        finally:
            self._schedule_next_update()

    async def async_update(self, **kwargs):
        try:
            today_local = dt_util.now().replace(hour=0, minute=0, second=0, microsecond=0)
            window_end_local = today_local + timedelta(days=1)
            today_utc = dt_util.as_utc(today_local)
            window_end_utc = dt_util.as_utc(window_end_local)
            
            endpoint = "pricing/" if self._price_type == "buy" else "prosumer-pricing/"
            url = f"{API_URL}{endpoint}?resolution=hour&window_start={today_utc.strftime('%Y-%m-%dT%H:%M:%SZ')}&window_end={window_end_utc.strftime('%Y-%m-%dT%H:%M:%SZ')}"

            async with aiohttp.ClientSession() as session:
                response = await session.get(url, headers={"Authorization": self._api_key, "Accept": "application/json"})
                data = await response.json()
                
                now = dt_util.utcnow()
                current_price = None
                for frame in data.get("frames", []):
                    start = dt_util.parse_datetime(frame["start"])
                    end = dt_util.parse_datetime(frame["end"])
                    if start <= now < end:
                        current_price = convert_price(frame["price_gross"])
                        break
                
                self._state = current_price
                self._available = current_price is not None
                _LOGGER.debug(
                    "Zaktualizowano %s: %s PLN (Twoja strefa: %s)",
                    self._price_type,
                    self._state,
                    dt_util.as_local(now).strftime("%Y-%m-%d %H:%M:%S")
                )

        except Exception as e:
            _LOGGER.error("Błąd aktualizacji %s: %s", self._price_type, str(e))
            self._state = None
            self._available = False

    async def async_will_remove_from_hass(self):
        if self._unsub_update:
            self._unsub_update()

class PstrykPriceTableSensor(SensorEntity):
    def __init__(self, api_key, price_type, top_count):
        self._api_key = api_key
        self._price_type = price_type
        self._top_count = top_count
        self._state = None
        self._attributes = {}
        self._available = True
        self._unsub_update = None

    @property
    def name(self): return f"Pstryk {self._price_type.title()} Price Table"
    
    @property
    def unique_id(self): return f"pstryk_{self._price_type}_price_table"
    
    @property
    def native_value(self): return self._state
    
    @property
    def extra_state_attributes(self): return self._attributes
    
    @property
    def available(self): return self._available

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self._schedule_next_update()

    def _schedule_next_update(self):
        if self._unsub_update:
            self._unsub_update()
        
        now_local = dt_util.now()
        next_midnight_local = (now_local + timedelta(days=1)).replace(
            hour=0, minute=1, second=0, microsecond=0
        )
        next_midnight_utc = dt_util.as_utc(next_midnight_local)

        self._unsub_update = async_track_point_in_time(
            self.hass, 
            self._async_update_task, 
            next_midnight_utc
        )

    async def _async_update_task(self, _):
        try:
            await self.async_update(no_throttle=True)
            self.async_write_ha_state()
        finally:
            self._schedule_next_update()

    def _convert_time(self, utc_str):
        try:
            dt_utc = dt_util.parse_datetime(utc_str)
            dt_local = dt_util.as_local(dt_utc)
            return dt_local.strftime("%Y-%m-%d %H:%M:%S")
        except Exception as e:
            _LOGGER.error("Błąd konwersji czasu: %s", str(e))
            return "N/A"

    async def async_update(self, **kwargs):
        try:
            today_local = dt_util.now().replace(hour=0, minute=0, second=0, microsecond=0)
            window_end_local = today_local + timedelta(days=1)
            today_utc = dt_util.as_utc(today_local)
            window_end_utc = dt_util.as_utc(window_end_local)
            
            endpoint = "pricing/" if self._price_type == "buy" else "prosumer-pricing/"
            url = f"{API_URL}{endpoint}?resolution=hour&window_start={today_utc.strftime('%Y-%m-%dT%H:%M:%SZ')}&window_end={window_end_utc.strftime('%Y-%m-%dT%H:%M:%SZ')}"

            async with aiohttp.ClientSession() as session:
                response = await session.get(url, headers={"Authorization": self._api_key, "Accept": "application/json"})
                data = await response.json()
                
                prices = []
                for frame in data.get("frames", []):
                    price = convert_price(frame.get("price_gross"))
                    if price is not None:
                        prices.append({
                            "start": self._convert_time(frame["start"]),
                            "price": price
                        })

                sorted_prices = sorted(prices, key=lambda x: x["price"], reverse=(self._price_type == "sell"))
                self._state = len(prices)
                self._attributes = {
                    "all_prices": [{"start": p["start"], "price": p["price"]} for p in prices],
                    "best_prices": [{"start": p["start"], "price": p["price"]} for p in sorted_prices[:self._top_count]],
                    "top_count": self._top_count,
                    "last_updated": dt_util.as_local(dt_util.utcnow()).isoformat()
                }
                self._available = True
                _LOGGER.debug(
                    "Zaktualizowano tabelę %s (Twoja strefa: %s)",
                    self._price_type,
                    dt_util.as_local(dt_util.utcnow()).strftime("%Y-%m-%d %H:%M:%S")
                )

        except Exception as e:
            _LOGGER.error("Błąd aktualizacji tabeli %s: %s", self._price_type, str(e))
            self._state = None
            self._available = False

    async def async_will_remove_from_hass(self):
        if self._unsub_update:
            self._unsub_update()
